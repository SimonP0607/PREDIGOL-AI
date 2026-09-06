"""Sync upcoming fixtures for the ACTIVE competitions.

    python -m scripts.sync_fixtures --horizon-days 7

Cost: exactly one /fixtures call per active competition-season. Says so
before it spends them.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion.fixtures import active_seasons, sync_fixtures
from fbi.ingestion.payload_store import PayloadStore
from fbi.providers.api_football import ApiFootballClient, ApiFootballProvider


async def _main(horizon_days: int, yes: bool) -> int:
    with psycopg.connect(settings.database.psycopg_url) as conn:
        seasons = active_seasons(conn)
        print(f"active competition-seasons: {len(seasons)}")
        for s in seasons:
            print(f"  league {s.provider_league_id:<5} season {s.season}  {s.name}")
        print(f"this will spend exactly {len(seasons)} provider request(s).")
        if not seasons:
            return 0
        if not yes:
            print("re-run with --yes to spend them.")
            return 0
        client = ApiFootballClient(settings.api_football, PayloadStore(settings.runtime.raw_store_dir))
        provider = ApiFootballProvider(client)
        try:
            counters = await sync_fixtures(conn, provider, horizon_days=horizon_days)
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
    parser.add_argument("--horizon-days", type=int, default=7)
    parser.add_argument("--yes", action="store_true", help="actually spend the requests")
    args = parser.parse_args(argv)
    configure_logging(settings.runtime.log_level)
    return asyncio.run(_main(args.horizon_days, args.yes))


if __name__ == "__main__":
    sys.exit(main())
