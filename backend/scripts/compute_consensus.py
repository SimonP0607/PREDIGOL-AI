"""Rebuild the live market consensus from stored snapshots.

    python -m scripts.compute_consensus            # what exists and what would be written
    python -m scripts.compute_consensus --apply    # write missing consensus rows (idempotent)

The worker computes the consensus after every capture; this is for a backfill
after a code change, or to check. One consensus per (fixture, payload): the
books one provider response contained, as of that response's capture time.
Zero provider requests.
"""

from __future__ import annotations

import argparse

import psycopg
from psycopg.rows import tuple_row

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.market.consensus import recompute_from_snapshots


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="compute_consensus", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT count(DISTINCT (fixture_id, payload_hash)), count(*) FROM market.odds_snapshots")
            payloads, snapshots = cur.fetchone() or (0, 0)
            cur.execute("SELECT count(*), count(DISTINCT fixture_id) FROM market.market_consensus")
            rows, fixtures = cur.fetchone() or (0, 0)
        print(f"snapshots: {snapshots} in {payloads} captured payload(s)")
        print(f"consensus: {rows} row(s) for {fixtures} fixture(s)")
        if not args.apply:
            print("dry run - nothing written (use --apply)")
            return 0
        seen, written = recompute_from_snapshots(conn)
        conn.commit()
        print(f"payloads processed: {seen}; consensus rows written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
