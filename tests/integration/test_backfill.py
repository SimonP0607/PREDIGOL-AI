"""History is backfilled one season per request - and never at live capture's expense.

The free plan was measured to serve 2022-2024 through /fixtures?league=&season=
in full, one request per season, scores included. The backfill takes those
units in priority order, stops when its allowance is spent, and resumes on the
next run. Before spending anything it reserves what live odds capture may need
in the next 24 hours, because a missed odds window is unrecoverable and a
season of history is not.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion.backfill import BackfillUnit, live_reserve, progress, run_backfill, seed_tasks
from fbi.ingestion.payload_store import PayloadStore
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from tests.integration.conftest import Seed
from tests.integration.helpers import row, scalar

SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
NOW = datetime(2026, 9, 24, 20, 0, tzinfo=UTC)
REFUSAL = {"response": [], "errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."}}


def season_payload(season: int, n: int = 3, base_id: int = 66_000) -> dict:
    out = []
    for i in range(n):
        ko = datetime(season, 9, 1 + i, 14, 0, tzinfo=UTC)
        out.append({
            "fixture": {"id": base_id + season * 10 + i, "date": ko.isoformat(), "status": {"short": "FT"},
                        "venue": {"id": None, "name": None, "city": None}},
            "league": {"id": 39, "season": season, "round": f"Regular Season - {i + 1}"},
            "teams": {"home": {"id": 33, "name": "Manchester United"}, "away": {"id": 40, "name": "Liverpool"}},
            "goals": {"home": i, "away": 1},
            "score": {"halftime": {"home": 0, "away": 0}, "fulltime": {"home": i, "away": 1},
                      "extratime": {"home": None, "away": None}, "penalty": {"home": None, "away": None}},
        })
    return {"response": out, "errors": [], "paging": {"current": 1, "total": 1}}


def provider(tmp_path: Path, answers: dict[tuple[str, str], dict] | None, calls: list[str]) -> ApiFootballProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.url.params.get("league", ""), request.url.params.get("season", ""))
        calls.append(f"{key[0]}/{key[1]}")
        if answers is None:
            raise AssertionError("no request may be made in this test")
        return httpx.Response(200, json=answers.get(key, REFUSAL))

    async def _no_sleep(_s: float) -> None:
        return None

    return ApiFootballProvider(ApiFootballClient(
        ApiFootballSettings(key=SECRET, plan="free", daily_budget=60, max_retries=0),
        PayloadStore(tmp_path), transport=httpx.MockTransport(handler),
        rate_limiter=TokenBucket(300, sleep=_no_sleep), quota=DailyQuota(budget=60),
    ))


@pytest.fixture()
def world(db: psycopg.Connection, seed: Seed) -> Iterator[psycopg.Connection]:
    set_clock(FrozenClock(NOW))
    yield db
    set_clock(SystemClock())
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM raw.backfill_tasks")
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 66000 AND 99999 "
                    "AND provider_fixture_id <> 1001")
        cur.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s AND season <> 2025",
                    (seed.competition_id,))
        cur.execute("DELETE FROM raw.provider_quota")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE run_id IN "
                    "(SELECT id FROM raw.ingestion_runs WHERE job_type = 'historical_backfill')")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'historical_backfill'")
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 77000 AND 77999")
        cur.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))
    db.commit()


PL = [BackfillUnit(39, s, 10) for s in (2024, 2023, 2022)]


def test_seeding_is_idempotent(world: psycopg.Connection) -> None:
    assert seed_tasks(world, PL) == 3
    assert seed_tasks(world, PL) == 0, "existing tasks keep their state"
    assert progress(world) == {"pending": 3}


async def test_a_run_writes_whole_seasons_with_scores_and_records_its_work(
    world: psycopg.Connection, seed: Seed, tmp_path: Path
) -> None:
    seed_tasks(world, PL)
    calls: list[str] = []
    answers = {("39", str(s)): season_payload(s) for s in (2024, 2023, 2022)}
    report = await run_backfill(world, provider(tmp_path, answers, calls), max_requests=10, daily_budget=60)
    assert report.done == 3 and report.attempted == 3
    assert calls == ["39/2024", "39/2023", "39/2022"], "priority order, newest season first"
    assert report.results_written == 9
    with world.cursor() as cur:
        cur.execute("SELECT season, is_current FROM core.competition_seasons WHERE competition_id = %s "
                    "AND season IN (2022,2023,2024) ORDER BY season", (seed.competition_id,))
        assert cur.fetchall() == [(2022, False), (2023, False), (2024, False)], (
            "a backfilled season is history, never 'current'")
        cur.execute("SELECT count(*) FROM core.fixture_results r JOIN core.fixtures f ON f.id = r.fixture_id "
                    "WHERE f.provider_fixture_id BETWEEN 66000 AND 99999 AND f.provider_fixture_id <> 1001")
        assert scalar(cur) == 9
        cur.execute("SELECT status, last_payload_hash IS NOT NULL FROM raw.backfill_tasks")
        assert set(cur.fetchall()) == {("done", True)}
        cur.execute("SELECT status, api_calls FROM raw.ingestion_runs WHERE id = %s", (report.run_id,))
        assert row(cur) == ("completed", 3)


async def test_the_run_stops_at_its_allowance_and_the_next_one_resumes(
    world: psycopg.Connection, tmp_path: Path
) -> None:
    seed_tasks(world, PL)
    answers = {("39", str(s)): season_payload(s) for s in (2024, 2023, 2022)}
    calls: list[str] = []
    first = await run_backfill(world, provider(tmp_path, answers, calls), max_requests=2, daily_budget=60)
    assert first.attempted == 2 and progress(world) == {"done": 2, "pending": 1}
    second = await run_backfill(world, provider(tmp_path, answers, calls), max_requests=2, daily_budget=60)
    assert second.attempted == 1 and progress(world) == {"done": 3}
    assert calls == ["39/2024", "39/2023", "39/2022"], "nothing was fetched twice"


async def test_a_season_the_plan_refuses_is_recorded_with_its_reason_and_not_retried(
    world: psycopg.Connection, tmp_path: Path
) -> None:
    seed_tasks(world, [BackfillUnit(39, 2025, 10)])
    calls: list[str] = []
    report = await run_backfill(world, provider(tmp_path, {}, calls), max_requests=5, daily_budget=60)
    assert report.refused == 1
    with world.cursor() as cur:
        cur.execute("SELECT status, attempts, last_error FROM raw.backfill_tasks")
        status, attempts, error = row(cur)
    assert (status, attempts) == ("refused", 1) and "2022 to 2024" in error
    again = await run_backfill(world, provider(tmp_path, {}, calls), max_requests=5, daily_budget=60)
    assert again.attempted == 0 and calls == ["39/2025"], "a refusal is an answer: it is not asked again"


async def test_nothing_is_spent_when_the_live_reserve_would_be_touched(
    world: psycopg.Connection, seed: Seed, tmp_path: Path
) -> None:
    """45 of 60 already spent; the reserve (standing syncs + margin) exceeds
    what is left, so the backfill defers - and the transport would raise if
    it were touched."""
    seed_tasks(world, PL)
    with world.cursor() as cur:
        cur.execute("INSERT INTO raw.provider_quota (provider, quota_date, spent, budget) "
                    "VALUES ('api_football', %s, 45, 60)", (NOW.date(),))
    world.commit()
    report = await run_backfill(world, provider(tmp_path, None, []), max_requests=10, daily_budget=60)
    assert report.attempted == 0 and report.allowance == 0
    assert report.deferred_reason and "reserve" in report.deferred_reason


def test_the_reserve_grows_with_fixtures_inside_capture_windows(world: psycopg.Connection, seed: Seed) -> None:
    base = live_reserve(world, at=NOW)
    with world.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
        cur.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
            "kickoff_at) VALUES (77001, %s, %s, %s, %s)",
            (seed.season_id, seed.home_team_id, seed.away_team_id, NOW + timedelta(hours=20)),
        )
    # kick-off in 20 h: windows at T-12h, T-6h, T-3h fall inside the next 24 h, plus near-close
    assert live_reserve(world, at=NOW) == base + 4


async def test_a_competition_missing_from_the_catalogue_is_not_invented(
    world: psycopg.Connection, tmp_path: Path
) -> None:
    seed_tasks(world, [BackfillUnit(999_999, 2023, 1)])
    report = await run_backfill(world, provider(tmp_path, None, []), max_requests=5, daily_budget=60)
    assert report.refused == 1
    with world.cursor() as cur:
        cur.execute("SELECT last_error FROM raw.backfill_tasks")
        assert "not in the catalogue" in scalar(cur)


def test_a_current_seasons_played_match_never_fetched_gets_a_detail_unit(world: psycopg.Connection,
                                                                         seed: Seed) -> None:
    """Data truth audit V2: 8,113 played fixtures of current seasons had no detail at all."""
    from fbi.ingestion.backfill import CURRENT_DETAIL_PRIORITY, seed_current_details

    with world.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
        cur.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
        cur.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
                    (seed.fixture_id,))
    assert seed_current_details(world) == 1
    with world.cursor() as cur:
        cur.execute("SELECT kind, priority, batch_key FROM raw.backfill_tasks WHERE kind = 'fixture_details'")
        assert row(cur) == ("fixture_details", CURRENT_DETAIL_PRIORITY, "1001")
    assert seed_current_details(world) == 0  # the same gap is queued once
