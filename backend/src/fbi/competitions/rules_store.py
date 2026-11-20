"""The database side of the competition rules (IA-072, plan piece AD-B01): recording the versions loaded (``core.competition_rules``,
migration 0143, append-only) and reading, read-only, what a reconstruction needs (a season's matches and the provider's latest
tables). The rules themselves are read from the files (``fbi.competitions.rules``); nothing here decides anything.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from fbi.competitions.reconstruction import Match, ProviderRow
from fbi.competitions.rules import SCHEMA, VERSION, RulesFile

TABLE: Final = "core.competition_rules"

INSERT_SQL: Final = """
INSERT INTO core.competition_rules (league_id, rules_version, state, reason, seasons, valid_from, valid_to, schema_version, file_path,
                                    file_sha256, rules, sources, reader_version, loaded_at, loaded_by, code_version)
VALUES (%(league)s, %(version)s, %(state)s, %(reason)s, %(seasons)s, %(valid_from)s, %(valid_to)s, %(schema)s, %(path)s, %(sha)s,
        %(rules)s, %(sources)s, %(reader)s, %(at)s, 'loader', %(code)s)
ON CONFLICT (league_id, rules_version, file_sha256) DO NOTHING
RETURNING id
"""

LOADED_SQL: Final = """
SELECT DISTINCT ON (league_id, rules_version) league_id, rules_version, state, file_sha256, loaded_at
  FROM core.competition_rules ORDER BY league_id, rules_version, id DESC
"""

SEASON_SQL: Final = """
SELECT s.id FROM core.competitions c JOIN core.competition_seasons s ON s.competition_id = c.id
 WHERE c.provider_league_id = %(league)s AND s.season = %(season)s
"""

MATCHES_SQL: Final = """
SELECT f.round, f.status_short, f.home_team_id, f.away_team_id, r.goals_home, r.goals_away, f.kickoff_at
  FROM core.fixtures f LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE f.competition_season_id = %(cs)s ORDER BY f.kickoff_at, f.id
"""

TABLES_SQL: Final = """
WITH last AS (SELECT group_key, max(snapshot_at) AS at FROM core.standings WHERE competition_season_id = %(cs)s GROUP BY 1)
SELECT st.group_key, st.snapshot_at, st.rank, st.team_id, st.points, st.played, st.goals_for, st.goals_against
  FROM core.standings st JOIN last l ON l.group_key = st.group_key AND l.at = st.snapshot_at
 WHERE st.competition_season_id = %(cs)s ORDER BY st.group_key, st.rank
"""

TRACKED_SQL: Final = "SELECT provider_league_id, name, type FROM core.competitions WHERE is_tracked ORDER BY provider_league_id"


@dataclass(frozen=True, slots=True)
class Loaded:
    league_id: int
    version: int
    path: str
    created: bool


def load(conn: psycopg.Connection[Any], files: Iterable[RulesFile], *, at: datetime, code_version: str | None = None
         ) -> list[Loaded]:
    """Record every file's version (idempotent: the same content twice writes nothing). One transaction; the caller commits.
    A version coded in shadow (IA-149) is skipped: it is recorded when the owner's cotejo makes it ``coded``."""
    out: list[Loaded] = []
    with conn.cursor(row_factory=tuple_row) as cur:
        for f in files:
            r = f.rules
            if r.state == "shadow":
                continue
            cur.execute(INSERT_SQL, {
                "league": r.league_id, "version": r.version, "state": r.state, "reason": r.retired_reason,
                "seasons": list(r.seasons), "valid_from": r.valid_from, "valid_to": r.valid_to, "schema": SCHEMA,
                "path": f.path, "sha": f.sha256, "rules": Jsonb(f.as_json()),
                "sources": Jsonb([s.model_dump(mode="json", exclude_none=True) for s in r.sources]), "reader": VERSION,
                "at": at, "code": code_version})
            out.append(Loaded(r.league_id, r.version, f.path, cur.fetchone() is not None))
    return out


def loaded(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    """The newest row of every (league, version) recorded."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(LOADED_SQL)
        return [{"league_id": int(a), "version": int(b), "state": str(c), "sha256": str(d), "loaded_at": e}
                for a, b, c, d, e in cur.fetchall()]


def tracked(conn: psycopg.Connection[Any]) -> dict[int, tuple[str, str]]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(TRACKED_SQL)
        return {int(i): (str(n), str(t)) for i, n, t in cur.fetchall()}


@dataclass(frozen=True, slots=True)
class SeasonData:
    matches: list[Match]
    tables: dict[str, list[ProviderRow]]
    snapshot_at: dict[str, datetime]


def season_data(conn: psycopg.Connection[Any], league_id: int, season: int) -> SeasonData | None:
    """A season's matches (as known when the provider's latest table of each group was taken: later kick-offs count as not
    played) and those tables. None when the season is not in the database."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SEASON_SQL, {"league": league_id, "season": season})
        row = cur.fetchone()
        if row is None:
            return None
        cs = int(row[0])
        cur.execute(TABLES_SQL, {"cs": cs})
        tables: dict[str, list[ProviderRow]] = {}
        snap: dict[str, datetime] = {}
        for g, at, rk, team, pts, pl, gf, ga in cur.fetchall():
            tables.setdefault(str(g), []).append(ProviderRow(int(rk), int(team), int(pts), int(pl), int(gf), int(ga)))
            snap[str(g)] = at
        cur.execute(MATCHES_SQL, {"cs": cs})
        raw = cur.fetchall()
    newest = max(snap.values()) if snap else None
    matches = [Match(None if rd is None else str(rd), str(st) if newest is None or ko < newest else "NS", int(h), int(a),
                     None if gh is None else int(gh), None if ga is None else int(ga))
               for rd, st, h, a, gh, ga, ko in raw]
    return SeasonData(matches=matches, tables=tables, snapshot_at=snap)
