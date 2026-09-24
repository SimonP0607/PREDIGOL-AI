"""The worker: an APScheduler loop around the odds capturer.

Two jobs, both deliberately boring:

  * ``odds_capture``  runs every ``FBI_ODDS_TICK_MINUTES`` (default 15) and
    captures whatever windows are due. The planner - not the cron expression -
    decides what that means, so changing the cadence never requires touching
    the schedule.
  * ``ensure_partitions`` creates next month's partition of
    market.odds_snapshots before it is needed. Without it every row would land
    in the DEFAULT partition and the range pruning would be worthless.

The tick is short and the planner is idempotent: a missed tick costs one window
at worst, and a duplicated tick costs nothing at all.

  * ``fixtures_sync``  every 12 h, horizon 1 day  -> 2 requests per run, 4/day
  * ``results_sync``   every 6 h, lookback 1 day  -> 2 requests per run, 8/day

Standing cost is therefore about 12 requests/day, leaving roughly 48 of the
60-request budget for odds capture - enough for a Premier League matchday at
four reachable windows per fixture. The numbers are environment variables
rather than constants because the right cadence changes the moment the plan
does.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from datetime import timedelta
from typing import Any

import psycopg
import structlog
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED, JobEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.logging import new_run_id
from fbi.core.version import code_version
from fbi.odds.partitions import ensure_partitions
from fbi.ops.heartbeat import (
    HeartbeatWriter,
    TickOutcome,
    default_worker_id,
    last_success,
    next_run_after,
)

log = structlog.get_logger("worker")

TICK_MINUTES = int(os.environ.get("FBI_ODDS_TICK_MINUTES", "15"))
FIXTURES_SYNC_HOURS = int(os.environ.get("FBI_FIXTURES_SYNC_HOURS", "12"))
FIXTURES_HORIZON_DAYS = int(os.environ.get("FBI_FIXTURES_HORIZON_DAYS", "1"))
RESULTS_SYNC_HOURS = int(os.environ.get("FBI_RESULTS_SYNC_HOURS", "6"))
RESULTS_LOOKBACK_DAYS = int(os.environ.get("FBI_RESULTS_LOOKBACK_DAYS", "1"))


async def _tick() -> TickOutcome:
    """One scheduler tick: partitions, then the windows that are due.

    The planner decides what "due" means; a tick that finds nothing due costs
    zero provider calls. The ledger records every tick that did something.
    """
    from scripts.capture_odds import _build_planner, _client, _upcoming

    from fbi.core.clock import today
    from fbi.odds.capture import OddsCaptureService
    from fbi.odds.repository import OddsRepository
    from fbi.odds.schedule import validate_plan
    from fbi.providers.api_football import ApiFootballProvider

    new_run_id()
    with _connect() as conn:
        ensure_partitions(conn, today=today())
        fixtures = _upcoming(conn, 96)
        if not fixtures:
            log.info("tick.nothing_scheduled")
            return "nothing_scheduled"
        planner = _build_planner()
        covered = planner.covered_keys(
            OddsRepository(conn).observations_since(
                since=now() - timedelta(hours=24),
                provider_fixture_ids=[f.provider_fixture_id for f in fixtures],
            )
        )
        tasks = planner.plan(fixtures, at=now(), already_done=covered)
        if not tasks:
            log.info("tick.nothing_due", fixtures=len(fixtures), next_window=planner.next_run_at(fixtures, at=now()))
            return "nothing_due"
        check = validate_plan(
            tasks, at=now(), budget_remaining=settings.api_football.daily_budget,
            known_fixture_ids={f.provider_fixture_id for f in fixtures},
        )
        if not check.ok:
            log.error("tick.plan_rejected", issues=check.issues)
            return "plan_rejected"
        provider = ApiFootballProvider(_client(), market_filter=settings.odds.market_filter)
        try:
            service = OddsCaptureService(conn, provider, planner, raw_root=settings.runtime.raw_store_dir)
            await service.capture(fixtures)
        finally:
            await provider.aclose()
    return "captured"


async def _daily_fixtures_sync() -> None:
    """Refresh the fixture list for active competitions.

    The horizon is deliberately short. On the free plan ``/fixtures?date=`` is
    served only for about a day either side of today, so a longer horizon does
    not see further - it just spends requests on refusals. Running often is
    what buys reach here, not asking for more at once.
    """
    from scripts.capture_odds import _client, _connect

    from fbi.ingestion.fixtures import SyncStrategy, sync_fixtures
    from fbi.providers.api_football import ApiFootballProvider

    new_run_id()
    # On the free plan the league query is always refused; asking anyway spent
    # one request of our budget per run just to be told so again.
    strategy = SyncStrategy.DATE if settings.provider_plan.plan == "free" else SyncStrategy.AUTO
    with _connect() as conn:
        provider = ApiFootballProvider(_client())
        try:
            await sync_fixtures(conn, provider, horizon_days=FIXTURES_HORIZON_DAYS, strategy=strategy)
        finally:
            await provider.aclose()


async def _results_sync() -> None:
    """Close the loop on fixtures that have been played.

    Without this a fixture whose kick-off passed keeps saying 'NS' for ever,
    because the fixture sync only looks forward. And the window to fix it is
    narrow: the free plan stops serving a date about a day after it passes, so
    a result missed today is missed permanently. That is why this runs on its
    own short cycle instead of riding along with a daily job.
    """
    from scripts.capture_odds import _client, _connect

    from fbi.ingestion.results import sync_results
    from fbi.providers.api_football import ApiFootballProvider

    new_run_id()
    with _connect() as conn:
        provider = ApiFootballProvider(_client())
        try:
            await sync_results(conn, provider, lookback_days=RESULTS_LOOKBACK_DAYS)
        finally:
            await provider.aclose()


_scheduler: AsyncIOScheduler | None = None


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.database.psycopg_url, connect_timeout=5)


def _writer(conn: psycopg.Connection) -> HeartbeatWriter:
    return HeartbeatWriter(
        conn, worker_id=default_worker_id(), tick_interval_s=TICK_MINUTES * 60, code_version=code_version()
    )


def _jobs() -> dict[str, Any]:
    if _scheduler is None:
        return {}
    return {
        j.id: (j.next_run_time.isoformat() if j.next_run_time else None) for j in _scheduler.get_jobs()
    }


def _lag_ms() -> int | None:
    """How late this tick started relative to its scheduled instant.

    For an interval trigger the current run was scheduled exactly one interval
    before the job's (already advanced) next run time.
    """
    if _scheduler is None:
        return None
    job = _scheduler.get_job("odds_capture")
    if job is None or job.next_run_time is None:
        return None
    scheduled = job.next_run_time - timedelta(minutes=TICK_MINUTES)
    return max(int((now() - scheduled).total_seconds() * 1000), 0)


async def _tick_with_heartbeat() -> None:
    """Run the tick and record that the worker is alive - whatever happened.

    A failed tick still beats: the process is alive, and "alive but failing"
    is a different diagnosis from "dead". The failure is re-raised so the
    scheduler logs it as well.
    """
    lag = _lag_ms()
    started = time.monotonic()
    outcome: TickOutcome = "failed"
    try:
        outcome = await _tick()
    finally:
        duration = int((time.monotonic() - started) * 1000)
        try:
            with _connect() as conn:
                _writer(conn).beat(outcome=outcome, duration_ms=duration, lag_ms=lag, jobs=_jobs())
        except psycopg.Error as exc:
            log.error("heartbeat.write_failed", error=exc.__class__.__name__)


def _on_missed(event: JobEvent) -> None:
    """A run skipped because the process could not start it in time - most
    often a suspended laptop. Each one is a window that may be gone."""
    log.warning("job.missed", job=event.job_id)


def _on_error(event: JobEvent) -> None:
    log.error("job.failed", job=event.job_id)


async def main() -> None:
    global _scheduler
    configure_logging(settings.runtime.log_level)
    scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler = scheduler
    moment = now()

    # Periodic syncs are anchored on the ledger, not on process start: a worker
    # that was down for twelve hours catches up at once, and one restarted five
    # times in an hour does not spend five times the requests.
    with _connect() as conn:
        fixtures_next = next_run_after(last_success(conn, "fixtures_sync"), timedelta(hours=FIXTURES_SYNC_HOURS), moment)
        results_next = next_run_after(last_success(conn, "results_sync"), timedelta(hours=RESULTS_SYNC_HOURS), moment)

    # A tick that could not start on time is still worth running late: the
    # capture tolerance band is wider than any grace time given here.
    tick_grace = TICK_MINUTES * 60
    scheduler.add_job(_tick_with_heartbeat, "interval", minutes=TICK_MINUTES, id="odds_capture",
                      max_instances=1, coalesce=True, misfire_grace_time=tick_grace, next_run_time=moment)
    scheduler.add_job(_daily_fixtures_sync, "interval", hours=FIXTURES_SYNC_HOURS, id="fixtures_sync",
                      max_instances=1, coalesce=True, misfire_grace_time=3600, next_run_time=fixtures_next)
    scheduler.add_job(_results_sync, "interval", hours=RESULTS_SYNC_HOURS, id="results_sync",
                      max_instances=1, coalesce=True, misfire_grace_time=3600, next_run_time=results_next)
    scheduler.add_listener(_on_missed, EVENT_JOB_MISSED)
    scheduler.add_listener(_on_error, EVENT_JOB_ERROR)
    scheduler.start()

    with _connect() as conn:
        _writer(conn).started(jobs=_jobs())
    log.info(
        "worker.started",
        tick_minutes=TICK_MINUTES,
        fixtures_sync_hours=FIXTURES_SYNC_HOURS,
        results_sync_hours=RESULTS_SYNC_HOURS,
        daily_budget=settings.api_football.daily_budget,
        code_version=code_version(),
        fixtures_sync_next=fixtures_next.isoformat(),
        results_sync_next=results_next.isoformat(),
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    scheduler.shutdown(wait=True)
    try:
        with _connect() as conn:
            _writer(conn).stopped()
    except psycopg.Error:
        pass
    log.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())
