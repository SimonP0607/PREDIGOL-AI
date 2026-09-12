"""/health and the data-quality snapshot read the ledger and the store; they never call out."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.quality.health import health
from fbi.quality.metrics import data_quality_snapshot

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def test_health_with_an_empty_ledger_is_honest_not_green(db: psycopg.Connection) -> None:
    set_clock(FrozenClock(NOW))
    try:
        h = health(db, version="t", daily_budget=60)
    finally:
        set_clock(SystemClock())
    assert h.database.status == "ok"
    assert h.database.data["revision"] == "0011"
    assert h.worker.status == "unknown", "no run yet is 'unknown', never 'ok'"
    assert h.football_provider.status == "ok" and h.football_provider.data["requests_today"] == 0
    assert h.status == "degraded"
    payload = h.as_dict()
    assert "password" not in str(payload) and "@" not in str(payload.get("database"))


def test_health_reports_the_last_run_and_goes_stale_after_three_ticks(db: psycopg.Connection) -> None:
    clock = FrozenClock(NOW)
    set_clock(clock)
    try:
        ledger = RunLedger(db)
        run_id = ledger.open("odds_capture", scheduled_for=NOW)
        ledger.close(run_id, RunCounters(api_calls=2, rows_inserted=6))
        fresh = health(db, version="t", daily_budget=60)
        assert fresh.worker.status == "ok" and fresh.worker.data["last_job"] == "odds_capture"
        assert fresh.football_provider.data["requests_today"] == 2
        clock.advance(minutes=50)
        stale = health(db, version="t", daily_budget=60)
        assert stale.worker.status == "degraded" and "min ago" in stale.worker.detail
    finally:
        set_clock(SystemClock())
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (run_id,))
        db.commit()


def test_a_failed_run_degrades_the_worker_and_the_provider(db: psycopg.Connection) -> None:
    set_clock(FrozenClock(NOW))
    try:
        ledger = RunLedger(db)
        run_id = ledger.open("fixtures_sync")
        ledger.close(run_id, RunCounters(api_calls=1, errors=["HTTP 429"]))
        h = health(db, version="t", daily_budget=60)
        assert h.worker.status == "degraded" and h.worker.data["last_error"] == "HTTP 429"
        assert h.football_provider.status == "degraded"
    finally:
        set_clock(SystemClock())
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (run_id,))
        db.commit()


def test_the_health_endpoint_never_spends_quota(db: psycopg.Connection) -> None:
    """The provider check is derived from the ledger. If it ever called
    /status, requests_today would move on its own."""
    before = health(db, version="t", daily_budget=60).football_provider.data["requests_today"]
    for _ in range(5):
        health(db, version="t", daily_budget=60)
    after = health(db, version="t", daily_budget=60).football_provider.data["requests_today"]
    assert before == after


def test_quality_snapshot_uses_null_ratios_when_nothing_is_expected(db: psycopg.Connection) -> None:
    set_clock(FrozenClock(NOW))
    try:
        snap = data_quality_snapshot(db)
    finally:
        set_clock(SystemClock())
    d = snap.as_dict()
    assert d["fixtures_expected"] == 0
    assert d["fixture_odds_coverage"] is None, "nothing expected -> null, never 0 or 1"
    assert d["markets_tracked"] == 2  # the seed's 1X2 and DC
    assert any("null, not zero" in n for n in snap.notes)


def test_quality_snapshot_counts_a_captured_fixture(db: psycopg.Connection) -> None:
    from tests.integration.conftest import Seed  # noqa: F401 - fixture types

    set_clock(FrozenClock(NOW))
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE core.competitions SET is_tracked = true WHERE provider_league_id = 39")
            cur.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE provider_fixture_id = 1001", (NOW + timedelta(hours=30),))
            cur.execute(
                "INSERT INTO market.odds_snapshots "
                "SELECT f.id, b.id, '1X2', 'Home', 0, 2.10, %s, 1800, 'prematch', 'h1' "
                "FROM core.fixtures f, market.bookmakers b WHERE f.provider_fixture_id = 1001 AND b.provider_bookmaker_id = 8 "
                "ON CONFLICT DO NOTHING",
                (NOW - timedelta(hours=1),),
            )
        snap = data_quality_snapshot(db)
        assert snap.fixtures_expected == 1 and snap.fixtures_with_odds == 1
        assert snap.as_dict()["fixture_odds_coverage"] == 1.0
        assert snap.stale_fixtures == 0
        assert snap.bookmakers_seen_24h == 1 and snap.markets_seen_24h == 1
    finally:
        set_clock(SystemClock())
        db.rollback()


def test_requests_today_uses_the_application_clock_not_the_database_clock(
    db: psycopg.Connection,
) -> None:
    """A run recorded "today" by the frozen clock must count as today.

    This failed the first time the suite ran on a different calendar day from
    the one the test was written on: the query said
    `started_at >= date_trunc('day', now())` and `now()` was the database's,
    not the clock the capturer bills its quota against.
    """
    clock = FrozenClock(datetime(2026, 3, 4, 9, 30, tzinfo=UTC))
    set_clock(clock)
    try:
        ledger = RunLedger(db)
        today_run = ledger.open("odds_capture")
        ledger.close(today_run, RunCounters(api_calls=7))
        clock.advance(hours=30)  # next day by the same clock
        yesterday_only = health(db, version="t", daily_budget=60)
        assert yesterday_only.football_provider.data["requests_today"] == 0

        clock.advance(hours=-30)
        same_day = health(db, version="t", daily_budget=60)
        assert same_day.football_provider.data["requests_today"] == 7
    finally:
        set_clock(SystemClock())
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (today_run,))
        db.commit()
