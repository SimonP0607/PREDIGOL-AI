"""Teams audit (database only, 0 requests): identity, logos, venues, squads, coaches and the provider's season
aggregates of every team in a current tracked season.

    python -m scripts.audit_teams

Checks - each an evidence entry when it finds something (area teams):

* a side PrediGol classifies differently from the provider's national flag (``core.team_kind``, refreshed first:
  a side that plays competitive club football is a club, one that plays only national-team competitions is a
  national side) - the provider's flag is wrong both ways for some sides;
* two provider ids for one name and country (possible duplicates; kept apart, reported);
* coverage: logo, venue, a squad read in the last 14 days, the coach's stored profile and photo, the
  provider's season aggregate (core.team_season_stats).

The provider-facing comparison of team statistics is ``scripts.audit_team_stats``.
Report: data/truth/<stamp>-teams/.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.catalog.team_kind import refresh_team_kind
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.truth.v2.ledger import Evidence, clear_unseen, record_all
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")

SCOPE = """
WITH scope AS (
    SELECT DISTINCT t.id FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
      JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
     WHERE c.is_tracked AND cs.is_current)
"""

COVERAGE = SCOPE + """
SELECT count(*) AS teams,
       count(*) FILTER (WHERE t.logo_url IS NOT NULL) AS with_logo,
       count(*) FILTER (WHERE t.venue_id IS NOT NULL) AS with_venue,
       count(*) FILTER (WHERE t.squad_checked_at > now() - interval '14 days') AS squad_fresh,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM core.team_season_stats s WHERE s.team_id = t.id)) AS with_season_stats,
       count(*) FILTER (WHERE COALESCE(t.is_national, false)) AS national
  FROM scope JOIN core.teams t ON t.id = scope.id
"""

COACHES = SCOPE + """
, coach AS (
    SELECT DISTINCT ON (t.id) t.id, l.provider_coach_id
      FROM scope t
      JOIN core.fixtures f ON t.id IN (f.home_team_id, f.away_team_id)
      JOIN core.fixture_lineups l ON l.fixture_id = f.id
                                  AND l.team_side = CASE WHEN f.home_team_id = t.id THEN 'home' ELSE 'away' END
     WHERE l.provider_coach_id > 0
     ORDER BY t.id, f.kickoff_at DESC)
SELECT count(*) AS teams_with_coach,
       count(cp.provider_coach_id) AS coach_profile,
       count(cp.photo_url) AS coach_photo
  FROM coach LEFT JOIN core.coach_profiles_latest cp ON cp.provider_coach_id = coach.provider_coach_id
"""

NATIONAL_MISMATCH = """
SELECT t.id, t.provider_team_id, t.name, t.is_national AS provider_national, k.is_national, k.basis,
       k.competitive_club_matches, k.national_matches, k.club_friendly_matches
  FROM core.team_kind k JOIN core.teams t ON t.id = k.team_id
 WHERE k.is_national IS DISTINCT FROM t.is_national AND k.is_national IS NOT NULL
 ORDER BY t.name
"""
"""Sides PrediGol classifies differently from the provider's flag (fbi.catalog.team_kind) - the product uses
PrediGol's classification."""

DUPLICATES = SCOPE + """
SELECT lower(t.name) AS name, t.country, array_agg(t.provider_team_id ORDER BY t.provider_team_id) AS ids
  FROM scope JOIN core.teams t ON t.id = scope.id
 GROUP BY lower(t.name), t.country HAVING count(*) > 1
"""


def audit(conn: psycopg.Connection[Any]) -> tuple[dict[str, Any], list[Evidence]]:
    refresh_team_kind(conn, at=now())
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(COVERAGE)
        coverage = dict(cur.fetchone() or {})
        cur.execute(COACHES)
        coverage.update(dict(cur.fetchone() or {}))
        cur.execute(NATIONAL_MISMATCH)
        mismatch = [dict(r) for r in cur.fetchall()]
        cur.execute(DUPLICATES)
        dupes = [dict(r) for r in cur.fetchall()]
    items: list[Evidence] = []
    for m in mismatch:
        said = {False: "a club", True: "national", None: "neither (not told)"}[m["provider_national"]]
        ours = "a national side" if m["is_national"] else "a club"
        items.append(Evidence(
            key=f"teams:national_flag:{m['provider_team_id']}", area="teams", issue_type="IDENTITY_MAPPING_ERROR",
            severity="medium", at_fault="provider", entity=f"{m['name']} ({m['provider_team_id']})", status="MONITOR",
            claim=f"the provider flags {m['name']} as {said}; it {m['basis']} - PrediGol treats it as {ours} "
                  "(core.team_kind) and the product never shows it in the other role",
            db={"provider_national": m["provider_national"], "is_national": m["is_national"], "basis": m["basis"],
                "competitive_club_matches": m["competitive_club_matches"],
                "national_matches": m["national_matches"], "club_friendly_matches": m["club_friendly_matches"]},
            fix="core.team_kind (migration 0060): national or club from the competitions a side plays",
            test="tests/integration/test_team_player_audits.py"))
    for d in dupes:
        items.append(Evidence(
            key=f"teams:duplicate:{d['name']}:{d['country']}", area="teams", issue_type="DUPLICATE_ENTITY",
            severity="low", at_fault="provider", entity=f"{d['name']} ({d['country']})", status="MONITOR",
            claim=f"one name and country, {len(d['ids'])} provider ids {d['ids']}: kept apart, never merged silently",
            db={"provider_team_ids": d["ids"]}))
    n = int(coverage.get("teams") or 0)
    for col, label in (("with_logo", "a logo"), ("squad_fresh", "a squad read in the last 14 days")):
        missing = n - int(coverage.get(col) or 0)
        if missing:
            items.append(Evidence(
                key=f"teams:coverage:{col}", area="teams", issue_type="PROVIDER_COVERAGE", severity="info",
                at_fault="undetermined", status="MONITOR",
                claim=f"{missing} of {n} teams of current tracked seasons have no {label}", db={"teams": n}))
    summary = {"coverage": coverage, "national_flag_mismatch": len(mismatch), "possible_duplicates": len(dupes)}
    return {"summary": summary, "national_flag_mismatch": mismatch, "duplicates": dupes}, items


def markdown(result: dict[str, Any]) -> str:
    s = result["summary"]
    c = s["coverage"]
    n = int(c.get("teams") or 0) or 1
    lines = ["# Teams audit", "", f"{c.get('teams')} teams in current tracked seasons ({c.get('national')} national).",
             "", "| Check | Teams | Share |", "|---|---:|---:|"]
    for k in ("with_logo", "with_venue", "squad_fresh", "with_season_stats", "teams_with_coach", "coach_profile",
              "coach_photo"):
        lines.append(f"| {k} | {c.get(k)} | {100 * int(c.get(k) or 0) / n:.0f}% |")
    lines += ["", f"National flag mismatches: {s['national_flag_mismatch']}; possible duplicates: "
                  f"{s['possible_duplicates']}.", ""]
    for m in result["national_flag_mismatch"][:40]:
        lines.append(f"* {m['name']} ({m['provider_team_id']}): provider national={m['provider_national']}, PrediGol "
                     f"national={m['is_national']} - {m['basis']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    at = now()
    with psycopg.connect(settings.database.psycopg_url, autocommit=True) as conn:
        conn.execute("SET statement_timeout = '300s'")
        run = V2Run(conn, None, "teams", at, params={})
        result, items = audit(conn)
        codes = record_all(conn, items, at=at, run_id=run.run_id)
        for prefix in ("teams:national_flag:", "teams:duplicate:", "teams:coverage:"):
            clear_unseen(conn, area="teams", scope_prefix=prefix, seen=[e.key for e in items], at=at)
        folder = write_report(REPORTS, "teams", at, result, markdown(result))
        status = run.finish({**result["summary"], "evidence": len(codes)}, report_dir=folder)
    print(json.dumps({**result["summary"], "evidence": len(codes), "report": str(folder), "status": status},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
