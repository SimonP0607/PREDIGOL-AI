"""Re-normalise stored /fixtures payloads. Spends zero provider requests.

    python -m scripts.replay_raw            # report what would change, write nothing
    python -m scripts.replay_raw --apply    # write it

Every file is verified against its indexed hash before it is read, and writes
are monotonic on the payload's fetch time. See fbi.ingestion.replay.
"""

from __future__ import annotations

import argparse
import asyncio

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion.payload_store import PayloadStore
from fbi.ingestion.replay import replay_fixture_payloads
from fbi.providers.api_football import ApiFootballProvider
from fbi.providers.api_football.build import build_client


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="replay_raw", description=__doc__)
    parser.add_argument("--apply", action="store_true", help="commit the changes (default: dry run)")
    args = parser.parse_args()

    # The provider is used only for its pure parse_* methods: no request is made.
    provider = ApiFootballProvider(build_client())
    try:
        with psycopg.connect(settings.database.psycopg_url) as conn:
            report = replay_fixture_payloads(
                conn, provider, PayloadStore(settings.runtime.raw_store_dir), apply=args.apply
            )
    finally:
        asyncio.run(provider.aclose())
    print(
        f"payloads considered={report.payloads_considered} applied={report.payloads_applied} "
        f"refused={len(report.payloads_refused)}"
    )
    print(
        f"fixtures inserted={report.fixtures_inserted} updated={report.fixtures_updated} "
        f"results written={report.results_written}"
    )
    for r in report.payloads_refused:
        print("  refused:", r)
    print("COMMITTED" if report.committed else "dry run - nothing written (use --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
