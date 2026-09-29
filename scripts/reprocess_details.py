"""Re-derive match-detail state from the raw payloads already on disk.

    python -m scripts.reprocess_details                # verify only, write nothing
    python -m scripts.reprocess_details --apply
    python -m scripts.reprocess_details --apply --limit 50

No provider request is made: every /fixtures?ids= payload we have ever fetched is
still in the raw store, so per-fixture detail coverage (revision 0028) and the
quality issues the old code dropped in silence can be established exactly, from
what the provider actually sent.

Commits after every payload, so an interrupted run resumes rather than restarts.

Exit status: 0 good, 1 the raw store disagrees with its index, 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ops.reprocess import reprocess_fixture_details

REPO = Path(__file__).resolve().parents[1]


def _raw_root() -> Path:
    root = Path(settings.runtime.raw_store_dir)
    return root if root.is_absolute() else REPO / root


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="reprocess_details", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--skip-hash-check", action="store_true",
                        help="faster, and gives up the guarantee that the bytes are unchanged")
    args = parser.parse_args()

    with psycopg.connect(settings.database.psycopg_url) as conn:
        report = reprocess_fixture_details(conn, _raw_root(), apply=args.apply, limit=args.limit,
                                           verify_hashes=not args.skip_hash_check)

    print(f"{report.payloads_seen} detail payload(s) in the raw index, {report.payloads_applied} usable")
    if report.payloads_missing_file or report.payloads_not_rehashing:
        print(f"  MISSING FILE: {report.payloads_missing_file}   "
              f"DOES NOT RE-HASH: {report.payloads_not_rehashing}")
    for problem in report.problems[:10]:
        print(f"  {problem}")
    if not args.apply:
        print(f"would touch {report.fixtures_touched} fixture(s) - re-run with --apply")
        return 1 if report.payloads_missing_file or report.payloads_not_rehashing else 0
    print(f"fixtures touched {report.fixtures_touched}, coverage rows {report.coverage_rows}, "
          f"issues opened {report.issues_opened} (+{report.issues_seen_again} seen again), "
          f"stale skips {report.skipped_stale}")
    return 1 if report.payloads_missing_file or report.payloads_not_rehashing else 0


if __name__ == "__main__":
    sys.exit(main())
