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
"""

from __future__ import annotations

import asyncio
import os
import signal

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.logging import new_run_id
from fbi.odds.partitions import ensure_partitions

log = structlog.get_logger("worker")

TICK_MINUTES = int(os.environ.get("FBI_ODDS_TICK_MINUTES", "15"))
FIXTURES_SYNC_HOURS = int(os.environ.get("FBI_FIXTURES_SYNC_HOURS", "12"))


async def _tick() -> None:
    """One scheduler tick: partitions, then the windows that are due.

    The planner decides what "due" means; a tick that finds nothing due costs
    zero provider calls. The ledger records every tick that did something.
    """
    from datetime import timedelta

    from scripts.capture_odds import _build_planner, _client, _connect, _upcoming

    from fbi.core.clock import now, today
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
            return
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
            return
        check = validate_plan(
            tasks, at=now(), budget_remaining=settings.api_football.daily_budget,
            known_fixture_ids={f.provider_fixture_id for f in fixtures},
        )
        if not check.ok:
            log.error("tick.plan_rejected", issues=check.issues)
            return
        provider = ApiFootballProvider(_client(), market_filter=settings.odds.market_filter)
        try:
            service = OddsCaptureService(conn, provider, planner, raw_root=settings.runtime.raw_store_dir)
            await service.capture(fixtures)
        finally:
            await provider.aclose()


async def _daily_fixtures_sync() -> None:
    """Refresh the fixture list for active competitions: one call per league."""
    from scripts.capture_odds import _client, _connect

    from fbi.ingestion.fixtures import sync_fixtures
    from fbi.providers.api_football import ApiFootballProvider

    new_run_id()
    with _connect() as conn:
        provider = ApiFootballProvider(_client())
        try:
            await sync_fixtures(conn, provider, horizon_days=7)
        finally:
            await provider.aclose()


async def main() -> None:
    configure_logging(settings.runtime.log_level)
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(_tick, "interval", minutes=TICK_MINUTES, id="odds_capture", max_instances=1)
    scheduler.add_job(_daily_fixtures_sync, "interval", hours=FIXTURES_SYNC_HOURS, id="fixtures_sync", max_instances=1)
    scheduler.start()
    log.info("worker.started", tick_minutes=TICK_MINUTES)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    scheduler.shutdown(wait=True)
    log.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())
