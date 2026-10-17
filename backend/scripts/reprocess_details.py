"""Re-derive match-detail state from the raw payloads already on disk.

    python -m scripts.reprocess_details                # verify only, write nothing
    python -m scripts.reprocess_details --apply
    python -m scripts.reprocess_details --apply --limit 50
    python -m scripts.reprocess_details --venues [--apply]   # fixtures' venue name/city from their own payload

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
from fbi.ops.reprocess import (
    derive_coverage_from_stored_detail,
    derive_identity_from_stored_detail,
    repair_payload_lineage,
    reprocess_fixture_details,
    reprocess_fixture_venues,
    reprocess_results,
    reprocess_teams,
)

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
    parser.add_argument("--derive-only", action="store_true",
                        help="skip the replay; only fill coverage and identity from what is normalized")
    parser.add_argument("--fix-lineage", action="store_true",
                        help="move derived rows' fetch time back to the payload's own, for the "
                             "rows written before the writers started asking the index")
    parser.add_argument("--results", action="store_true",
                        help="re-derive the 90-minute score from score.fulltime in the stored "
                             "payloads: fixes the rows where extratime was the running total")
    parser.add_argument("--teams", action="store_true",
                        help="normalise the /teams payloads that were only ever stored as bytes")
    parser.add_argument("--venues", action="store_true",
                        help="fill core.fixtures.venue_name/venue_city from each fixture's own source payload")
    args = parser.parse_args()

    if args.venues:
        with psycopg.connect(settings.database.psycopg_url) as conn:
            rep = reprocess_fixture_venues(conn, _raw_root(), apply=args.apply, limit=args.limit,
                                           verify_hashes=not args.skip_hash_check)
        print(f"{rep.payloads_seen} source payload(s) read, {rep.payloads_applied} naming a venue, "
              f"{rep.fixtures_touched} fixture(s) named a venue, {rep.coverage_rows} row(s) written")
        for problem in rep.problems[:10]:
            print(f"  {problem}")
        if not args.apply:
            print("re-run with --apply")
        return 1 if rep.payloads_missing_file or rep.payloads_not_rehashing else 0

    if args.derive_only:
        if not args.apply:
            print("--derive-only writes rows: add --apply")
            return 2
        with psycopg.connect(settings.database.psycopg_url) as conn:
            coverage = derive_coverage_from_stored_detail(conn)
            identity = derive_identity_from_stored_detail(conn)
        print(f"{sum(coverage.values())} coverage row(s) derived: "
              + ", ".join(f"{k} {v}" for k, v in coverage.items()))
        print("identity derived: " + ", ".join(f"{k} {v}" for k, v in identity.items()))
        return 0

    if args.fix_lineage:
        with psycopg.connect(settings.database.psycopg_url) as conn:
            counts = repair_payload_lineage(conn, apply=args.apply)
        total = sum(counts.values())
        if not counts:
            print("no row is dated after the payload it names")
            return 0
        for rel, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  core.{rel:<26} {n:>8}")
        print(f"{total} row(s) in {len(counts)} relation(s)"
              + ("" if args.apply else " - re-run with --apply"))
        return 0

    if args.results:
        with psycopg.connect(settings.database.psycopg_url) as conn:
            rep = reprocess_results(conn, _raw_root(), apply=args.apply, limit=args.limit,
                                    verify_hashes=not args.skip_hash_check)
        print(f"{rep.payloads_seen} /fixtures payload(s), {rep.payloads_applied} with scores, "
              f"{rep.fixtures_touched} result(s) written")
        print(f"provider score parts disagreeing (fulltime + extratime != goals): "
              f"{rep.issues_opened}")
        for problem in rep.problems[:10]:
            print(f"  {problem}")
        if not args.apply:
            print("re-run with --apply")
        return 1 if rep.payloads_missing_file or rep.payloads_not_rehashing else 0

    if args.teams:
        with psycopg.connect(settings.database.psycopg_url) as conn:
            rep = reprocess_teams(conn, _raw_root(), apply=args.apply,
                                  verify_hashes=not args.skip_hash_check)
        print(f"{rep.payloads_seen} /teams payload(s), {rep.payloads_applied} usable, "
              f"{rep.fixtures_touched} team(s) named, {rep.coverage_rows} row(s) written")
        for problem in rep.problems[:10]:
            print(f"  {problem}")
        if not args.apply:
            print("re-run with --apply")
        return 1 if rep.payloads_missing_file or rep.payloads_not_rehashing else 0

    with psycopg.connect(settings.database.psycopg_url) as conn:
        report = reprocess_fixture_details(conn, _raw_root(), apply=args.apply, limit=args.limit,
                                           verify_hashes=not args.skip_hash_check)
        derived = derive_coverage_from_stored_detail(conn) if args.apply else {}

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
    if derived:
        print(f"{sum(derived.values())} further coverage row(s) derived from detail already normalized "
              "(a payload fetched twice keeps its first index time, so its replay reads as stale)")
    return 1 if report.payloads_missing_file or report.payloads_not_rehashing else 0


if __name__ == "__main__":
    sys.exit(main())
