"""Players audit (database only, 0 requests): photos, profiles, current club vs national team, and the provider's
reference lists of every player who played in a current tracked season.

    python -m scripts.audit_players

Checks - each an evidence entry when it finds something (area players):

* the club the product shows is never a national side, and the national team never a club (the product query
  itself is run over every player in scope - ``fbi.api.repositories.center``);
* a player whose newest squad is a national side's but who has no club at all is reported (the product then
  shows no club rather than the national team);
* coverage: photo, profile (birth date), the provider's season aggregate, and whether the provider's
  sidelined / trophies lists were asked (core.reference_checks);
* match rows the provider rated 0 (a player it did not rate - MONITOR, the provider's).

The provider-facing comparison of player statistics is ``scripts.audit_player_stats``.
Report: data/truth/<stamp>-players/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.api.repositories.center import PLAYER_AGG, PLAYER_TEAMS_COLUMNS, TEAMS_OF_PLAYER
from fbi.api.services.center import PLAYER_WINDOW
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.truth.v2.ledger import Evidence, clear_unseen, record_all
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")

SCOPE = """
WITH scope AS (
    SELECT DISTINCT ps.provider_player_id FROM core.fixture_player_stats ps
      JOIN core.fixtures f ON f.id = ps.fixture_id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
     WHERE c.is_tracked AND cs.is_current AND ps.provider_player_id > 0 AND COALESCE(ps.minutes, 0) > 0)
"""

COVERAGE = SCOPE + """
SELECT count(*) AS players,
       count(p.id) AS with_profile_row,
       count(p.photo_url) AS with_photo,
       count(p.birth_date) AS with_birth_date,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM core.player_season_stats s
                                       WHERE s.provider_player_id = scope.provider_player_id)) AS with_season_stats,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM core.reference_checks k WHERE k.feed = 'sidelined_players'
                                         AND k.target = 'player:' || scope.provider_player_id)) AS sidelined_asked,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM core.reference_checks k WHERE k.feed = 'trophies_players'
                                         AND k.target = 'player:' || scope.provider_player_id)) AS trophies_asked
  FROM scope LEFT JOIN core.players p ON p.provider_player_id = scope.provider_player_id
"""

CLUBS = SCOPE + """
SELECT p.id, p.provider_player_id, p.name,""" + PLAYER_TEAMS_COLUMNS + """,
       COALESCE(ck.is_national, club.is_national, false) AS club_is_national,
       COALESCE(nk.is_national, nat.is_national, true) AS national_is_national,
       club.is_national AS club_provider_flag
  FROM scope JOIN core.players p ON p.provider_player_id = scope.provider_player_id
  LEFT JOIN LATERAL (""" + PLAYER_AGG + """) a ON true""" + TEAMS_OF_PLAYER + """
"""


RATING_ZERO = """
SELECT count(*) AS rows, count(*) FILTER (WHERE COALESCE(ps.minutes, 0) > 0) AS with_minutes,
       count(DISTINCT ps.fixture_id) FILTER (WHERE COALESCE(ps.minutes, 0) > 0) AS fixtures,
       count(DISTINCT f.competition_season_id) FILTER (WHERE COALESCE(ps.minutes, 0) > 0) AS seasons,
       (array_agg(DISTINCT f.provider_fixture_id) FILTER (WHERE COALESCE(ps.minutes, 0) > 0))[1:5] AS examples
  FROM core.fixture_player_stats ps JOIN core.fixtures f ON f.id = ps.fixture_id
 WHERE ps.rating = 0
"""
"""Match rows the provider rated 0: a player it did not rate (fbi.api.repositories.center.RATING_NOTE)."""


def audit(conn: psycopg.Connection[Any]) -> tuple[dict[str, Any], list[Evidence]]:
    since = now() - PLAYER_WINDOW
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COVERAGE)
        coverage = dict(cur.fetchone() or {})
        cur.execute(CLUBS, {"since": since})
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute(RATING_ZERO)
        zero = dict(cur.fetchone() or {})
    club_national = [r for r in rows if r["team_id"] is not None and r["club_is_national"]]
    national_club = [r for r in rows if r["national_team_id"] is not None and not r["national_is_national"]]
    no_club = [r for r in rows if r["team_id"] is None and r["national_team_id"] is not None]
    items: list[Evidence] = []
    for r in club_national:
        items.append(Evidence(
            key=f"players:club_is_national:{r['provider_player_id']}", area="players",
            issue_type="IDENTITY_MAPPING_ERROR", severity="critical", at_fault="predigol",
            entity=f"{r['name']} ({r['provider_player_id']})",
            claim=f"{r['name']}'s club is shown as {r['team']}, a national side", db={"team_id": r["team_id"]}))
    for r in national_club:
        items.append(Evidence(
            key=f"players:national_is_club:{r['provider_player_id']}", area="players",
            issue_type="IDENTITY_MAPPING_ERROR", severity="high", at_fault="predigol",
            entity=f"{r['name']} ({r['provider_player_id']})",
            claim=f"{r['name']}'s national team is shown as {r['national_team']}, a club",
            db={"national_team_id": r["national_team_id"]}))
    if int(zero.get("with_minutes") or 0):
        items.append(Evidence(
            key="players:rating_zero", area="players", issue_type="PROVIDER_DEFINED_METRIC", severity="low",
            at_fault="provider", status="MONITOR",
            claim=f"the provider sent a rating of 0 for {zero['with_minutes']} match rows with minutes "
                  f"({zero['fixtures']} matches, {zero['seasons']} competition seasons; {zero['rows']} rows in all): a "
                  "player it did not rate - and its season ratings average those zeros",
            db={k: zero.get(k) for k in ("rows", "with_minutes", "fixtures", "seasons", "examples")},
            root_cause="the provider's sentinel for 'not rated' is 0 in some matches (null in most)",
            fix="stored as sent; product reads show no rating for a 0 and average only real ratings; the provider's "
                "season rating in the top lists says how many unrated matches it counts (unrated_matches)",
            test="tests/integration/test_reference_api.py"))
    corrected = [r for r in rows if r["team_id"] is not None and r["club_provider_flag"] is True]
    summary = {"coverage": coverage, "players_checked": len(rows), "club_is_national": len(club_national),
               "club_flagged_national_by_the_provider": len(corrected),
               "national_is_club": len(national_club), "national_team_only": len(no_club),
               "club_source": {k: sum(1 for r in rows if r["club_source"] == k) for k in ("squad", "appearances")},
               "rating_zero": {k: zero.get(k) for k in ("rows", "with_minutes", "fixtures", "seasons")}}
    return {"summary": summary, "club_is_national": club_national[:50], "national_is_club": national_club[:50],
            "national_team_only": [{"name": r["name"], "national_team": r["national_team"]} for r in no_club[:50]]}, items


def markdown(result: dict[str, Any]) -> str:
    s = result["summary"]
    c = s["coverage"]
    n = int(c.get("players") or 0) or 1
    lines = ["# Players audit", "", f"{c.get('players')} players who played in a current tracked season.", "",
             "| Check | Players | Share |", "|---|---:|---:|"]
    for k in ("with_profile_row", "with_photo", "with_birth_date", "with_season_stats", "sidelined_asked",
              "trophies_asked"):
        lines.append(f"| {k} | {c.get(k)} | {100 * int(c.get(k) or 0) / n:.0f}% |")
    lines += ["", f"Product query over {s['players_checked']} players: club shown is a national side "
                  f"{s['club_is_national']}, national team shown is a club {s['national_is_club']}; "
                  f"national team only (no club known) {s['national_team_only']}. Club from the newest squad "
                  f"{s['club_source']['squad']}, from the last appearance {s['club_source']['appearances']}.",
              "", f"Match rows the provider rated 0 (not rated): {s['rating_zero']['with_minutes']} with minutes, "
                  f"{s['rating_zero']['rows']} in all - shown as no rating, never averaged in."]
    return "\n".join(lines) + "\n"


def main() -> int:
    at = now()
    with psycopg.connect(settings.database.psycopg_url, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '900s'")
        run = V2Run(conn, None, "players", at, params={})
        result, items = audit(conn)
        codes = record_all(conn, items, at=at, run_id=run.run_id)
        for prefix in ("players:club_is_national:", "players:national_is_club:", "players:rating_zero"):
            clear_unseen(conn, area="players", scope_prefix=prefix, seen=[e.key for e in items], at=at)
        folder = write_report(REPORTS, "players", at, result, markdown(result))
        status = run.finish({**result["summary"], "evidence": len(codes)}, report_dir=folder)
    print(json.dumps({**result["summary"], "evidence": len(codes), "report": str(folder), "status": status},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
