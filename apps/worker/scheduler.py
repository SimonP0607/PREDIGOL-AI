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


async def _tick() -> None:
    from scripts.capture_odds import _build_planner, _connect, _provider, _upcoming

    from fbi.core.clock import today
    from fbi.odds.capture import OddsCaptureService

    new_run_id()
    with _connect() as conn:
        ensure_partitions(conn, today=today())
        fixtures = _upcoming(conn, 96)
        if not fixtures:
            log.info("tick.nothing_scheduled")
            return
        provider = _provider()
        try:
            service = OddsCaptureService(
                conn, provider, _build_planner(), raw_root=settings.runtime.raw_store_dir
            )
            await service.capture(fixtures)
        finally:
            await provider.aclose()


async def main() -> None:
    configure_logging(settings.runtime.log_level)
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(_tick, "interval", minutes=TICK_MINUTES, id="odds_capture", max_instances=1)
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
