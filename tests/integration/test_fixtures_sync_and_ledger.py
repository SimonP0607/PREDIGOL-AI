"""Fixtures sync writes fixtures, teams, payloads and a ledger row - and is idempotent."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion.fixtures import SyncStrategy, sync_fixtures, tracked_season_ids
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.ingestion.payload_store import PayloadStore
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.api_football.status import fetch_status
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from tests.integration.conftest import Seed
from tests.integration.helpers import row, scalar

SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
NOW = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)


def fixtures_body(*fixtures: tuple[int, str, int, str, int, str]) -> dict:
    return {
        "response": [
            {
                "fixture": {"id": fid, "date": date, "status": {"short": "NS"}},
                "league": {"id": 39, "season": 2025},
                "teams": {"home": {"id": hid, "name": hname}, "away": {"id": aid, "name": aname}},
            }
            for fid, date, hid, hname, aid, aname in fixtures
        ],
        "errors": [],
        "paging": {"current": 1, "total": 1},
    }


STATUS_BODY = {
    "response": {
        "account": {"firstname": "Simon", "lastname": "X", "email": "hidden@example.com"},
        "subscription": {"plan": "Pro", "end": "2027-01-01T00:00:00+00:00", "active": True},
        "requests": {"current": 214, "limit_day": 7500},
    },
    "errors": [],
}


@pytest.fixture()
def clock() -> Iterator[FrozenClock]:
    c = FrozenClock(NOW)
    set_clock(c)
    yield c
    set_clock(SystemClock())


def provider_with(tmp_path: Path, body_for: object) -> tuple[ApiFootballProvider, ApiFootballClient, list[str]]:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=body_for(request))  # type: ignore[operator]

    async def _no_sleep(_s: float) -> None:
        return None

    settings = ApiFootballSettings(key=SECRET, plan="pro", daily_budget=50, max_retries=0)
    client = ApiFootballClient(
        settings, PayloadStore(tmp_path), transport=httpx.MockTransport(handler),
        rate_limiter=TokenBucket(300, sleep=_no_sleep), quota=DailyQuota(budget=50),
    )
    return ApiFootballProvider(client), client, urls


@pytest.fixture()
def active(db: psycopg.Connection, seed: Seed) -> Iterator[psycopg.Connection]:
    with db.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
        cur.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
    db.commit()
    yield db
    with db.cursor() as cur:
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 5000 AND 5099")
        cur.execute("DELETE FROM core.teams WHERE provider_team_id BETWEEN 900 AND 999")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE run_id IN (SELECT id FROM raw.ingestion_runs WHERE job_type = 'fixtures_sync')")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'fixtures_sync'")
        cur.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))
    db.commit()


async def test_sync_writes_fixtures_teams_payload_and_a_ledger_row(active: psycopg.Connection, tmp_path: Path, clock: FrozenClock) -> None:
    body = fixtures_body(
        (5001, "2026-09-08T19:00:00+00:00", 901, "Alpha FC", 902, "Beta FC"),
        (5002, "2026-09-09T19:00:00+00:00", 902, "Beta FC", 903, "Gamma FC"),
    )
    provider, _, urls = provider_with(tmp_path, lambda _r: body)
    counters = await sync_fixtures(active, provider, horizon_days=7)

    assert counters.api_calls == 1 and counters.rows_inserted == 2 and counters.rows_updated == 0
    assert counters.status == "completed"
    # the whole season in one request: no date window that leaves earlier matches unknown
    assert "league=39" in urls[0] and "season=2025" in urls[0]
    assert "from=" not in urls[0] and "to=" not in urls[0]
    assert SECRET not in urls[0]

    with active.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixtures WHERE provider_fixture_id IN (5001, 5002)")
        assert scalar(cur) == 2
        cur.execute("SELECT name FROM core.teams WHERE provider_team_id = 903")
        assert scalar(cur) == "Gamma FC"
        cur.execute(
            "SELECT job_type, status, api_calls, payloads_stored, rows_normalized, rows_written, rows_updated, attempt, duration_ms "
            "FROM raw.ingestion_runs WHERE job_type = 'fixtures_sync' ORDER BY id DESC LIMIT 1"
        )
        ledger_row = row(cur)
        assert ledger_row[:8] == ("fixtures_sync", "completed", 1, 1, 2, 2, 0, 1)
        assert ledger_row[8] is not None, "duration is derived, not typed in"


async def test_syncing_twice_updates_instead_of_duplicating(active: psycopg.Connection, tmp_path: Path, clock: FrozenClock) -> None:
    body = fixtures_body((5001, "2026-09-08T19:00:00+00:00", 901, "Alpha FC", 902, "Beta FC"))
    provider, _, _ = provider_with(tmp_path, lambda _r: body)
    first = await sync_fixtures(active, provider, horizon_days=7)
    moved = fixtures_body((5001, "2026-09-08T20:00:00+00:00", 901, "Alpha FC", 902, "Beta FC"))
    provider2, _, _ = provider_with(tmp_path, lambda _r: moved)
    second = await sync_fixtures(active, provider2, horizon_days=7)

    assert (first.rows_inserted, first.rows_updated) == (1, 0)
    assert (second.rows_inserted, second.rows_updated) == (0, 1)
    with active.cursor() as cur:
        cur.execute("SELECT count(*), max(kickoff_at) FROM core.fixtures WHERE provider_fixture_id = 5001")
        n, ko = row(cur)
        assert n == 1 and ko == datetime(2026, 9, 8, 20, 0, tzinfo=UTC)


async def test_status_is_parsed_and_the_email_never_leaves_the_provider_module(tmp_path: Path) -> None:
    _, client, _ = provider_with(tmp_path, lambda _r: STATUS_BODY)
    st = await fetch_status(client)
    assert st.plan == "pro" and st.requests_today == 214 and st.remaining_today == 7286
    assert "email" not in st.as_metadata()
    assert st.account_label == "Simon"


def test_the_ledger_records_the_last_error_and_the_attempt(db: psycopg.Connection) -> None:
    ledger = RunLedger(db)
    run_id = ledger.open("odds_capture", scheduled_for=NOW, attempt=2)
    ledger.close(run_id, RunCounters(api_calls=3, errors=["boom", "later boom"]))
    with db.cursor() as cur:
        cur.execute("SELECT status, attempt, errors, last_error, scheduled_for FROM raw.ingestion_runs WHERE id = %s", (run_id,))
        assert cur.fetchone() == ("failed", 2, 2, "later boom", NOW)
        cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (run_id,))
    db.commit()


# --------------------------------------------------------------------------
# The date strategy: the only fixtures query a restricted plan serves.
# --------------------------------------------------------------------------

UNTRACKED_LEAGUE = 140  # La Liga: known to the provider, not tracked by us
PLAN_REFUSAL_BODY = {
    "response": [],
    "errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."},
}
QUOTA_ERROR_BODY = {
    "response": [],
    "errors": {"requests": "You have reached the request limit for the day."},
}


def day_body(*fixtures: tuple[int, int, int, str, int, int, str]) -> dict:
    """A /fixtures?date= payload: every league at once.

    Each tuple is (fixture_id, league_id, season, kickoff, home_id, away_id, home_name).
    """
    return {
        "response": [
            {
                "fixture": {"id": fid, "date": kickoff, "status": {"short": "NS"}},
                "league": {"id": league, "season": season},
                "teams": {
                    "home": {"id": hid, "name": hname},
                    "away": {"id": aid, "name": f"team {aid}"},
                },
            }
            for fid, league, season, kickoff, hid, aid, hname in fixtures
        ],
        "errors": [],
        "paging": {"current": 1, "total": 1},
    }


def by_date(bodies: dict[str, dict]) -> object:
    """Dispatch the mock transport on the ?date= parameter."""

    def body_for(request: httpx.Request) -> dict:
        on = request.url.params.get("date", "")
        return bodies.get(on, day_body())

    return body_for


async def test_the_date_strategy_spends_one_request_per_day_and_keeps_only_our_leagues(
    active: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    """One call per calendar day, every league in the answer, ours filtered out
    locally. The untracked league is dropped rather than given a season row."""
    bodies = {
        "2026-09-06": day_body(
            (5010, 39, 2025, "2026-09-06T14:00:00+00:00", 911, 912, "Alpha FC"),
            (5011, UNTRACKED_LEAGUE, 2026, "2026-09-06T20:00:00+00:00", 921, 922, "Madrid FC"),
        ),
        "2026-09-07": day_body(
            (5012, 39, 2025, "2026-09-07T19:00:00+00:00", 912, 913, "Beta FC"),
        ),
    }
    provider, _, urls = provider_with(tmp_path, by_date(bodies))
    counters = await sync_fixtures(active, provider, horizon_days=1, strategy=SyncStrategy.DATE)

    assert counters.api_calls == 2, "one request per calendar day, horizon included"
    assert len(urls) == 2
    assert "date=2026-09-06" in urls[0] and "date=2026-09-07" in urls[1]
    assert "league=" not in urls[0] and "season=" not in urls[0], (
        "league+season is what the restricted plan refuses"
    )
    assert counters.rows_normalized == 2, "only the two Premier League fixtures are ours"
    assert counters.rows_inserted == 2 and counters.rows_updated == 0
    assert counters.status == "completed"

    with active.cursor() as cur:
        cur.execute("SELECT provider_fixture_id FROM core.fixtures WHERE provider_fixture_id BETWEEN 5010 AND 5012 ORDER BY 1")
        assert [r[0] for r in cur.fetchall()] == [5010, 5012]
        cur.execute("SELECT count(*) FROM core.teams WHERE provider_team_id IN (921, 922)")
        assert scalar(cur) == 0, "an untracked league's teams are not imported either"
        cur.execute("SELECT notes, payloads_stored FROM raw.ingestion_runs WHERE job_type = 'fixtures_sync' ORDER BY id DESC LIMIT 1")
        notes, payloads = row(cur)
        assert notes == "date" and payloads == 2, "every day's payload is kept, empty or not"


async def test_auto_falls_back_to_dates_when_the_plan_refuses_the_season(
    active: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    """The real Free-plan behaviour: league+season is refused, date alone works.

    The refused request is still counted - it was issued - but it is no longer
    an error, because the fallback handled it and the run did its job.
    """
    def body_for(request: httpx.Request) -> dict:
        if request.url.params.get("league"):
            return PLAN_REFUSAL_BODY
        return day_body((5020, 39, 2025, "2026-09-06T14:00:00+00:00", 931, 932, "Alpha FC"))

    provider, _, urls = provider_with(tmp_path, body_for)
    counters = await sync_fixtures(active, provider, horizon_days=1, strategy=SyncStrategy.AUTO)

    assert "league=39" in urls[0], "auto tries the cheap strategy first"
    assert len(urls) == 3, "one refused league call, then one call per day"
    assert counters.api_calls == 3, "the refused request was issued, so it is counted"
    assert counters.errors == [], "a handled plan refusal is not a failure"
    assert counters.status == "completed"
    assert counters.rows_inserted == 1

    with active.cursor() as cur:
        cur.execute("SELECT status, notes, errors FROM raw.ingestion_runs WHERE job_type = 'fixtures_sync' ORDER BY id DESC LIMIT 1")
        assert row(cur) == ("completed", "auto", 0)


async def test_an_error_that_is_not_a_plan_refusal_stays_a_failure(
    active: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    """Quota exhaustion must not be silently retried as a date sweep - that
    would spend the rest of the budget on a provider that already said no."""
    provider, _, urls = provider_with(tmp_path, lambda _r: QUOTA_ERROR_BODY)
    counters = await sync_fixtures(active, provider, horizon_days=1, strategy=SyncStrategy.AUTO)

    assert len(urls) == 1, "no fallback for an error the fallback cannot fix"
    assert counters.api_calls == 1
    assert counters.status == "failed"
    assert counters.errors and "request limit" in counters.errors[0]


async def test_a_day_with_no_fixtures_of_ours_is_recorded_without_writing_anything(
    active: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    provider, _, _ = provider_with(
        tmp_path,
        lambda _r: day_body((5030, UNTRACKED_LEAGUE, 2026, "2026-09-06T20:00:00+00:00", 941, 942, "Madrid FC")),
    )
    counters = await sync_fixtures(active, provider, horizon_days=0, strategy=SyncStrategy.DATE)

    assert counters.api_calls == 1 and counters.payloads_stored == 1
    assert counters.rows_normalized == 0 and counters.rows_inserted == 0
    assert counters.status == "completed"
    with active.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixtures WHERE provider_fixture_id = 5030")
        assert scalar(cur) == 0


def test_tracked_season_ids_maps_only_the_competitions_we_follow(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The filter the date strategy depends on. Untracked means absent, so a
    fixture from that competition has nowhere to go and is dropped."""
    assert tracked_season_ids(db) == {}, "nothing is tracked by default"
    with db.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    assert tracked_season_ids(db) == {(39, 2025): seed.season_id}
    assert (UNTRACKED_LEAGUE, 2026) not in tracked_season_ids(db)
