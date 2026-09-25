"""Historical backfill, one competition-season per request.

    python -m scripts.backfill seed                 # register the default units (no request)
    python -m scripts.backfill seed --league 141 --priority 70   # one named league, same seasons
    python -m scripts.backfill status               # progress and today's allowance (no request)
    python -m scripts.backfill run --yes --max 18   # spend at most 18, never the live reserve

Default units: Premier League first, then La Liga, Bundesliga, Serie A,
Ligue 1 and the Champions League, seasons 2024, 2023, 2022 - the seasons the
free plan was measured to serve. A unit the plan refuses is recorded as
refused with the provider's message and not retried.
"""

from __future__ import annotations

import argparse
import asyncio

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion.backfill import (
    BackfillReport,
    BackfillUnit,
    live_reserve,
    progress,
    run_backfill,
    seed_tasks,
)
from fbi.providers.api_football import ApiFootballProvider
from fbi.providers.api_football.build import build_client
from fbi.providers.quota import read_usage

DEFAULT_LEAGUES = [(39, 10), (140, 20), (78, 30), (135, 40), (61, 50), (2, 60)]
DEFAULT_SEASONS = [2024, 2023, 2022]


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.database.psycopg_url)


async def _run(conn: psycopg.Connection, max_requests: int, budget: int) -> BackfillReport:
    """One event loop for the whole run: the HTTP client is opened and closed in it."""
    provider = ApiFootballProvider(build_client())
    try:
        return await run_backfill(conn, provider, max_requests=max_requests, daily_budget=budget,
                                  prematch_windows=settings.odds.prematch_windows)
    finally:
        await provider.aclose()


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="backfill", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sd = sub.add_parser("seed")
    sd.add_argument("--league", type=int, action="append", default=[],
                    help="provider league id to seed instead of the defaults (repeatable)")
    sd.add_argument("--seasons", default=",".join(map(str, DEFAULT_SEASONS)),
                    help="comma-separated seasons (default: the three the free plan serves)")
    sd.add_argument("--priority", type=int, default=70, help="lower runs first (defaults use 10-60)")
    sub.add_parser("status")
    run = sub.add_parser("run")
    run.add_argument("--yes", action="store_true")
    run.add_argument("--max", type=int, default=6)
    args = parser.parse_args()

    budget = settings.provider_plan.effective_budget
    with _connect() as conn:
        if args.cmd == "seed":
            seasons = [int(s) for s in args.seasons.split(",") if s.strip()]
            leagues = [(lid, args.priority) for lid in args.league] or DEFAULT_LEAGUES
            units = [BackfillUnit(league, season, prio) for league, prio in leagues for season in seasons]
            kind = "named" if args.league else "default"
            print(f"added {seed_tasks(conn, units)} task(s); {len(units)} {kind} units")
            return 0
        if args.cmd == "status" or not args.yes:
            reserve = live_reserve(conn, prematch_windows=settings.odds.prematch_windows) + 10
            remaining = read_usage(conn, budget=budget).remaining
            print(f"tasks: {progress(conn)}")
            print(f"requests remaining today: {remaining}; live reserve: {reserve}; "
                  f"a run could spend {max(0, remaining - reserve)}")
            if args.cmd == "run":
                print("re-run with --yes to spend them")
            return 0
        report = asyncio.run(_run(conn, args.max, budget))
        print(f"reserve={report.reserve} remaining_before={report.remaining_before} allowance={report.allowance}")
        print(f"attempted={report.attempted} done={report.done} refused={report.refused} failed={report.failed} "
              f"fixtures={report.fixtures_written} results={report.results_written}")
        if report.deferred_reason:
            print("deferred:", report.deferred_reason)
        for n in report.notes:
            print(" -", n)
        print(f"tasks now: {progress(conn)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
