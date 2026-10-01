"""Retire old live-odds partitions to Parquet.

    python scripts/live_retention.py plan                 # what would go, writes nothing
    python scripts/live_retention.py archive              # write the Parquet, keep the tables
    python scripts/live_retention.py archive --drop       # ...and drop them once verified
    python scripts/live_retention.py verify               # check what is on disk

The live series is the one table in this database that grows with the clock
rather than with the football that exists, so it is the one that needs retiring.
A partition is dropped only after its archive has been written, checksummed and
read back with a matching row count - an archive nobody has restored is a hope,
not a backup. Zero provider requests.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import psycopg

from fbi.core.clock import today
from fbi.core.config import settings
from fbi.odds.live_archive import (
    DEFAULT_RETENTION_MONTHS,
    archive,
    plan,
    verify,
)

ARCHIVE_DIR = pathlib.Path("data/archive/live")


def _mb(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB"


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.database.psycopg_url)


def _plan(months: int) -> int:
    with _connect() as conn:
        p = plan(conn, today=today(), retention_months=months)
    print(f"keeping anything from {p.cutoff} onwards ({months} months)\n")
    print(f"{'partition':<30} {'rows':>10} {'size':>10}  ")
    for part in p.keep:
        print(f"{part.name:<30} {part.rows:>10,} {_mb(part.bytes):>10}  keep")
    for part in p.retire:
        print(f"{part.name:<30} {part.rows:>10,} {_mb(part.bytes):>10}  RETIRE")
    if not p.retire:
        print("\nnothing is old enough to retire")
        return 0
    print(f"\n{len(p.retire)} partition(s), {p.rows_to_retire:,} rows, "
          f"{_mb(p.bytes_to_retire)} would leave Postgres")
    print("re-run with `archive --drop` to do it")
    return 0


def _archive(months: int, drop: bool) -> int:
    with _connect() as conn:
        p = plan(conn, today=today(), retention_months=months)
        if not p.retire:
            print("nothing is old enough to retire")
            return 0
        failures = 0
        for part in p.retire:
            result = archive(conn, part, ARCHIVE_DIR, drop=drop)
            state = (
                "dropped" if result.dropped
                else "verified, kept" if result.verified
                else "FAILED VERIFICATION, kept"
            )
            ratio = (
                f"{part.bytes / result.bytes:.1f}x smaller"
                if result.bytes else "empty"
            )
            print(f"{part.name}: {result.rows_written:,} rows -> "
                  f"{_mb(result.bytes)} parquet ({ratio})  [{state}]")
            if not result.verified:
                failures += 1
    return 1 if failures else 0


def _verify() -> int:
    problems = verify(ARCHIVE_DIR)
    if not problems:
        print(f"{ARCHIVE_DIR}: every archive matches its checksum")
        return 0
    for problem in problems:
        print(f"  {problem}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--months", type=int, default=DEFAULT_RETENTION_MONTHS,
                    help="how many months of live history to keep in Postgres")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="what would be retired (writes nothing)")
    a = sub.add_parser("archive", help="write the Parquet archives")
    a.add_argument("--drop", action="store_true",
                   help="drop each partition once its archive is verified")
    sub.add_parser("verify", help="check the archives against their checksums")
    args = ap.parse_args()

    if args.cmd == "plan":
        return _plan(args.months)
    if args.cmd == "archive":
        return _archive(args.months, args.drop)
    return _verify()


if __name__ == "__main__":
    raise SystemExit(main())
