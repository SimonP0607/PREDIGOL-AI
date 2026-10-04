"""Recover the kick-off changes recorded before core.fixture_kickoff_changes existed.

    python -m scripts.backfill_kickoff_changes --since 2026-09-20            # dry run
    python -m scripts.backfill_kickoff_changes --since 2026-09-20 --apply

Replays every stored /fixtures payload fetched since then, in fetch order (no provider
request) - see fbi.ingestion.kickoff_history.
"""

from __future__ import annotations

import argparse
from datetime import datetime

import psycopg

from fbi.core.config import settings
from fbi.ingestion.kickoff_history import backfill_kickoff_changes
from fbi.ingestion.payload_store import PayloadStore


def main() -> int:
    parser = argparse.ArgumentParser(prog="backfill_kickoff_changes", description=__doc__)
    parser.add_argument("--since", type=datetime.fromisoformat, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        report = backfill_kickoff_changes(conn, PayloadStore(settings.runtime.raw_store_dir), since=args.since,
                                          apply=args.apply)
    print(f"payloads {report.payloads}, refused {len(report.refused)}, changes {report.changes}, "
          f"rows {'written' if args.apply else 'that would be written'} {report.written}")
    for r in report.refused[:20]:
        print("  refused:", r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
