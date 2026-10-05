"""No run stays 'running' for ever: a real crash, a hung run, a capped run, the shared per-minute limit.

5 Oct 2026: two odds captures open across worker restarts and a RAW replay killed by hand stayed 'running' for
11-20 hours and the System page said DEGRADED (fbi.ops.run_watchdog)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.notify.service import collect
from fbi.ops.run_watchdog import recover_runs
from fbi.providers.quota import PersistentMinuteLimiter
from fbi.quality.metrics import data_quality_snapshot


@pytest.fixture()
def conn(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database) as c:
        yield c
        c.rollback()
        c.execute("DELETE FROM raw.ingestion_runs WHERE job_name LIKE 'wd-%' OR job_type LIKE 'wd_%'")
        c.execute("DELETE FROM raw.provider_minute_usage WHERE provider = 'wd-test'")
        c.commit()


def status(conn: psycopg.Connection, run_id: int) -> tuple[str, str | None]:
    row = conn.execute("SELECT status, last_error FROM raw.ingestion_runs WHERE id = %s", (run_id,)).fetchone()
    assert row is not None
    return row[0], row[1]


def test_a_run_whose_process_is_killed_is_recovered_at_once(conn: psycopg.Connection, migrated_database: str) -> None:
    """A real crash: a child process opens a run and is SIGKILLed before it can close it."""
    code = (
        "import os, signal, psycopg\n"
        "from fbi.ingestion.ledger import RunLedger\n"
        f"c = psycopg.connect({migrated_database!r})\n"
        "rid = RunLedger(c).open('wd_crash')\n"
        "print(rid, flush=True)\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    child = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
    assert child.returncode == -9, child.stderr
    run_id = int(child.stdout.strip().splitlines()[-1])  # the last line: the run id (logs come first)
    live = RunLedger(conn).open("wd_live")  # this process: alive, inside its deadline
    owner = conn.execute("SELECT owner_pid, deadline_at > started_at, heartbeat_at IS NOT NULL "
                         "FROM raw.ingestion_runs WHERE id = %s", (live,)).fetchone()
    assert owner == (os.getpid(), True, True)

    recovered = recover_runs(conn, at=datetime.now(UTC))
    assert [(r.run_id, r.status) for r in recovered] == [(run_id, "interrupted")]
    st, why = status(conn, run_id)
    assert st == "interrupted" and why is not None and "is gone" in why and "run watchdog" in why
    assert status(conn, live)[0] == "running"
    assert recover_runs(conn, at=datetime.now(UTC)) == [], "idempotent"
    RunLedger(conn).close(live, RunCounters(api_calls=1, rows_inserted=1))


def test_a_hung_run_is_stale_and_its_late_close_keeps_both_facts(conn: psycopg.Connection) -> None:
    ledger = RunLedger(conn)
    run_id = ledger.open("live_odds_capture")  # a 10-minute deadline
    later = datetime.now(UTC) + timedelta(minutes=11)
    recovered = recover_runs(conn, at=later)
    assert [(r.run_id, r.status) for r in recovered] == [(run_id, "stale")]
    snap = data_quality_snapshot(conn, horizon_hours=24, prematch_windows=6, daily_budget=60000)
    assert snap.stale_running_jobs == 0, "closed: no longer stuck"
    ledger.close(run_id, RunCounters(api_calls=1, rows_inserted=2))
    st, why = status(conn, run_id)
    assert st == "completed" and why is not None and "after the watchdog had marked it stale" in why
    conn.execute("UPDATE raw.ingestion_runs SET job_name = 'wd-hung' WHERE id = %s", (run_id,))
    conn.commit()


def test_a_capped_run_is_not_a_failure_and_a_stuck_run_is_judged_by_its_deadline(conn: psycopg.Connection) -> None:
    ledger = RunLedger(conn)
    capped = ledger.open("wd_capped")
    ledger.close(capped, RunCounters(api_calls=300, payloads_stored=300, stopped_early="allowance 300"))
    failed = ledger.open("wd_failed")
    ledger.close(failed, RunCounters(errors=["CheckViolation: x"]))
    long_backfill = ledger.open("historical_backfill")  # 3 h deadline
    conn.execute("UPDATE raw.ingestion_runs SET started_at = now() - interval '150 minutes', "
                 "job_name = 'wd-long' WHERE id = %s", (long_backfill,))
    conn.commit()
    snap = data_quality_snapshot(conn, horizon_hours=24, prematch_windows=6, daily_budget=60000)
    assert snap.capped_jobs_24h >= 1 and snap.failed_jobs_24h >= 1
    stuck = conn.execute("SELECT count(*) FROM raw.ingestion_runs WHERE id = %s AND status = 'running' "
                         "AND deadline_at < now()", (long_backfill,)).fetchone()
    assert stuck == (0,), "two and a half hours into a three-hour deadline is working, not stuck"
    ledger.close(long_backfill, RunCounters())


def test_the_notifier_tells_of_recovered_runs_and_of_a_job_failing_three_times(conn: psycopg.Connection) -> None:
    ledger = RunLedger(conn)
    for _ in range(3):
        ledger.close(ledger.open("wd_broken"), RunCounters(errors=["boom"]))
    hung = ledger.open("live_match_capture")
    conn.execute("UPDATE raw.ingestion_runs SET job_name = 'wd-hung2' WHERE id = %s", (hung,))
    conn.commit()
    recover_runs(conn, at=datetime.now(UTC) + timedelta(minutes=11))
    drafts = {d.kind: d for d in collect(conn, at=datetime.now(UTC) + timedelta(minutes=12))
              if d.kind in ("run_recovered", "job_failing")}
    assert "job_failing" in drafts and "wd_broken" in drafts["job_failing"].title
    assert "run_recovered" in drafts and "stale" in drafts["run_recovered"].title


def test_the_per_minute_limit_is_shared_by_every_process(conn: psycopg.Connection, migrated_database: str) -> None:
    clock = FrozenClock(datetime(2026, 10, 5, 2, 46, 10, tzinfo=UTC))
    set_clock(clock)
    slept: list[float] = []

    async def advance(seconds: float) -> None:
        slept.append(seconds)
        clock.advance(seconds=seconds)

    try:
        def one() -> PersistentMinuteLimiter:
            return PersistentMinuteLimiter(limit=2, provider="wd-test", sleep=advance,
                                           connect=lambda: psycopg.connect(migrated_database, autocommit=True))

        first, second = one(), one()  # two processes
        assert first.try_spend() and second.try_spend()
        assert not first.try_spend(), "the minute is full for everyone"
        import asyncio

        waited = asyncio.run(second.acquire())
        assert 49 <= waited <= 52 and len(slept) == 1, "waits for the next minute, then goes"
    finally:
        set_clock(SystemClock())
