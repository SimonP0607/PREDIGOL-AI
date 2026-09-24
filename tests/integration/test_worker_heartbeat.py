"""A quiet worker and a dead worker must not look the same.

Before revision 0014 /health judged the worker from the job ledger, which only
records ticks that did something. On a day with no fixture in a capture
window a healthy worker writes nothing for hours - and was reported as
"last run 400 min ago", exactly like one that had crashed. After a 12-hour
outage on 2026-09-24 the two needed telling apart, and could not be.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.ops.heartbeat import HeartbeatWriter, last_success, latest_heartbeat, next_run_after
from fbi.quality.health import health

NOW = datetime(2026, 9, 24, 18, 0, tzinfo=UTC)
TICK_S = 15 * 60


@pytest.fixture()
def clock(db: psycopg.Connection) -> Iterator[FrozenClock]:
    c = FrozenClock(NOW)
    set_clock(c)
    yield c
    set_clock(SystemClock())
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM raw.worker_heartbeats")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type IN ('fixtures_sync','results_sync','odds_capture')")
    db.commit()


def writer(db: psycopg.Connection) -> HeartbeatWriter:
    return HeartbeatWriter(db, worker_id="test-host:worker", tick_interval_s=TICK_S, code_version="abc123")


def test_a_quiet_worker_that_keeps_beating_is_healthy(db: psycopg.Connection, clock: FrozenClock) -> None:
    """The false alarm this revision removes: nothing to capture for six
    hours, a heartbeat every fifteen minutes, and a healthy verdict."""
    ledger = RunLedger(db)
    run_id = ledger.open("fixtures_sync")
    ledger.close(run_id, RunCounters(api_calls=2, payloads_stored=2))
    w = writer(db)
    w.started()
    for _ in range(24):  # six hours of quiet ticks
        clock.advance(minutes=15)
        w.beat(outcome="nothing_scheduled", duration_ms=40, lag_ms=3)
    h = health(db, version="t", daily_budget=60)
    assert h.worker.status == "ok", h.worker.detail
    assert h.worker.data["alive"] is True
    assert h.worker.data["heartbeat"]["ticks"] == 24
    assert h.worker.data["heartbeat"]["last_tick_outcome"] == "nothing_scheduled"


def test_a_worker_that_stopped_beating_is_down_not_degraded(db: psycopg.Connection, clock: FrozenClock) -> None:
    w = writer(db)
    w.started()
    w.beat(outcome="nothing_due", duration_ms=10, lag_ms=0)
    clock.advance(minutes=40)  # two intervals and the grace have passed
    h = health(db, version="t", daily_budget=60)
    assert h.worker.status == "down"
    assert "no heartbeat for 40 min" in h.worker.detail
    assert h.status == "down", "a dead worker loses odds windows: the system is down, not degraded"


def test_within_two_intervals_a_late_beat_is_still_alive(db: psycopg.Connection, clock: FrozenClock) -> None:
    w = writer(db)
    w.started()
    clock.advance(minutes=31)
    assert health(db, version="t", daily_budget=60).worker.status == "ok"


def test_a_clean_stop_is_reported_as_a_stop(db: psycopg.Connection, clock: FrozenClock) -> None:
    w = writer(db)
    w.started()
    clock.advance(minutes=1)
    w.stopped()
    h = health(db, version="t", daily_budget=60)
    assert h.worker.status == "down" and "stopped" in h.worker.detail


def test_alive_but_failing_is_degraded(db: psycopg.Connection, clock: FrozenClock) -> None:
    w = writer(db)
    w.started()
    w.beat(outcome="failed", duration_ms=1200, lag_ms=0)
    h = health(db, version="t", daily_budget=60)
    assert h.worker.status == "degraded" and "failed" in h.worker.detail


def test_a_partial_job_still_degrades_a_live_worker(db: psycopg.Connection, clock: FrozenClock) -> None:
    w = writer(db)
    w.started()
    ledger = RunLedger(db)
    run_id = ledger.open("results_sync")
    ledger.close(run_id, RunCounters(api_calls=2, payloads_stored=1, errors=["refused"]))
    h = health(db, version="t", daily_budget=60)
    assert h.worker.status == "degraded" and "partly" in h.worker.detail


def test_a_restart_reuses_the_row_and_resets_the_tick_count(db: psycopg.Connection, clock: FrozenClock) -> None:
    w = writer(db)
    w.started()
    w.beat(outcome="nothing_scheduled", duration_ms=5, lag_ms=1)
    clock.advance(hours=1)
    w.started()
    beat = latest_heartbeat(db)
    assert beat is not None and beat.ticks == 0 and beat.started_at == NOW + timedelta(hours=1)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw.worker_heartbeats")
        assert cur.fetchone() == (1,)


# ---------------------------------------------------------------------------
# Catch-up scheduling, anchored on the ledger
# ---------------------------------------------------------------------------

def test_a_job_that_never_ran_is_due_now() -> None:
    assert next_run_after(None, timedelta(hours=12), NOW) == NOW


def test_a_job_that_ran_recently_waits_for_its_interval() -> None:
    """A restart must not re-spend a 12-hourly sync's requests."""
    assert next_run_after(NOW - timedelta(hours=2), timedelta(hours=12), NOW) == NOW + timedelta(hours=10)


def test_after_an_outage_a_job_catches_up_at_once() -> None:
    """The 2026-09-24 case: down for twelve hours, results for a day the free
    plan stops serving tomorrow. Waiting another interval would lose them."""
    assert next_run_after(NOW - timedelta(hours=13), timedelta(hours=6), NOW) == NOW


def test_last_success_ignores_failed_runs(db: psycopg.Connection, clock: FrozenClock) -> None:
    ledger = RunLedger(db)
    ok = ledger.open("results_sync")
    ledger.close(ok, RunCounters(api_calls=2, payloads_stored=2))
    clock.advance(hours=3)
    bad = ledger.open("results_sync")
    ledger.close(bad, RunCounters(api_calls=2, errors=["x", "y"]))
    assert last_success(db, "results_sync") == NOW, "a failed run is not a success to wait from"
