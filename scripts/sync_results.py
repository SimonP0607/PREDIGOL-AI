"""Bring played fixtures to their real state.

    python -m scripts.sync_results            # announce the cost, spend nothing
    python -m scripts.sync_results --yes
    python -m scripts.sync_results --yes --lookback-days 1

Cost: one /fixtures request per calendar day, today included. The goals are in
that payload already, so this is the same price as a fixtures sync - and on the
free plan only about a day back is served at all, which is why the default is 1
and anything larger is announced as likely to be refused.
"""

from __future__ import annotations

import argparse
import asyncio

import psycopg
import structlog

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion.results import PLAN_LOOKBACK_LIMIT, stale_fixtures, sync_results
from fbi.providers.api_football import ApiFootballProvider
from fbi.providers.api_football.build import build_client

log = structlog.get_logger("sync_results")


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.database.psycopg_url)


async def _run(lookback_days: int, confirm: bool) -> int:
    with _connect() as conn:
        stale = stale_fixtures(conn)
        print(f"fixtures past kick-off still marked as not started: {len(stale)}")
        for s in stale[:10]:
            print(f"  {s.provider_fixture_id}  {s.kickoff_at.isoformat()}  {s.status_short}")
        cost = lookback_days + 1
        print(f"this will spend exactly {cost} provider request(s).")
        if lookback_days > PLAN_LOOKBACK_LIMIT:
            print(
                f"WARNING: the free plan serves about {PLAN_LOOKBACK_LIMIT} day(s) back; "
                "the rest will be issued and refused."
            )
        if not confirm:
            print("re-run with --yes to spend them.")
            return 0

        provider = ApiFootballProvider(build_client())
        try:
            counters = await sync_results(conn, provider, lookback_days=lookback_days)
        finally:
            await provider.aclose()

        print(
            f"requests={counters.api_calls} payloads={counters.payloads_stored} "
            f"finished seen={counters.rows_normalized} fixtures updated={counters.rows_updated} "
            f"results written={counters.rows_inserted} errors={len(counters.errors)} "
            f"status={counters.status}"
        )
        for e in counters.errors:
            print("  -", e)
        remaining = stale_fixtures(conn)
        print(f"still stale after the sync: {len(remaining)}")
        return 1 if counters.status == "failed" else 0


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="sync_results", description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=PLAN_LOOKBACK_LIMIT)
    parser.add_argument("--yes", action="store_true", help="actually spend the requests")
    args = parser.parse_args()
    return asyncio.run(_run(args.lookback_days, args.yes))


if __name__ == "__main__":
    raise SystemExit(main())
