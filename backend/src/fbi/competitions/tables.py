"""Stored league tables read together with the season's structure (``phases``): the table a match is
shown with, and a competition season's tables kept apart by stage, phase and group.

Reads ``core.standings`` (one row per team per table per snapshot; the table is ``group_key``) and
``core.fixtures`` (round labels, kick-offs, finished or not). Writes nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.competitions.phases import (
    Choice,
    Match,
    RoundCount,
    Stage,
    TableIn,
    TableMap,
    choose,
    map_tables,
    stage_of,
    stages_from_rounds,
)

DECIDED = "(f.status_group = 'finished' OR f.status_short IN ('AWD', 'WO'))"
"""A match a table counts: played to the end, or decided off the pitch (a technical loss, a walkover:
status group 'cancelled' in core.fixtures, but every table counts it - Libertadores 2026 Medellin v
Flamengo)."""

ROUNDS_SQL = f"""
SELECT f.round, min(f.kickoff_at) AS first_kickoff, max(f.kickoff_at) AS last_kickoff, count(*) AS fixtures,
       count(*) FILTER (WHERE {DECIDED}) AS finished
  FROM core.fixtures f WHERE f.competition_season_id = %(cs)s GROUP BY f.round
"""

MATCHES_SQL = f"""
SELECT f.round, f.home_team_id, f.away_team_id, f.kickoff_at, {DECIDED} AS finished
  FROM core.fixtures f WHERE f.competition_season_id = %(cs)s AND f.kickoff_at IS NOT NULL
"""

SNAPSHOTS_SQL = """
(SELECT DISTINCT snapshot_at FROM core.standings WHERE competition_season_id = %(cs)s AND snapshot_at <= %(ko)s
  ORDER BY snapshot_at DESC LIMIT %(before)s)
UNION ALL
(SELECT DISTINCT snapshot_at FROM core.standings WHERE competition_season_id = %(cs)s AND snapshot_at > %(ko)s
  ORDER BY snapshot_at LIMIT %(after)s)
"""

NEWEST_SQL = "SELECT max(snapshot_at) AS at FROM core.standings WHERE competition_season_id = %(cs)s"

TIMES_SQL = "SELECT DISTINCT snapshot_at FROM core.standings WHERE competition_season_id = %(cs)s ORDER BY 1"

PLAYED_SQL = """
SELECT snapshot_at, group_key, team_id, played FROM core.standings
 WHERE competition_season_id = %(cs)s AND snapshot_at = ANY(%(at)s)
 ORDER BY snapshot_at, group_key, rank NULLS LAST, team_id
"""

BEFORE = 6
"""Snapshots before kick-off tried, newest first, before any taken after it (a stage's table that
the provider dropped from later answers is still found in an earlier one)."""
AFTER = 3


@dataclass(frozen=True)
class Season:
    cs_id: int
    stages: list[Stage]
    matches: list[Match]


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def load_season(conn: psycopg.Connection[Any], cs_id: int) -> Season:
    rounds = [RoundCount(r["round"], r["first_kickoff"], r["last_kickoff"], int(r["fixtures"]), int(r["finished"]))
              for r in _rows(conn, ROUNDS_SQL, {"cs": cs_id})]
    matches = [Match(stage_of(r["round"]), int(r["home_team_id"]), int(r["away_team_id"]), r["kickoff_at"],
                     bool(r["finished"]))
               for r in _rows(conn, MATCHES_SQL, {"cs": cs_id})]
    return Season(cs_id, stages_from_rounds(rounds), matches)


def tables_of(rows: Sequence[dict[str, Any]]) -> list[TableIn]:
    """Rows of one snapshot as tables, in the order their keys first appear."""
    played: dict[str, dict[int, int | None]] = {}
    for r in rows:
        played.setdefault(str(r["group_key"]), {})[int(r["team_id"])] = (
            None if r.get("played") is None else int(r["played"]))
    return [TableIn(k, v) for k, v in played.items()]


def snapshot_maps(conn: psycopg.Connection[Any], season: Season, times: Sequence[datetime]) -> dict[datetime, list[TableMap]]:
    rows = _rows(conn, PLAYED_SQL, {"cs": season.cs_id, "at": list(times)})
    by_time: dict[datetime, list[dict[str, Any]]] = {}
    for r in rows:
        by_time.setdefault(r["snapshot_at"], []).append(r)
    return {at: map_tables(tables_of(by_time.get(at, [])), season.stages, season.matches, at) for at in times}


@dataclass(frozen=True)
class MatchTables:
    snapshot_at: datetime
    choice: Choice
    maps: dict[str, TableMap]
    """Every table of the chosen snapshot by key."""
    stage: Stage | None
    last_finished_before: datetime | None
    """Kick-off of the chosen stage's last finished match before this one (is the table current?)."""


def _pick(season: Season, times: Sequence[datetime], maps_at: Callable[[datetime], list[TableMap]],
          fixture_round: str | None, kickoff: datetime, home: int, away: int) -> MatchTables | None:
    for at in times:
        maps = maps_at(at)
        choice = choose(fixture_round, kickoff, season.stages, maps, (home, away))
        if choice is None:
            continue
        stage = next((s for s in season.stages if s.name == choice.stage), None)
        last = max((m.kickoff for m in season.matches
                    if m.stage == choice.stage and m.finished and m.kickoff < kickoff), default=None)
        return MatchTables(at, choice, {m.key: m for m in maps}, stage, last)
    return None


def candidate_times(times: Sequence[datetime], kickoff: datetime) -> list[datetime]:
    """The snapshots tried for a match, in order: up to ``BEFORE`` taken before kick-off (newest
    first), then up to ``AFTER`` taken after it (oldest first)."""
    ordered = sorted(times)
    before = [t for t in ordered if t <= kickoff][-BEFORE:][::-1]
    after = [t for t in ordered if t > kickoff][:AFTER]
    return before + after


def match_tables(conn: psycopg.Connection[Any], cs_id: int, fixture_round: str | None, kickoff: datetime,
                 home: int, away: int, *, season: Season | None = None) -> MatchTables | None:
    """The table(s) a match is shown with, from the newest snapshot taken before kick-off that has
    one, else the first taken after it. None when no stored table ranks the match's stage."""
    season = season or load_season(conn, cs_id)
    times = [r["snapshot_at"] for r in _rows(conn, SNAPSHOTS_SQL, {"cs": cs_id, "ko": kickoff, "before": BEFORE,
                                                                  "after": AFTER})]
    if not times:
        return None
    maps = snapshot_maps(conn, season, times)
    return _pick(season, candidate_times(times, kickoff), maps.__getitem__, fixture_round, kickoff, home, away)


class SeasonTables:
    """One season's snapshots for many matches (audits): every snapshot time read once, each
    snapshot mapped once."""

    def __init__(self, conn: psycopg.Connection[Any], season: Season) -> None:
        self.conn = conn
        self.season = season
        self.times = [r["snapshot_at"] for r in _rows(conn, TIMES_SQL, {"cs": season.cs_id})]
        self._maps: dict[datetime, list[TableMap]] = {}

    def maps(self, at: datetime) -> list[TableMap]:
        if at not in self._maps:
            self._maps.update(snapshot_maps(self.conn, self.season, [at]))
        return self._maps[at]

    def for_match(self, fixture_round: str | None, kickoff: datetime, home: int, away: int) -> MatchTables | None:
        return _pick(self.season, candidate_times(self.times, kickoff), self.maps, fixture_round, kickoff, home, away)


def newest_maps(conn: psycopg.Connection[Any], season: Season) -> tuple[datetime, list[TableMap]] | None:
    """The newest snapshot of the season and its tables, mapped."""
    found = _rows(conn, NEWEST_SQL, {"cs": season.cs_id})
    at = found[0]["at"] if found else None
    if at is None:
        return None
    return at, snapshot_maps(conn, season, [at])[at]
