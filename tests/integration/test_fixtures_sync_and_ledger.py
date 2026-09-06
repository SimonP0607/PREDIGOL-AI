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
from fbi.ingestion.fixtures import sync_fixtures
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
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id IN (5001, 5002)")
        cur.execute("DELETE FROM core.teams WHERE provider_team_id IN (901, 902, 903)")
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
    assert "from=2026-09-06" in urls[0] and "to=2026-09-13" in urls[0]
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
