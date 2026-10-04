"""The fixes the first truth audit called for: corrected sides, the season list, post-match
detail, and an Elo history that keeps up with the results."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.features.elo_refresh import JOB, refresh_elo
from fbi.ingestion.catalogue_refresh import refresh_catalogue
from fbi.ingestion.fixtures import FixtureRepository, PayloadLineage
from fbi.ingestion.live_match import post_match_to_refresh
from fbi.providers.api_football.details import iter_coverage
from fbi.providers.base import FixtureRef, RawResponse
from tests.integration.conftest import Seed

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def conn(migrated_database: str, seed: Seed) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database) as c:
        yield c
        c.rollback()


def test_a_fixture_whose_sides_the_provider_corrects_follows_it_and_says_so(conn: psycopg.Connection,
                                                                           seed: Seed) -> None:
    repo = FixtureRepository(conn)
    teams = repo.ensure_teams([FixtureRef(1001, 39, 2025, datetime(2026, 9, 15, 19, 0, tzinfo=UTC), 33, 77,
                                          "NS")], {33: "Manchester United", 77: "Corrected FC"})
    ref = FixtureRef(1001, 39, 2025, datetime(2026, 9, 15, 19, 0, tzinfo=UTC), 33, 77, "NS")
    inserted, updated = repo.upsert_fixtures([ref], {(39, 2025): seed.season_id}, teams,
                                             lineage=PayloadLineage(seed.payload_hash, NOW))
    assert (inserted, updated) == (0, 1)
    away = conn.execute("SELECT away_team_id FROM core.fixtures WHERE id = %s", (seed.fixture_id,)).fetchone()
    assert away is not None and away[0] == teams[77]
    repair = conn.execute("SELECT rule, before_value, after_value FROM audit.data_repairs "
                          "WHERE entity_id = %s ORDER BY id DESC LIMIT 1", (seed.fixture_id,)).fetchone()
    assert repair is not None and repair[0] == "fixture_sides" and repair[1] != repair[2]


class CatalogueProvider:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body

    async def fetch_coverage(self, *, league_id: int | None = None) -> Any:
        raw = RawResponse(endpoint="/leagues", params={}, fetched_at=NOW, http_status=200, results_count=1,
                          payload_hash="h1", file_path="x", bytes_written=1, body=self.body)
        return list(iter_coverage(self.body)), raw


async def test_the_daily_catalogue_refresh_learns_a_new_current_season(conn: psycopg.Connection,
                                                                       seed: Seed) -> None:
    body = {"response": [{
        "league": {"id": 39, "name": "Premier League", "type": "League"}, "country": {"name": "England"},
        "seasons": [
            {"year": 2025, "current": False, "start": "2025-08-15", "end": "2026-05-24",
             "coverage": {"fixtures": {"events": True}, "standings": True, "odds": True}},
            {"year": 2026, "current": True, "start": "2026-08-14", "end": "2027-05-23",
             "coverage": {"fixtures": {"events": True}, "standings": True, "odds": True}},
        ]}]}
    before = conn.execute("SELECT season, is_current, start_date, end_date, has_odds, has_fixtures, listed_at "
                          "FROM core.competition_seasons WHERE competition_id = %s", (seed.competition_id,)).fetchall()
    conn.commit()
    try:
        counters = await refresh_catalogue(conn, CatalogueProvider(body), at=NOW)
        assert counters.api_calls == 1 and not counters.errors
        rows = conn.execute("SELECT season, is_current FROM core.competition_seasons WHERE competition_id = %s "
                            "ORDER BY season", (seed.competition_id,)).fetchall()
        assert (2026, True) in rows and (2025, False) in rows
        flags = conn.execute("SELECT standings, odds FROM raw.league_coverage WHERE provider_league_id = 39 "
                             "AND season = 2026").fetchone()
        assert flags == (True, True)
    finally:
        # refresh_catalogue commits: put the shared seed back exactly as it was.
        conn.rollback()
        conn.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s AND season <> ALL(%s)",
                     (seed.competition_id, [r[0] for r in before]))
        for season, current, start, end, odds, has_fixtures, listed in before:
            conn.execute("UPDATE core.competition_seasons SET is_current = %s, start_date = %s, end_date = %s, "
                         "has_odds = %s, has_fixtures = %s, listed_at = %s WHERE competition_id = %s AND season = %s",
                         (current, start, end, odds, has_fixtures, listed, seed.competition_id, season))
        conn.execute("DELETE FROM raw.league_coverage WHERE provider_league_id = 39 AND payload_hash = 'h1'")
        conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'catalogue_refresh'")
        conn.commit()


def test_a_finished_match_read_only_at_the_whistle_is_read_again(conn: psycopg.Connection, seed: Seed) -> None:
    kickoff = NOW - timedelta(hours=5)
    conn.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    conn.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished', kickoff_at = %s "
                 "WHERE id = %s", (kickoff, seed.fixture_id))
    conn.execute("INSERT INTO core.fixture_detail_coverage (fixture_id, source, dataset, block_present, "
                 "rows_written, payload_hash, fetched_at) VALUES (%s, 'api-football', 'team_statistics', true, 2, "
                 "%s, %s)", (seed.fixture_id, seed.payload_hash, kickoff + timedelta(minutes=112)))
    assert (seed.fixture_id, 1001) in post_match_to_refresh(conn, at=NOW)
    conn.execute("UPDATE core.fixture_detail_coverage SET fetched_at = %s WHERE fixture_id = %s",
                 (kickoff + timedelta(hours=3), seed.fixture_id))
    assert (seed.fixture_id, 1001) not in post_match_to_refresh(conn, at=NOW), "read after it settled"


def test_the_elo_history_is_recomputed_and_older_refreshes_pruned(conn: psycopg.Connection, seed: Seed) -> None:
    conn.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
                 (seed.fixture_id,))
    conn.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ft_goals_home, ft_goals_away) "
                 "VALUES (%s, 2, 0, 2, 0) ON CONFLICT (fixture_id) DO NOTHING", (seed.fixture_id,))
    conn.commit()
    try:
        first = refresh_elo(conn)
        second = refresh_elo(conn)
        third = refresh_elo(conn, keep=1)
        assert first.matches >= 1 and first.rows == 2 * first.matches
        runs = {r[0] for r in conn.execute("SELECT DISTINCT run_id FROM features.elo_ratings").fetchall()}
        assert third.run_id in runs and first.run_id not in runs and second.run_id not in runs
        home = conn.execute("SELECT rating_after FROM features.elo_ratings WHERE run_id = %s AND team_id = %s",
                            (third.run_id, seed.home_team_id)).fetchone()
        assert home is not None and home[0] > 1500, "the 2-0 winner gains"
    finally:
        conn.execute("DELETE FROM features.elo_ratings")
        conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = %s", (JOB,))
        conn.execute("DELETE FROM core.fixture_results WHERE fixture_id = %s", (seed.fixture_id,))
        conn.execute("UPDATE core.fixtures SET status_short = 'NS', status_group = 'scheduled' WHERE id = %s",
                     (seed.fixture_id,))
        conn.commit()
