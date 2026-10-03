"""The current season's tables and injury reports are refreshed, request by request, into the ledger."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from fbi.core.errors import ProviderError
from fbi.ingestion.context_refresh import refresh_context
from fbi.providers.api_football.details import StandingRef
from fbi.providers.base import RawResponse
from tests.integration.conftest import Seed


class FakeProvider:
    def __init__(self, league: int, season: int, home_pid: int, away_pid: int) -> None:
        self.league, self.season, self.home, self.away = league, season, home_pid, away_pid
        self.calls: list[str] = []

    def _raw(self, endpoint: str) -> RawResponse:
        at = datetime.now(UTC)
        return RawResponse(endpoint=endpoint, params={}, fetched_at=at, http_status=200, results_count=1,
                           payload_hash=f"ctx-{endpoint.strip('/')}-{at.timestamp()}", file_path="x",
                           bytes_written=1, body={})

    async def fetch_standings(self, *, league_id: int, season: int) -> Any:
        self.calls.append(f"standings {league_id}")
        if league_id != self.league:
            raise ProviderError("not this one")
        refs = [StandingRef(self.league, self.season, self.home, 1, 9, 3, 3, 0, 0, 7, 1, "WWW", None),
                StandingRef(self.league, self.season, self.away, 2, 6, 3, 2, 0, 1, 4, 3, "WLW", None)]
        return refs, self._raw("/standings")

    async def fetch_injuries(self, *, league_id: int, season: int) -> Any:
        self.calls.append(f"injuries {league_id}")
        return [], self._raw("/injuries")


@pytest.fixture
def current_league(migrated_database: str, seed: Seed) -> Iterator[dict[str, int]]:
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT is_tracked, type FROM core.competitions WHERE id = %s", (seed.competition_id,))
        tracked, kind = cur.fetchone()  # type: ignore[misc]
        cur.execute("SELECT is_current FROM core.competition_seasons WHERE id = %s", (seed.season_id,))
        current = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("UPDATE core.competitions SET is_tracked = true, type = 'league' WHERE id = %s",
                    (seed.competition_id,))
        cur.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
        cur.execute("SELECT c.provider_league_id, cs.season FROM core.competition_seasons cs JOIN core.competitions c "
                    "ON c.id = cs.competition_id WHERE cs.id = %s", (seed.season_id,))
        league, season = cur.fetchone()  # type: ignore[misc]
        cur.execute("SELECT provider_team_id FROM core.teams WHERE id IN (%s, %s) ORDER BY id = %s DESC",
                    (seed.home_team_id, seed.away_team_id, seed.home_team_id))
        home, away = (r[0] for r in cur.fetchall())
    yield {"league": int(league), "season": int(season), "home": int(home), "away": int(away)}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM core.standings WHERE competition_season_id = %s", (seed.season_id,))
        cur.execute("SELECT id FROM raw.ingestion_runs WHERE job_type = 'context_refresh'")
        runs = [r[0] for r in cur.fetchall()]
        if runs:
            cur.execute("DELETE FROM raw.ingestion_payloads WHERE run_id = ANY(%s)", (runs,))
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = ANY(%s)", (runs,))
        cur.execute("UPDATE core.competitions SET is_tracked = %s, type = %s WHERE id = %s",
                    (tracked, kind, seed.competition_id))
        cur.execute("UPDATE core.competition_seasons SET is_current = %s WHERE id = %s", (current, seed.season_id))


async def test_tables_and_injuries_are_refreshed_and_counted(migrated_database: str, seed: Seed,
                                                              current_league: dict[str, int]) -> None:
    provider = FakeProvider(current_league["league"], current_league["season"], current_league["home"],
                            current_league["away"])
    with psycopg.connect(migrated_database) as conn:
        counters = await refresh_context(conn, provider)
        assert f"standings {current_league['league']}" in provider.calls
        assert f"injuries {current_league['league']}" in provider.calls
        assert counters.api_calls == len(provider.calls)
        with conn.cursor() as cur:
            cur.execute("SELECT rank, points FROM core.standings WHERE competition_season_id = %s ORDER BY rank",
                        (seed.season_id,))
            assert cur.fetchall() == [(1, 9), (2, 6)]
            cur.execute("SELECT status, api_calls FROM raw.ingestion_runs WHERE job_type = 'context_refresh' "
                        "ORDER BY id DESC LIMIT 1")
            status, calls = cur.fetchone()  # type: ignore[misc]
            assert calls == counters.api_calls and status in ("completed", "partial")
