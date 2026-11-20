"""The tables of a competition season computed from its rules file, for a reader's page (plan PM, PM-09-04; BE-082).

Reads the season's matches (and those of the earlier seasons an average counts), applies the competition's decisions and computes
with ``fbi.competitions.season_tables`` (BE-075) - the same function the shadow check runs (``scripts.competition_tables``). It adds
only what a page needs to draw it: PrediGol's team ids, names and crests, and the matches still to be decided with the tables each
counts in (for the calculator, PM-09-03). Nothing is estimated and no probability is computed.

Behind ``FBI_COMPETITION_TABLES`` (off: 404, the owner's preview too) until the owner signs the cotejo (DOC-008) and DM-14. The answer
is kept five minutes.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal

from fbi.api.cache import shared
from fbi.api.contracts.season_tables import (
    Champion,
    PointsRule,
    RemainingMatch,
    SeasonPlace,
    SeasonRecord,
    SeasonTable,
    SeasonTableRow,
    SeasonTables,
    SeasonTeam,
    SeasonZone,
    TieScope,
)
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.competitions import rules as rl
from fbi.competitions import season_tables as st
from fbi.core.clock import now

CACHE_SECONDS: Final = 300

COMPETITION_SQL: Final = """
SELECT c.id, c.provider_league_id,
       (SELECT max(s.season) FROM core.competition_seasons s
         WHERE s.competition_id = c.id AND EXISTS (SELECT 1 FROM core.fixtures f WHERE f.competition_season_id = s.id)) AS newest
  FROM core.competitions c WHERE c.id = %(c)s
"""
MATCHES_SQL: Final = """
SELECT s.season, f.id AS fixture_id, f.provider_fixture_id, f.round, f.status_short, f.kickoff_at,
       th.provider_team_id AS home, ta.provider_team_id AS away,
       r.goals_home, r.goals_away, r.pen_home, r.pen_away
  FROM core.fixtures f
  JOIN core.competition_seasons s ON s.id = f.competition_season_id
  JOIN core.competitions c ON c.id = s.competition_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE c.provider_league_id = %(league)s AND s.season = ANY(%(seasons)s)
 ORDER BY f.kickoff_at, f.id
"""
TEAMS_SQL: Final = """
SELECT t.id, t.provider_team_id, t.name, t.logo_url FROM core.teams t WHERE t.provider_team_id = ANY(%(ids)s)
"""


def _int(v: Any) -> int | None:
    return None if v is None else int(v)


def seasons_needed(rules: rl.CompetitionRules, season: int) -> list[int]:
    """The season and every earlier season an average of the rules counts."""
    return sorted({season, *(p.season for t in rules.tables for p in t.past)})


def _matches(rows: Sequence[Mapping[str, Any]]) -> list[st.Match]:
    return [st.Match(int(r["season"]), int(r["provider_fixture_id"]), None if r["round"] is None else str(r["round"]),
                     str(r["status_short"]), int(r["home"]), int(r["away"]), _int(r["goals_home"]), _int(r["goals_away"]),
                     _int(r["pen_home"]), _int(r["pen_away"]))
            for r in rows]


def table_keys_of(rules: rl.CompetitionRules, round_label: str | None) -> list[str]:
    """The keys of the tables of the rules that count a match of this round (its phase matches one of their ``counts``)."""
    found = rules.phase_of_round(round_label)
    if found is None:
        return []
    ref = f"{found[0].key}.{found[1].key}"
    return [t.key for t in rules.tables if any(fnmatch.fnmatchcase(ref, pat) for pat in t.counts)]


def _team(teams: Mapping[int, Mapping[str, Any]], provider_id: int) -> SeasonTeam:
    row = teams.get(provider_id)
    if row is None:
        return SeasonTeam(team_id=None, provider_team_id=provider_id, name=f"#{provider_id}", logo_url=None)
    return SeasonTeam(team_id=int(row["id"]), provider_team_id=provider_id, name=str(row["name"]),
                      logo_url=None if row["logo_url"] is None else str(row["logo_url"]))


def _row(r: Mapping[str, Any], kind: str, teams: Mapping[int, Mapping[str, Any]]) -> SeasonTableRow:
    base: dict[str, Any] = {"position": int(r["position"]), "team": _team(teams, int(r["team"])), "played": int(r["played"]),
                            "points": int(r["points"]), "shared_with": [int(x) for x in r.get("shared_with") or ()],
                            "decided_by": r.get("decided_by"), "open_on": r.get("open_on")}
    if kind == "average":
        scope = r.get("tie_scope")
        return SeasonTableRow(
            **base, average=r["average"], average_3=r["average_3"], average_3_cut=r["average_3_cut"],
            seasons=[SeasonRecord(season=int(s), played=int(v["played"]), points=int(v["points"]))
                     for s, v in sorted((r.get("seasons") or {}).items())],
            window=[int(s) for s in r.get("window") or ()],
            tie_scope=None if scope is None else TieScope(**scope))
    return SeasonTableRow(**base, wins=r["wins"], draws=r["draws"], losses=r["losses"], goals_for=r["goals_for"],
                          goals_against=r["goals_against"], goal_difference=r["goal_difference"])


def _table(reading: st.TableReading, rule: rl.Table, teams: Mapping[int, Mapping[str, Any]]) -> SeasonTable:
    kind: Literal["aggregate", "average"] = "average" if reading.kind == "average" else "aggregate"
    places = [SeasonPlace(competition=p["competition"], article=p.get("article"), slot=p["slot"], source=p["source"],
                          of=p.get("of"), team=None if p.get("team") is None else _team(teams, int(p["team"])),
                          position=p.get("position"), state=p["state"], reason=p.get("reason"))
              for p in reading.places]
    return SeasonTable(
        key=reading.key, name=reading.name, kind=kind, complete=reading.complete, pending_matches=reading.pending,
        unverified_decisions=reading.unverified_decisions,
        tiebreakers=[str(tb.criterion) for tb in rule.ranking.tiebreakers], counts=list(rule.counts),
        rows=[_row(r, kind, teams) for r in reading.rows],
        zones=[SeasonZone(kind=z["kind"], target=z.get("target"), positions=list(z["positions"]),
                          teams=[int(t) for t in z["teams"]], state=z["state"], note=z.get("note")) for z in reading.zones],
        places=places, rounding=dict(reading.rounding), note=reading.note)  # type: ignore[arg-type]


def build(conn: Conn, competition_id: int, season: int | None = None) -> Envelope[SeasonTables | None]:
    comp = fetch_one(conn, COMPETITION_SQL, {"c": competition_id})
    if comp is None:
        raise ApiError(404, "not_found", "competition not found")
    league = int(comp["provider_league_id"])
    chosen = season if season is not None else _int(comp["newest"])
    if chosen is None:
        return unavailable(None, "This competition has no season stored.", status=DataStatus.EMPTY)
    answer = rl.rules_for(league, chosen)
    if not isinstance(answer, rl.Coded) or not answer.rules.tables:
        return unavailable(None, "PrediGol computes no season table for this competition: its rules file has none "
                                 "(today only the Primera A of Colombia).", status=DataStatus.EMPTY)
    rules = answer.rules
    raw = fetch_all(conn, MATCHES_SQL, {"league": league, "seasons": seasons_needed(rules, chosen)})
    matches = _matches(raw)
    if not any(m.season == chosen for m in matches):
        return unavailable(None, f"No match of season {chosen} is stored.", status=DataStatus.EMPTY)
    reading = st.compute(rules, chosen, matches, decisions=st.load_decisions(league))
    ids = sorted({t for m in matches for t in (m.home, m.away)})
    teams = {int(r["provider_team_id"]): r for r in fetch_all(conn, TEAMS_SQL, {"ids": ids})}
    remaining: list[RemainingMatch] = []
    for r in raw:
        if int(r["season"]) != chosen or str(r["status_short"]) in st.DECIDED:
            continue
        keys = table_keys_of(rules, None if r["round"] is None else str(r["round"]))
        if not keys:
            continue
        remaining.append(RemainingMatch(
            fixture_id=int(r["fixture_id"]), provider_fixture_id=int(r["provider_fixture_id"]),
            round=None if r["round"] is None else str(r["round"]), kickoff_at=r["kickoff_at"],
            home=_team(teams, int(r["home"])), away=_team(teams, int(r["away"])), tables=keys))
    champions = [Champion(tournament=k, team=None if v.get("team") is None else _team(teams, int(v["team"])),
                          state="calculado" if v.get("team") is not None else "pendiente")
                 for k, v in reading.champions.items()]
    return ok(SeasonTables(
        computed_by=reading.version, competition_id=competition_id, league_id=league, season=chosen,
        rules_version=rules.version, rules_file=answer.file.path, rules_sha256=answer.file.sha256,
        points=PointsRule(win=rules.points.win, draw=rules.points.draw, loss=rules.points.loss),
        tables=[_table(tr, rules.table(tr.key), teams) for tr in reading.tables],
        champions=champions, remaining=remaining, unverified_decisions=reading.decisions.unverified,
        computed_at=now()))


@shared(CACHE_SECONDS)
def _cached(conn: Conn, competition_id: int, season: int | None) -> Envelope[SeasonTables | None]:
    return build(conn, competition_id, season)


def season_tables(conn: Conn, competition_id: int, season: int | None = None) -> Envelope[SeasonTables | None]:
    """404 while ``FBI_COMPETITION_TABLES`` is off; the tables of the season (its newest by default) otherwise."""
    if not st.switch_on():
        raise ApiError(404, "not_found", "not found")
    return _cached(conn, competition_id, season)
