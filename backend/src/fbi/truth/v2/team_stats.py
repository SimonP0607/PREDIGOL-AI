"""Team statistics truth: /teams/statistics (league + season + team) against what our fixtures say
for exactly that league and season, and against what the product shows as a team's record.

The provider's numbers are per competition and season ("Returns the statistics of a team in
relation to a given competition and season", updated twice a day). PrediGol stores no copy of
them (``core.team_season_stats`` is empty); every team figure is computed from our fixtures. So
two questions per team:

1. Same scope, same numbers? Our finished fixtures of that league-season, recomputed, against
   the provider's played / wins / draws / losses / goals / clean sheets / failed to score, home,
   away and total. A difference is ours (a missing result: MISSING_BACKFILL), the provider's (a
   match it has not counted twice-daily: PROVIDER_STALE) or a result that differs
   (RESULT_MISMATCH, undetermined until the fixture is compared).
2. Does the product say what scope it shows? The team page's "record" is every recorded result
   of the team in every competition and season (``catalog.team_record``); shown next to a
   provider-style season table it reads as a wrong number. That is PRODUCT_SCOPE.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth.v2.ledger import Evidence

PROVIDER_REFRESH = timedelta(hours=14)
"""Twice a day plus slack: a match that ended earlier than this should be in the provider's figures."""
SIDES = ("home", "away", "total")
KEYS = ("played", "wins", "draws", "loses", "goals_for", "goals_against", "clean_sheet", "failed_to_score")


def _d(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@dataclass
class Figures:
    """Each KEY per side (home / away / total)."""

    values: dict[str, dict[str, int | None]] = field(default_factory=dict)
    form: str | None = None

    def get(self, key: str, side: str = "total") -> int | None:
        return self.values.get(key, {}).get(side)

    def flat(self) -> dict[str, int | None]:
        return {f"{k}.{s}": self.get(k, s) for k in KEYS for s in SIDES}


def parse(body: Mapping[str, Any]) -> Figures | None:
    """The comparable part of a /teams/statistics answer; None when the provider has none."""
    resp = body.get("response")
    if not isinstance(resp, dict) or not resp:
        return None
    fx = _d(resp.get("fixtures"))
    goals = _d(resp.get("goals"))
    out = Figures(form=resp.get("form") if isinstance(resp.get("form"), str) else None)
    for key in ("played", "wins", "draws", "loses"):
        block = _d(fx.get(key))
        out.values[key] = {s: _int(block.get(s)) for s in SIDES}
    for key, name in (("goals_for", "for"), ("goals_against", "against")):
        block = _d(_d(goals.get(name)).get("total"))
        out.values[key] = {s: _int(block.get(s)) for s in SIDES}
    for key in ("clean_sheet", "failed_to_score"):
        block = _d(resp.get(key))
        out.values[key] = {s: _int(block.get(s)) for s in SIDES}
    return out


FIXTURES_SQL = """
SELECT f.provider_fixture_id, f.kickoff_at, f.status_short, f.home_team_id = %(team)s AS at_home,
       r.goals_home, r.goals_away, r.ft_goals_home, r.ft_goals_away, r.et_goals_home, r.et_goals_away,
       r.pen_home, r.pen_away
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE c.provider_league_id = %(league)s AND cs.season = %(season)s AND f.status_group = 'finished'
   AND %(team)s IN (f.home_team_id, f.away_team_id) AND r.goals_home IS NOT NULL AND r.goals_away IS NOT NULL
 ORDER BY f.kickoff_at
"""


def recompute(rows: Sequence[Mapping[str, Any]], *, shootout_decides: bool = False) -> Figures:
    """Our fixtures' figures: the final score (extra time included), wins/draws/losses from it, clean
    sheet = conceded 0, failed to score = scored 0. With ``shootout_decides`` a match settled on
    penalties counts as won/lost and the shoot-out winner gets one goal - the provider's own rule for
    /teams/statistics (found by this audit: Inter's 2025 Super Cup, City's and Barcelona's friendlies)."""
    acc = {k: dict.fromkeys(SIDES, 0) for k in KEYS}
    form = []
    for r in rows:
        side = "home" if r["at_home"] else "away"
        gf = int(r["goals_home"] if r["at_home"] else r["goals_away"])
        ga = int(r["goals_away"] if r["at_home"] else r["goals_home"])
        pen_for = r.get("pen_home") if r["at_home"] else r.get("pen_away")
        pen_against = r.get("pen_away") if r["at_home"] else r.get("pen_home")
        if shootout_decides and gf == ga and pen_for is not None and pen_against is not None \
                and pen_for != pen_against:
            gf, ga = (gf + 1, ga) if pen_for > pen_against else (gf, ga + 1)
        res = "wins" if gf > ga else "draws" if gf == ga else "loses"
        form.append({"wins": "W", "draws": "D", "loses": "L"}[res])
        for s in (side, "total"):
            acc["played"][s] += 1
            acc[res][s] += 1
            acc["goals_for"][s] += gf
            acc["goals_against"][s] += ga
            acc["clean_sheet"][s] += int(ga == 0)
            acc["failed_to_score"][s] += int(gf == 0)
    return Figures({k: dict(v) for k, v in acc.items()}, form="".join(form) or None)


def our_fixtures(conn: psycopg.Connection[Any], *, league: int, season: int, team_id: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"league": league, "season": season, "team": team_id})
        return [dict(r) for r in cur.fetchall()]


def product_record(conn: psycopg.Connection[Any], team_id: int) -> dict[str, Any]:
    """What the team page shows NOW as the team's record - its headline (the domestic league's latest
    season; a national side: its latest competition) and the lifetime figure it labels apart - read
    through the product's own code (``team_records`` + ``team_record_sections``), not a copy of it.

    ``competitions`` is how many competitions the HEADLINE adds up (1 when it is one competition and
    season); ``lifetime_*`` describe the labelled lifetime line."""
    from fbi.api.repositories.catalog import team_records
    from fbi.api.services.catalog import team_record_sections

    head, campaign, lifetime = team_record_sections(team_records(conn, team_id))
    h, life = head.data, lifetime.data
    if h is None:
        return {}
    return {"played": h.played, "won": h.won, "drawn": h.drawn, "lost": h.lost, "goals_for": h.goals_for,
            "goals_against": h.goals_against, "scope": h.scope, "competition": h.competition, "season": h.season,
            "competitions": h.competitions if h.scope == "all" else 1,
            "campaign_rows": len(campaign.data or []),
            "lifetime_played": life.played if life else None, "lifetime_competitions": life.competitions if life else None,
            "lifetime_scope": life.scope if life else None}


@dataclass
class TeamAudit:
    league: int
    season: int
    team: int
    """provider team id"""
    name: str
    verdict: str = "ok"
    """ok | provider_behind | ours_missing | result_mismatch | shootout_rule | provider_lag_expected | no_api"""
    api: dict[str, int | None] = field(default_factory=dict)
    ours: dict[str, int | None] = field(default_factory=dict)
    differences: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)
    api_form: str | None = None
    our_form: str | None = None
    last_finished: datetime | None = None
    product: dict[str, Any] = field(default_factory=dict)
    payload_hash: str | None = None


def judge(api: Figures | None, ours: Figures, *, last_finished: datetime | None,
          at: datetime) -> tuple[str, dict[str, tuple[int | None, int | None]]]:
    if api is None:
        return ("no_api" if ours.get("played") else "no_data"), {}
    differences = {k: (a, b) for k, a in api.flat().items() for b in [ours.flat().get(k)] if a != b}
    if not differences:
        return "ok", {}
    a_played, o_played = api.get("played") or 0, ours.get("played") or 0
    if o_played > a_played:
        if last_finished and at - last_finished < PROVIDER_REFRESH:
            return "provider_lag_expected", differences
        return "provider_behind", differences
    if o_played < a_played:
        return "ours_missing", differences
    return "result_mismatch", differences


def audit_team(api_body: Mapping[str, Any] | None, rows: Sequence[Mapping[str, Any]], *, league: int, season: int,
               team: int, name: str, at: datetime, product: dict[str, Any] | None = None,
               payload_hash: str | None = None) -> TeamAudit:
    api = parse(api_body or {}) if api_body is not None else None
    ours = recompute(list(rows))
    last = max((r["kickoff_at"] for r in rows), default=None)
    verdict, differences = judge(api, ours, last_finished=last, at=at)
    if verdict == "result_mismatch" and api is not None:
        provider_way = recompute(list(rows), shootout_decides=True)
        if judge(api, provider_way, last_finished=last, at=at)[0] == "ok":
            verdict = "shootout_rule"
    return TeamAudit(league, season, team, name, verdict, api.flat() if api else {}, ours.flat(), differences,
                     api.form if api else None, ours.form, last, product or {}, payload_hash)


def evidence(a: TeamAudit, api_ref: Mapping[str, Any] | None) -> list[Evidence]:
    key = f"team_stats:{a.league}:{a.season}:{a.team}"
    label = f"{a.name} ({a.team}) in league {a.league} {a.season}"
    diffs = {k: list(v) for k, v in a.differences.items()}
    api = {**(dict(api_ref) if api_ref else {}), "differences": diffs}
    db = {"recomputed_from_fixtures": True, "last_finished_kickoff": a.last_finished}
    if a.verdict == "ours_missing":
        return [Evidence(key=f"{key}:ours_missing", area="team_stats", issue_type="MISSING_BACKFILL", severity="high",
                         at_fault="predigol", entity=label,
                         claim=f"{label}: the provider counts {a.api.get('played.total')} games, our finished "
                               f"fixtures {a.ours.get('played.total')}",
                         api=api, db=db, root_cause="finished fixtures or results missing for this league-season",
                         fix="re-sync the season's full fixture list")]
    if a.verdict == "provider_behind":
        return [Evidence(key=f"{key}:provider_behind", area="team_stats", issue_type="PROVIDER_STALE",
                         severity="medium", at_fault="provider", entity=label,
                         claim=f"{label}: our fixtures have {a.ours.get('played.total')} finished games, the "
                               f"provider's team statistics {a.api.get('played.total')} (last match "
                               f"{a.last_finished})",
                         api=api, db=db, root_cause="/teams/statistics is refreshed twice a day and lags")]
    if a.verdict == "result_mismatch":
        return [Evidence(key=f"{key}:result_mismatch", area="team_stats", issue_type="TEAM_STATS_MISMATCH",
                         severity="medium", at_fault="undetermined", entity=label,
                         claim=f"{label}: same games, different figures ({', '.join(diffs)})",
                         api=api, db=db,
                         root_cause="a result or a home/away side differs between /teams/statistics and "
                                    "/fixtures, or the provider counts a game differently (awarded, shoot-out)")]
    return []


def shootout_evidence(audits: Sequence[TeamAudit]) -> Evidence | None:
    """One entry: the provider's team statistics count a shoot-out as a win/loss (+1 goal)."""
    hits = [a for a in audits if a.verdict == "shootout_rule"]
    if not hits:
        return None
    ex = [{"team": a.team, "name": a.name, "league": a.league, "season": a.season, "differences":
           {k: list(v) for k, v in a.differences.items()}} for a in hits[:6]]
    return Evidence(
        key="team_stats:provider_rule:shootout", area="team_stats", issue_type="PROVIDER_DEFINED_METRIC",
        severity="info", at_fault="none", entity=f"{len(hits)} team-seasons",
        claim="/teams/statistics counts a match settled on penalties as won/lost and gives the shoot-out winner one "
              "goal; our fixtures (and football's result) keep it a draw - figures differ by definition only",
        api={"examples": ex}, root_cause="provider definition", status="ACCEPTED",
        fix="never compare those two numbers without saying which rule each uses")


def scope_evidence(audits: list[TeamAudit]) -> Evidence | None:
    """One entry for the product's scope: the team page's headline record mixes competitions or seasons
    (until 4 Oct 2026 it added every competition and season, unlabelled)."""
    mixed = [a for a in audits if a.product and ((a.product.get("competitions") or 0) > 1
                                                 or a.product.get("scope", "all") != "competition_season")]
    if not mixed:
        return None
    ex = [{"team": a.team, "name": a.name, "provider_league_season_played": a.api.get("played.total"),
           "team_page_record_played": a.product.get("played"), "competitions": a.product.get("competitions"),
           "seasons": a.product.get("seasons"), "since": a.product.get("first")} for a in mixed[:8]]
    return Evidence(
        key="team_stats:product_scope:team_record", area="team_stats", issue_type="PRODUCT_SCOPE", severity="high",
        at_fault="predigol", entity="team page record (catalog.team_record)",
        claim=f"The team page's record adds every recorded result of the team in every competition and season "
              f"({len(mixed)} of {len(audits)} audited teams mix several competitions); the provider's team "
              "statistics, the widget and the standings are per league and season",
        api={"examples": ex}, db={"query": "fbi.api.repositories.catalog.team_record"},
        root_cause="aggregation scope: no league/season filter, national-team, cup and friendly results included",
        fix="record per competition and season (default: the current domestic league), the scope written on the "
            "page; the lifetime figure only labelled as such")
