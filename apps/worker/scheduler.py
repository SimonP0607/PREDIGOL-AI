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
  * ``pick_pipeline``  every 30 min and right after a capture: forecasts,
    shadow picks, settlement. Database only, zero requests.
  * ``notifier``       every 10 min: new events -> audit.notifications ->
    Telegram when a token is configured, 'skipped' otherwise.

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
from fbi.odds.horizons import DEFAULT_HORIZON_DAYS
from fbi.odds.live_cadence import (
    DEFAULT_LIVE_DAILY_BUDGET,
    POLL_FLOOR_SECONDS,
    wake_interval,
)
from fbi.odds.partitions import ensure_partitions
from fbi.odds.schedule import NEAR_CLOSE_TOLERANCE_MINUTES
from fbi.ops.heartbeat import (
    HeartbeatWriter,
    TickOutcome,
    default_worker_id,
    last_success,
    next_run_after,
)
from fbi.ops.reaper import boot_time, reap_interrupted_runs
from fbi.ops.worker_lock import WorkerLock, holder

log = structlog.get_logger("worker")

# Defaults follow the plan. On the free plan the provider shows fixtures about a
# day ahead and history is a few requests a day; on a paid plan the worker looks
# four days ahead (so T-72h and T-48h become reachable) and the historical
# migration runs every hour, always behind the live reserve it computes itself.
PAID_PLAN = settings.provider_plan.plan != "free"
NEAR_CLOSE_SPAN_MINUTES = 2 * NEAR_CLOSE_TOLERANCE_MINUTES
"""Width of the near-close opportunity: the planner accepts a fixture within that many
minutes either side of the configured window."""

TICK_MINUTES = int(os.environ.get(
    "FBI_ODDS_TICK_MINUTES", str(max(1, NEAR_CLOSE_SPAN_MINUTES - 1))))
"""How often the capture tick runs, and it cannot be coarser than the near-close window.

It was 15 minutes against a 6-minute window, so the closing price was captured on about
40% of fixtures - and /odds/live keeps no history, so the other 60% are unrecoverable. The
closing line is the most informative price there is: it is the market's final word and the
benchmark any edge is measured against.

Ticking more often is nearly free. The planner computes what is due from the database and
a tick with nothing due issues no provider request at all, while the 45-minute prematch
tolerance and the covered-key de-duplication keep the extra ticks from re-requesting a
window already captured. The cost is a few database queries, not quota."""
FIXTURES_SYNC_HOURS = int(os.environ.get("FBI_FIXTURES_SYNC_HOURS", "6" if PAID_PLAN else "12"))
"""Every current season's whole fixture list, one request each (~124 a run). Six hours, not
twelve: a cup draw published in the morning reached the database at the next run, and a
match announced 3 days out had already missed its T-72h price window."""
FIXTURES_HORIZON_DAYS = int(os.environ.get(
    "FBI_FIXTURES_HORIZON_DAYS", str(DEFAULT_HORIZON_DAYS) if PAID_PLAN else "1"))
"""Four days was the Free-plan figure, kept after the upgrade by oversight.

Prices were measured at T-18.2 days, so a four-day horizon meant a fixture ten days
out was not in the database at all, the capture planner could not see it, and the
earliest and least efficient part of its price series - the part no later request can
recover - was never captured. Under the LEAGUE strategy the wider horizon costs the
same one request per competition-season."""
RESULTS_SYNC_HOURS = int(os.environ.get("FBI_RESULTS_SYNC_HOURS", "6"))
RESULTS_LOOKBACK_DAYS = int(os.environ.get("FBI_RESULTS_LOOKBACK_DAYS", "1"))
QUALITY_SWEEP_HOURS = int(os.environ.get("FBI_QUALITY_SWEEP_HOURS", "6"))
CONTEXT_REFRESH_HOURS = int(os.environ.get("FBI_CONTEXT_REFRESH_HOURS", "12"))
"""League tables and injury reports for the active seasons (fbi.ingestion.context_refresh)."""
CONTEXT_DUE_MINUTES = int(os.environ.get("FBI_CONTEXT_DUE_MINUTES", "30"))
"""Tables a finished match changed, injury lists of the next 48 hours (``refresh_due_context``).

The provider updates a table every hour and injuries every four hours; the twelve-hour
cycle above left a table up to half a day behind the match that changed it."""
ELO_REFRESH_HOURS = int(os.environ.get("FBI_ELO_REFRESH_HOURS", "6"))
"""Elo recomputed from every stored result (fbi.features.elo_refresh). The ratings were
computed once and never extended; six hours keeps them within a matchday."""
CATALOGUE_REFRESH_HOURS = int(os.environ.get("FBI_CATALOGUE_REFRESH_HOURS", "24"))
"""Seasons and coverage flags from one /leagues request (fbi.ingestion.catalogue_refresh)."""
RESULTS_REPAIR_MINUTES = int(os.environ.get("FBI_RESULTS_REPAIR_MINUTES", "30"))
"""Tracked fixtures over three hours past kick-off that still do not say they finished,
re-read by id (20 per request). It rode along with the six-hourly results sync, so a
match the live follower missed could stay "awaiting a result" for six hours."""
FINAL_PREMATCH_MINUTES = int(os.environ.get("FBI_FINAL_PREMATCH_MINUTES", "60"))
"""The provider's last pre-match prices for every tracked match played in the last six days,
read once each (fbi.odds.final_prematch). It keeps them seven days, so the matches the capture
missed while the worker was down are recovered as long as it comes back within the week."""
LIVE_MATCH_SECONDS = int(os.environ.get("FBI_LIVE_MATCH_SECONDS", "60"))
LIVE_MATCH_MAX_REQUESTS = int(os.environ.get("FBI_LIVE_MATCH_MAX_REQUESTS", "10"))
LIVE_MATCH_RESERVE = int(os.environ.get("FBI_LIVE_MATCH_RESERVE", "3000"))
"""Matches in play are followed through the fixture feed every minute: state, events,
statistics and line-ups for 20 fixtures per request (fbi.ingestion.live_match). It stops
when fewer than LIVE_MATCH_RESERVE requests are left today, so the odds capture - which
comes first - always keeps its share."""
"""The sweep reads the database only (about 10 s). It used to be run by hand, so the
Data Quality page showed whatever the last manual run found - two days old after
the machine was off."""
BACKFILL_HOURS = int(os.environ.get("FBI_BACKFILL_HOURS", "1" if PAID_PLAN else "6"))
BACKFILL_MAX_PER_RUN = int(os.environ.get("FBI_BACKFILL_MAX_PER_RUN", "1500" if PAID_PLAN else "6"))
LIVE_TICK_SECONDS = int(os.environ.get(
    "FBI_LIVE_TICK_SECONDS", str(wake_interval(POLL_FLOOR_SECONDS))))
"""How often the live job WAKES. How often it CALLS is the cadence's decision.

HALF the 30 s capture interval, and the halving is the point. The provider's
measured refresh period is ~31 s - 12 calls 10.4 s apart returned 5 distinct
payloads, every fixture's ``update`` stamp moving together once every three
ticks - so 30 s is the interval worth capturing at. Waking at 30 s to capture
every 30 s produced 60 s: the wake-up arrives a fraction before its own
deadline, the cadence correctly declines, and the next one is a full interval
late. The first night of live capture ran at exactly half the intended rate for
this reason, and a missed in-play refresh cannot be re-fetched.

A wake-up is not a request. The job asks the database whether anything could be
on the pitch and returns without calling the provider when nothing is - so a
night with no football costs a handful of queries and no quota at all."""
LIVE_DAILY_BUDGET = int(os.environ.get(
    "FBI_LIVE_DAILY_BUDGET", str(DEFAULT_LIVE_DAILY_BUDGET)))
PIPELINE_MINUTES = int(os.environ.get("FBI_PIPELINE_MINUTES", "30"))
NOTIFY_MINUTES = int(os.environ.get("FBI_NOTIFY_MINUTES", "10"))


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
    # A fresh price is evaluated at once, not up to half an hour later: the
    # pipeline is database-only and idempotent, so running it here is free.
    await asyncio.to_thread(_pipeline_now)
    return "captured"


async def _live_tick() -> None:
    """In-play capture. Its own pipeline, sharing only client, quota and raw store.

    This job can reach market.live_odds_snapshots and market.live_fixture_states
    and nothing else - LiveCaptureService holds no pre-match repository - so an
    in-play price cannot land in the pre-match series or the backtest from here.
    """
    from scripts.capture_odds import _client

    from fbi.core.clock import today
    from fbi.odds.live_capture import LiveCaptureService
    from fbi.odds.partitions import ensure_partitions
    from fbi.providers.api_football import ApiFootballProvider
    from fbi.providers.quota import read_usage

    new_run_id()
    cfg = settings.api_football
    with _connect() as conn:
        remaining = read_usage(
            conn, budget=min(cfg.daily_budget, cfg.per_day_limit)
        ).remaining
        service = LiveCaptureService(
            conn, provider=None, live_daily_budget=LIVE_DAILY_BUDGET  # type: ignore[arg-type]
        )
        decision = service.plan(remaining_quota=remaining)
        if not decision.should_capture:
            log.debug("live_tick.skipped", reason=decision.reason,
                      next_in_seconds=decision.next_in_seconds)
            return
        ensure_partitions(conn, today=today())
        provider = ApiFootballProvider(_client())
        try:
            report = await LiveCaptureService(
                conn, provider, live_daily_budget=LIVE_DAILY_BUDGET
            ).capture(remaining_quota=remaining)
        finally:
            await provider.aclose()
    if report.captured:
        log.info("live_tick.captured", fixtures=report.fixtures_priced,
                 written=report.quotes_written, duplicate=report.quotes_duplicate,
                 untracked=report.quotes_untracked, suspended=report.values_suspended,
                 accounting_holds=report.accounting_holds)


async def _live_match_tick() -> None:
    """Follow tracked matches in play. Spends nothing when none is."""
    from scripts.capture_odds import _client

    from fbi.ingestion.live_match import capture_live_matches, fixtures_to_follow
    from fbi.providers.api_football import ApiFootballProvider
    from fbi.providers.quota import read_usage

    cfg = settings.api_football
    with _connect() as conn:
        if not fixtures_to_follow(conn, at=now()):
            return
        remaining = read_usage(conn, budget=min(cfg.daily_budget, cfg.per_day_limit)).remaining
        if remaining < LIVE_MATCH_RESERVE:
            log.warning("live_match.skipped", reason="quota reserve", remaining=remaining)
            return
        new_run_id()
        provider = ApiFootballProvider(_client())
        try:
            await capture_live_matches(conn, provider, max_requests=LIVE_MATCH_MAX_REQUESTS)
        finally:
            await provider.aclose()


async def _context_refresh() -> None:
    """Tables and injuries for the current seasons: what the Match Center shows as context."""
    from scripts.capture_odds import _client

    from fbi.ingestion.context_refresh import refresh_context
    from fbi.providers.api_football import ApiFootballProvider

    new_run_id()
    with _connect() as conn:
        provider = ApiFootballProvider(_client())
        try:
            await refresh_context(conn, provider)
        finally:
            await provider.aclose()


async def _context_due() -> None:
    """Only what a match made due: a changed table, the injury lists of the next two days."""
    from scripts.capture_odds import _client

    from fbi.ingestion.context_refresh import refresh_due_context
    from fbi.providers.api_football import ApiFootballProvider

    new_run_id()
    with _connect() as conn:
        provider = ApiFootballProvider(_client())
        try:
            await refresh_due_context(conn, provider)
        finally:
            await provider.aclose()


async def _results_repair() -> None:
    """Fixtures past kick-off that still do not say they finished, by id; and one more read
    of each finished match once it has settled (final statistics, corrected events)."""
    from scripts.capture_odds import _client

    from fbi.ingestion.live_match import refresh_post_match, repair_stale_results
    from fbi.providers.api_football import ApiFootballProvider

    new_run_id()
    with _connect() as conn:
        provider = ApiFootballProvider(_client())
        try:
            await repair_stale_results(conn, provider)
            await refresh_post_match(conn, provider)
        finally:
            await provider.aclose()


async def _final_prematch() -> None:
    """Each played match's last pre-match prices, once, for the closing-line benchmark."""
    from scripts.capture_odds import _client

    from fbi.odds.final_prematch import recover_final_prematch
    from fbi.providers.api_football import ApiFootballProvider

    new_run_id()
    with _connect() as conn:
        provider = ApiFootballProvider(_client(), market_filter=settings.odds.market_filter)
        try:
            await recover_final_prematch(conn, provider)
        finally:
            await provider.aclose()


async def _catalogue_refresh() -> None:
    """Which season is current, and the coverage flags: one /leagues request a day."""
    from scripts.capture_odds import _client

    from fbi.ingestion.catalogue_refresh import refresh_catalogue
    from fbi.providers.api_football import ApiFootballProvider

    new_run_id()
    with _connect() as conn:
        provider = ApiFootballProvider(_client())
        try:
            await refresh_catalogue(conn, provider)
        finally:
            await provider.aclose()


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
            # What the date sweep left behind (a day the worker was off): by id.
            from fbi.ingestion.live_match import repair_stale_results
            await repair_stale_results(conn, provider)
        finally:
            await provider.aclose()


async def _historical_backfill() -> None:
    """Carry on with pending history - only what live capture can spare.

    The backfill computes its own reserve for the next 24 h of odds windows
    and standing syncs, and defers entirely when the day's remaining budget is
    inside it. History is seeded deliberately with ``scripts.backfill seed``; the
    worker never widens the scope on its own. What it does seed is the refresh of
    the scope it already has: a monthly player-profile sweep and a weekly round of
    current squads (fbi.ingestion.people).
    """
    from scripts.capture_odds import _client

    from fbi.ingestion.backfill import run_backfill
    from fbi.ingestion.people import seed_people_refresh
    from fbi.providers.api_football import ApiFootballProvider

    new_run_id()
    with _connect() as conn:
        # Player profiles monthly, current squads weekly: a refresh of the tracked scope,
        # queued behind everything else in the same budget-guarded backfill.
        seed_people_refresh(conn, at=now())
        provider = ApiFootballProvider(_client())
        try:
            report = await run_backfill(
                conn, provider, max_requests=BACKFILL_MAX_PER_RUN,
                daily_budget=settings.provider_plan.effective_budget,
                prematch_windows=settings.odds.prematch_windows,
            )
        finally:
            await provider.aclose()
    log.info("backfill.tick", done=report.done, refused=report.refused, failed=report.failed,
             allowance=report.allowance, reserve=report.reserve, deferred=report.deferred_reason)


def _pipeline_now() -> None:
    """Forecasts, evaluation of captured prices, settlement. Never raises into
    the capture: a failure is logged and recorded in its own ledger run."""
    from fbi.picks.pipeline import run_pipeline

    try:
        with _connect() as conn:
            run_pipeline(conn, at=now(), code_version=code_version())
    except Exception as exc:  # the capture has already been committed
        log.error("pipeline.failed", error=f"{type(exc).__name__}: {exc}"[:300])


def _quality_sweep_now() -> None:
    """Record what is wrong, never repair it. Failures are logged and in the ledger."""
    from fbi.ingestion.ledger import RunCounters, RunLedger
    from fbi.quality.detect import sweep

    try:
        with _connect() as conn:
            ledger = RunLedger(conn)
            run_id = ledger.open("quality_sweep", params={"apply": True, "source": "worker"})
            counters = RunCounters()
            report = None
            try:
                report = sweep(conn, run_id=run_id, apply=True)
                counters.rows_inserted = report.issues_opened
                counters.rows_updated = report.issues_seen_again
            finally:
                ledger.close(run_id, counters,
                             notes=f"{len(report.checks)} checks" if report else "the sweep did not finish")
                conn.commit()
    except Exception as exc:  # a sweep problem must never stop the capture
        log.error("quality_sweep.failed", error=f"{type(exc).__name__}: {exc}"[:300])


async def _quality_sweep() -> None:
    new_run_id()
    await asyncio.to_thread(_quality_sweep_now)


async def _pipeline() -> None:
    new_run_id()
    await asyncio.to_thread(_pipeline_now)


def _elo_refresh_now() -> None:
    from fbi.features.elo_refresh import refresh_elo

    with _connect() as conn:
        refresh_elo(conn)


async def _elo_refresh() -> None:
    """The whole Elo history from every stored result (seconds of arithmetic, zero requests),
    in a thread so the live jobs keep their cadence."""
    new_run_id()
    await asyncio.to_thread(_elo_refresh_now)


def _notify_now() -> None:
    """Turn new events into messages. Without a Telegram token they are recorded as skipped."""
    from fbi.notify.service import channel_from_env, run_notifier

    channel = channel_from_env()
    try:
        with _connect() as conn:
            run_notifier(conn, channel)
    except Exception as exc:  # a notification problem must never stop the worker
        log.error("notify.failed", error=type(exc).__name__)
    finally:
        if channel is not None:
            channel.close()


async def _notify() -> None:
    await asyncio.to_thread(_notify_now)


_scheduler: AsyncIOScheduler | None = None
_lock: WorkerLock | None = None
_stop: asyncio.Event | None = None

EXIT_ANOTHER_WORKER = 75
"""EX_TEMPFAIL: not an error in this worker, and worth trying again later."""


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
    if _lock is not None:
        held = _lock.still_held()
        if held is False:
            # The database restarted and another worker took the lock first.
            log.error("worker.lock_lost", action="stopping; the other worker carries on")
            if _stop is not None:
                _stop.set()
            return
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
    global _scheduler, _lock, _stop
    configure_logging(settings.runtime.log_level)
    # One worker per database, host or container: the second one leaves at once.
    _lock = WorkerLock.acquire(settings.database.psycopg_url)
    if _lock is None:
        with _connect() as conn:
            other = holder(conn)
        log.error("worker.already_running", held_by=other.application_name if other else None,
                  since=other.backend_start.isoformat() if other and other.backend_start else None,
                  action="not starting: stop the other worker first (scripts/dev-down worker, "
                         "or docker compose stop worker)")
        raise SystemExit(EXIT_ANOTHER_WORKER)
    # Holding the lock means no other worker is alive; runs older than this
    # machine's boot belonged to a process that is gone (fbi.ops.reaper).
    with _connect() as conn:
        reaped = reap_interrupted_runs(conn, boot_time())
    if reaped:
        log.warning("worker.reaped_interrupted_runs", run_ids=reaped)
    scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler = scheduler
    moment = now()

    # Periodic syncs are anchored on the ledger, not on process start: a worker
    # that was down for twelve hours catches up at once, and one restarted five
    # times in an hour does not spend five times the requests.
    with _connect() as conn:
        fixtures_next = next_run_after(last_success(conn, "fixtures_sync"), timedelta(hours=FIXTURES_SYNC_HOURS), moment)
        results_next = next_run_after(last_success(conn, "results_sync"), timedelta(hours=RESULTS_SYNC_HOURS), moment)
        backfill_next = next_run_after(last_success(conn, "historical_backfill"), timedelta(hours=BACKFILL_HOURS), moment)
        sweep_next = next_run_after(last_success(conn, "quality_sweep"), timedelta(hours=QUALITY_SWEEP_HOURS), moment)
        context_next = next_run_after(last_success(conn, "context_refresh"),
                                      timedelta(hours=CONTEXT_REFRESH_HOURS), moment)
        catalogue_next = next_run_after(last_success(conn, "catalogue_refresh"),
                                        timedelta(hours=CATALOGUE_REFRESH_HOURS), moment)
        elo_next = next_run_after(last_success(conn, "elo_refresh"), timedelta(hours=ELO_REFRESH_HOURS), moment)

    # A tick that could not start on time is still worth running late, and how late is
    # set by the capture tolerance - NOT by the interval. Tying it to the interval made
    # the grace shrink from 900s to 300s the moment the tick was tightened to 5 minutes
    # for the near-close window, so a database busy for longer than that dropped every
    # tick instead of running them late. A restore test on the live machine did exactly
    # that for five hours and twenty minutes, and the capture simply stopped.
    tick_grace = settings.odds.odds_window_tolerance * 60
    scheduler.add_job(_tick_with_heartbeat, "interval", minutes=TICK_MINUTES, id="odds_capture",
                      max_instances=1, coalesce=True, misfire_grace_time=tick_grace, next_run_time=moment)
    # Live capture comes before everything else in priority, so it gets its own
    # job rather than a slice of the odds tick: a long pre-match capture must
    # never be the reason an in-play price was missed, and an in-play price
    # missed is gone - /odds/live has no history to come back for.
    scheduler.add_job(_live_tick, "interval", seconds=LIVE_TICK_SECONDS, id="live_odds",
                      max_instances=1, coalesce=True,
                      misfire_grace_time=LIVE_TICK_SECONDS, next_run_time=moment)
    scheduler.add_job(_live_match_tick, "interval", seconds=LIVE_MATCH_SECONDS, id="live_match",
                      max_instances=1, coalesce=True, misfire_grace_time=LIVE_MATCH_SECONDS,
                      next_run_time=moment + timedelta(seconds=20))
    scheduler.add_job(_daily_fixtures_sync, "interval", hours=FIXTURES_SYNC_HOURS, id="fixtures_sync",
                      max_instances=1, coalesce=True, misfire_grace_time=3600, next_run_time=fixtures_next)
    scheduler.add_job(_results_sync, "interval", hours=RESULTS_SYNC_HOURS, id="results_sync",
                      max_instances=1, coalesce=True, misfire_grace_time=3600, next_run_time=results_next)
    # History waits a few minutes after start so the catch-up syncs go first.
    scheduler.add_job(_historical_backfill, "interval", hours=BACKFILL_HOURS, id="historical_backfill",
                      max_instances=1, coalesce=True, misfire_grace_time=3600,
                      next_run_time=max(backfill_next, moment + timedelta(minutes=5)))
    # Database only: forecasts for new fixtures or new results, shadow picks for
    # new prices, settlement for new results. First run shortly after start.
    scheduler.add_job(_pipeline, "interval", minutes=PIPELINE_MINUTES, id="pick_pipeline", max_instances=1,
                      coalesce=True, misfire_grace_time=PIPELINE_MINUTES * 60,
                      next_run_time=moment + timedelta(minutes=2))
    scheduler.add_job(_notify, "interval", minutes=NOTIFY_MINUTES, id="notifier", max_instances=1, coalesce=True,
                      misfire_grace_time=NOTIFY_MINUTES * 60, next_run_time=moment + timedelta(minutes=3))
    scheduler.add_job(_quality_sweep, "interval", hours=QUALITY_SWEEP_HOURS, id="quality_sweep",
                      max_instances=1, coalesce=True, misfire_grace_time=3600,
                      next_run_time=max(sweep_next, moment + timedelta(minutes=10)))
    scheduler.add_job(_context_refresh, "interval", hours=CONTEXT_REFRESH_HOURS, id="context_refresh",
                      max_instances=1, coalesce=True, misfire_grace_time=3600,
                      next_run_time=max(context_next, moment + timedelta(minutes=15)))
    scheduler.add_job(_context_due, "interval", minutes=CONTEXT_DUE_MINUTES, id="context_due",
                      max_instances=1, coalesce=True, misfire_grace_time=CONTEXT_DUE_MINUTES * 60,
                      next_run_time=moment + timedelta(minutes=6))
    scheduler.add_job(_results_repair, "interval", minutes=RESULTS_REPAIR_MINUTES, id="results_repair",
                      max_instances=1, coalesce=True, misfire_grace_time=RESULTS_REPAIR_MINUTES * 60,
                      next_run_time=moment + timedelta(minutes=4))
    scheduler.add_job(_final_prematch, "interval", minutes=FINAL_PREMATCH_MINUTES, id="final_prematch",
                      max_instances=1, coalesce=True, misfire_grace_time=FINAL_PREMATCH_MINUTES * 60,
                      next_run_time=moment + timedelta(minutes=7))
    scheduler.add_job(_catalogue_refresh, "interval", hours=CATALOGUE_REFRESH_HOURS, id="catalogue_refresh",
                      max_instances=1, coalesce=True, misfire_grace_time=3600,
                      next_run_time=max(catalogue_next, moment + timedelta(minutes=8)))
    scheduler.add_job(_elo_refresh, "interval", hours=ELO_REFRESH_HOURS, id="elo_refresh",
                      max_instances=1, coalesce=True, misfire_grace_time=3600,
                      next_run_time=max(elo_next, moment + timedelta(minutes=12)))
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
    _stop = stop
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
    _lock.release()
    log.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())
