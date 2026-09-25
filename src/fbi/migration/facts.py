"""What the planner reads from the database: stored fixtures and provider coverage."""

from __future__ import annotations

import psycopg
from psycopg.rows import tuple_row

from fbi.providers.api_football.details import COVERAGE_FLAGS


class DatabaseFacts:
    """Loads everything once; the planner asks per (league, season)."""

    def __init__(self, conn: psycopg.Connection) -> None:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT c.provider_league_id, cs.season, count(*) FROM core.fixtures f "
                "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
                "JOIN core.competitions c ON c.id = cs.competition_id "
                "JOIN core.fixture_results r ON r.fixture_id = f.id "
                "WHERE f.status_group = 'finished' GROUP BY 1, 2"
            )
            self._stored = {(int(a), int(b)): int(n) for a, b, n in cur.fetchall()}
            cur.execute(f"SELECT provider_league_id, season, {', '.join(COVERAGE_FLAGS)} FROM raw.league_coverage "
                        "WHERE provider = 'api_football'")
            self._coverage: dict[tuple[int, int], dict[str, bool | None]] = {}
            self._listed: dict[int, set[int]] = {}
            for row in cur.fetchall():
                league, season, *flags = row
                self._coverage[(int(league), int(season))] = dict(zip(COVERAGE_FLAGS, flags, strict=True))
                self._listed.setdefault(int(league), set()).add(int(season))

    def stored_fixtures(self, league_id: int, season: int) -> int:
        return self._stored.get((league_id, season), 0)

    def coverage(self, league_id: int, season: int) -> dict[str, bool | None] | None:
        return self._coverage.get((league_id, season))

    def seasons_listed(self, league_id: int) -> set[int] | None:
        return self._listed.get(league_id)
