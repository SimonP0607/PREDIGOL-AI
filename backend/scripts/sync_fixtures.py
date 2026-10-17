"""Sync upcoming fixtures for the ACTIVE competitions.

    python -m scripts.sync_fixtures                       # announce the cost, spend nothing
    python -m scripts.sync_fixtures --yes
    python -m scripts.sync_fixtures --yes --strategy date --horizon-days 8

Cost, stated before it is spent:
    league  one /fixtures call per active competition-season
    date    one /fixtures call per calendar day in the horizon
    auto    league first; falls back to date if the provider refuses on plan
            grounds (a refused call does not count against the daily quota)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion.fixtures import SyncStrategy, active_seasons, sync_fixtures
from fbi.odds.horizons import DEFAULT_HORIZON_DAYS
from fbi.providers.api_football import ApiFootballProvider
from fbi.providers.api_football.build import build_client


async def _main(horizon_days: int, yes: bool, strategy: SyncStrategy) -> int:
    with psycopg.connect(settings.database.psycopg_url) as conn:
        seasons = active_seasons(conn)
        print(f"active competition-seasons: {len(seasons)}")
        for s in seasons:
            print(f"  league {s.provider_league_id:<5} season {s.season}  {s.name}")
        if not seasons:
            print("nothing tracked: enable a league in config/competitions.yaml and run `manage_competitions apply`.")
            return 0
        if strategy is SyncStrategy.LEAGUE:
            cost = f"exactly {len(seasons)}"
        elif strategy is SyncStrategy.DATE:
            cost = f"exactly {horizon_days + 1}"
        else:
            cost = f"{len(seasons)}, or {len(seasons)} + {horizon_days + 1} if the plan refuses league+season"
        print(f"strategy: {strategy}")
        print(f"this will spend {cost} provider request(s).")
        if not yes:
            print("re-run with --yes to spend them.")
            return 0
        client = build_client()  # persistent daily budget, shared with every other script
        provider = ApiFootballProvider(client)
        try:
            counters = await sync_fixtures(
                conn, provider, horizon_days=horizon_days, strategy=strategy
            )
        finally:
            await provider.aclose()
        print(
            f"requests={counters.api_calls} payloads={counters.payloads_stored} "
            f"fixtures seen={counters.rows_normalized} inserted={counters.rows_inserted} "
            f"updated={counters.rows_updated} errors={len(counters.errors)} status={counters.status}"
        )
        for e in counters.errors:
            print("  -", e)
        return 1 if counters.status == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sync_fixtures", description=__doc__)
    parser.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS,
                        help=f"default {DEFAULT_HORIZON_DAYS}: prices were measured at "
                             "T-18.2 days, and under --strategy league a wider horizon "
                             "costs nothing")
    parser.add_argument("--yes", action="store_true", help="actually spend the requests")
    parser.add_argument(
        "--strategy",
        type=SyncStrategy,
        choices=list(SyncStrategy),
        default=SyncStrategy.AUTO,
        help="auto (default) | league | date",
    )
    args = parser.parse_args(argv)
    configure_logging(settings.runtime.log_level)
    return asyncio.run(_main(args.horizon_days, args.yes, args.strategy))


if __name__ == "__main__":
    sys.exit(main())
