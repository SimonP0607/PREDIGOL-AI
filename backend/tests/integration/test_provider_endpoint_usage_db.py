"""Requests by endpoint and lane, the daily summary of the per-minute peaks and the size of the database (plan PM, PM-01-02), on the real
schema. The decisive test: many requests at once, from several jobs and two counters (as two processes would), with retries - and the
day's sum by endpoint is EXACTLY what the daily budget (``raw.provider_quota``) counted.

Each test writes under a provider name of its own and removes its rows afterwards: the shared test database is walked down by other
files, and the downgrade of 0168 refuses while a measure exists."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers import quota as q
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.ratelimit import TokenBucket
from fbi.storage.payload_store import PayloadStore

pytestmark = pytest.mark.integration
PROVIDER = "pm0102_test"
SIZE_SQL = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "db" / "db_size_history.sql"
OK_BODY = {"response": [], "errors": [], "results": 0, "paging": {"current": 1, "total": 1}}


def _clear(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        for table in ("raw.provider_endpoint_usage", "raw.provider_minute_daily", "raw.provider_minute_usage", "raw.provider_quota"):
            conn.execute(f"DELETE FROM {table} WHERE provider = %s", (PROVIDER,))
        conn.execute("DELETE FROM audit.db_size_history WHERE source = 'pm0102_test'")


@pytest.fixture()
def dsn(migrated_database: str) -> Iterator[str]:
    _clear(migrated_database)
    q.bind_usage_job(None)
    q.bind_usage_lane(None)
    yield migrated_database
    _clear(migrated_database)
    set_clock(SystemClock())
    q.bind_usage_job(None)


def connector(dsn: str) -> Any:
    return lambda: psycopg.connect(dsn, autocommit=True)


def usage_rows(dsn: str) -> dict[tuple[str, str, str], int]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT endpoint, lane, job, requests FROM raw.provider_endpoint_usage WHERE provider = %s",
                            (PROVIDER,)).fetchall()
    return {(e, lane, j): int(n) for e, lane, j, n in rows}


def test_a_flush_adds_to_the_days_row_and_two_counters_flushing_at_once_lose_nothing(dsn: str) -> None:
    counters = [q.EndpointUsageCounter(connect=connector(dsn), provider=PROVIDER, flush_every=0.0) for _ in range(2)]
    jobs = ("odds_capture", "reference_refresh", "live_match_capture")

    def work(c: q.EndpointUsageCounter, job: str) -> None:
        q.bind_usage_job(job)
        for i in range(150):  # flush_every=0: nearly every record is a statement, the worst case for the row locks
            c.record(("/odds", "/fixtures", "/players")[i % 3])

    threads = [threading.Thread(target=work, args=(c, job)) for c in counters for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for c in counters:
        c.flush()
        assert c.pending_requests == 0
    rows = usage_rows(dsn)
    assert sum(rows.values()) == 2 * 3 * 150
    assert rows[("/odds", "cuotas", "odds_capture")] == 2 * 50
    assert rows[("/players", "referencia", "reference_refresh")] == 2 * 50
    assert rows[("/fixtures", "directo", "live_match_capture")] == 2 * 50
    assert len(rows) == 9, "one row per endpoint, lane and job of the day - not one per request"


async def test_the_days_sum_by_endpoint_is_exactly_what_the_daily_budget_counted(dsn: str, tmp_path: Path) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:  # the day's budget row of this provider, from zero
        conn.execute("INSERT INTO raw.provider_quota (provider, quota_date, spent, budget) VALUES (%s, current_date, 0, 100000)",
                     (PROVIDER,))
    settings = ApiFootballSettings(key="k" * 32, plan="ultra", daily_budget=100_000, max_retries=2, timeout_seconds=2.0)

    async def no_sleep(_s: float) -> None:
        return None

    calls = {"n": 0}

    def answer(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] % 7 == 0 else httpx.Response(200, json=OK_BODY)  # some retries

    def make_client() -> ApiFootballClient:
        return ApiFootballClient(
            settings, PayloadStore(tmp_path), transport=httpx.MockTransport(answer),
            rate_limiter=TokenBucket(10_000, sleep=no_sleep), sleep=no_sleep,
            quota=q.PersistentDailyQuota(budget=100_000, connect=connector(dsn), provider=PROVIDER),
            usage=q.EndpointUsageCounter(connect=connector(dsn), provider=PROVIDER, flush_every=0.05))

    clients = [make_client(), make_client()]  # two processes' worth of counters

    async def job(client: ApiFootballClient, name: str, endpoints: tuple[str, ...], n: int) -> None:
        q.bind_usage_job(name)
        for i in range(n):
            await client.get(endpoints[i % len(endpoints)], {"i": i})

    await asyncio.gather(
        job(clients[0], "live_odds_capture", ("/odds/live",), 60),
        job(clients[0], "reference_refresh", ("/players", "/transfers", "/trophies"), 45),
        job(clients[1], "fixtures_sync", ("/fixtures",), 30),
        job(clients[1], "context_due", ("/teams/statistics", "/injuries"), 25),
    )
    for c in clients:
        await c.aclose()
    with psycopg.connect(dsn) as conn:
        spent = conn.execute("SELECT spent FROM raw.provider_quota WHERE provider = %s AND quota_date = current_date",
                             (PROVIDER,)).fetchone()
    rows = usage_rows(dsn)
    assert spent is not None and int(spent[0]) == calls["n"] > 160, "retries included: every request that left the building"
    assert sum(rows.values()) == int(spent[0]), "the sum by endpoint IS the daily ledger (criterion: < 1 %)"
    assert {lane for _, lane, _ in rows} == {"directo", "referencia", "calendario", "estadisticas_contexto"}
    assert sum(n for (e, _, _), n in rows.items() if e == "/odds/live") >= 60


def test_a_ledger_run_names_the_job_of_the_requests_that_follow(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        ledger = RunLedger(conn)
        run_id = ledger.open("pm0102_probe_job")
        try:
            assert q.current_usage_tags() == (q.NO_LANE, "pm0102_probe_job")
        finally:
            ledger.close(run_id, RunCounters())
            conn.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (run_id,))


def _minutes(dsn: str, rows: list[tuple[datetime, int]]) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.executemany("INSERT INTO raw.provider_minute_usage (provider, minute, spent) VALUES (%s, %s, %s)",
                        [(PROVIDER, m, n) for m, n in rows])


def daily(dsn: str) -> dict[str, tuple[Any, ...]]:
    with psycopg.connect(dsn) as conn:
        rows = conn.execute("SELECT usage_date, minutes_active, requests, max_per_minute, peak_minute, p50, p95, p99, complete "
                            "FROM raw.provider_minute_daily WHERE provider = %s", (PROVIDER,)).fetchall()
    return {r[0].isoformat(): tuple(r[1:]) for r in rows}


def test_the_hourly_prune_keeps_yesterdays_and_todays_peaks_before_they_are_gone(dsn: str) -> None:
    yesterday = datetime(2026, 11, 19, 0, 0, tzinfo=UTC)
    # yesterday: 100 minutes of 1..100 requests; today: three minutes before 10:00
    _minutes(dsn, [(yesterday + timedelta(minutes=i), i + 1) for i in range(100)])
    _minutes(dsn, [(datetime(2026, 11, 20, 9, m, tzinfo=UTC), n) for m, n in ((1, 5), (2, 9), (3, 7))])
    _minutes(dsn, [(datetime(2026, 11, 17, 23, 0, tzinfo=UTC), 400)])  # older than yesterday: not summarised, pruned
    clock = FrozenClock(datetime(2026, 11, 20, 10, 0, 5, tzinfo=UTC))
    set_clock(clock)
    limiter = q.PersistentMinuteLimiter(limit=360, connect=connector(dsn), provider=PROVIDER, summarize=True)
    assert limiter.try_spend(1), "the first request of 10:00 - the one that prunes"
    got = daily(dsn)
    assert set(got) == {"2026-11-19", "2026-11-20"}
    minutes, requests, peak, peak_at, p50, p95, p99, complete = got["2026-11-19"]
    assert (minutes, requests, peak, complete) == (100, 5050, 100, True)
    assert peak_at == yesterday + timedelta(minutes=99)
    assert float(p50) == 50.5 and abs(float(p95) - 95.05) <= 0.1 and abs(float(p99) - 99.01) <= 0.1
    assert got["2026-11-20"][:3] == (4, 22, 9) and got["2026-11-20"][-1] is False, "today so far, the 10:00 minute included"
    with psycopg.connect(dsn) as conn:
        left = conn.execute("SELECT count(*) FROM raw.provider_minute_usage WHERE provider = %s AND minute < %s",
                            (PROVIDER, datetime(2026, 11, 18, 10, 0, tzinfo=UTC))).fetchone()
    assert left == (0,), "the prune still ran"
    # later in the day, once the first minutes of yesterday are gone, its summary is never shrunk
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM raw.provider_minute_usage WHERE provider = %s AND minute < %s",
                     (PROVIDER, yesterday + timedelta(minutes=50)))
        q.summarize_minutes(conn, provider=PROVIDER, at=datetime(2026, 11, 20, 11, 0, tzinfo=UTC))
    assert daily(dsn)["2026-11-19"][:2] == (100, 5050)


def test_without_summarize_the_limiter_keeps_no_summary(dsn: str) -> None:
    _minutes(dsn, [(datetime(2026, 11, 19, 12, 0, tzinfo=UTC), 3)])
    set_clock(FrozenClock(datetime(2026, 11, 20, 10, 0, 5, tzinfo=UTC)))
    limiter = q.PersistentMinuteLimiter(limit=360, connect=connector(dsn), provider=PROVIDER)
    assert limiter.try_spend(1)
    assert daily(dsn) == {}


def test_the_storage_reports_file_keeps_one_measure_of_the_database(dsn: str) -> None:
    sql = SIZE_SQL.read_text(encoding="utf-8").replace("'storage-report'", "'pm0102_test'")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.encode())  # a script of several statements, no parameters
        row = conn.execute("SELECT database_name, db_bytes, schema_bytes, top_tables FROM audit.db_size_history "
                           "WHERE source = 'pm0102_test'").fetchone()
        assert row is not None
        name, size, schemas, top = row
        actual = conn.execute("SELECT current_database(), pg_database_size(current_database())").fetchone()
        assert actual is not None
        assert name == actual[0] and size > 0 and abs(size - int(actual[1])) < 64 * 1024 * 1024
        assert {"raw", "core", "audit"} <= set(schemas) and all(isinstance(v, int) and v >= 0 for v in schemas.values())
        assert 0 < len(top) <= 12 and all({"name", "bytes"} == set(t) for t in top)
        assert [t["bytes"] for t in top] == sorted((t["bytes"] for t in top), reverse=True)
        assert sum(schemas.values()) <= size
