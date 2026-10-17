"""Carry raw payloads from one installation to another, lineage intact.

    python -m scripts.raw_transfer export --provider football_data --origin "cloud replica" --out fd.tar
    python -m scripts.raw_transfer import fd.tar --reason "football-data.co.uk unreachable here"   # verify only
    python -m scripts.raw_transfer import fd.tar --reason "..." --apply

Every file is verified (sha256 and the body hash its row names) before
anything is written; the rows arrive under a new `raw_transfer` ledger run
and keep the time the provider actually answered. See fbi.ops.raw_transfer.

Exit status: 0 good, 1 the archive does not verify, 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ops.raw_transfer import TransferError, export_payloads, import_payloads

REPO = Path(__file__).resolve().parents[1]


def _raw_root() -> Path:
    root = Path(settings.runtime.raw_store_dir)
    return root if root.is_absolute() else REPO / root


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="raw_transfer", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("--provider", required=True)
    ex.add_argument("--origin", required=True, help="who fetched these payloads, in words")
    ex.add_argument("--out", required=True)
    im = sub.add_parser("import")
    im.add_argument("archive")
    im.add_argument("--reason", required=True, help="why the payloads are not fetched here, in words")
    im.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        try:
            if args.cmd == "export":
                rep = export_payloads(conn, _raw_root(), Path(args.out), provider=args.provider, origin=args.origin)
                print(f"exported {rep.rows} payload(s) of {args.provider} to {rep.path} ({rep.bytes} bytes)")
                return 0
            imp = import_payloads(conn, _raw_root(), Path(args.archive), reason=args.reason, apply=args.apply)
        except TransferError as exc:
            print(f"REFUSED: {exc}")
            return 1
    print(f"{imp.rows_in_archive} payload(s) in the archive, every file verified")
    if not args.apply:
        print(f"would write {imp.files_written} file(s) ({imp.files_already_present} already present) - "
              "re-run with --apply")
        return 0
    print(f"ledger run {imp.run_id}: {imp.files_written} file(s) written, {imp.files_already_present} already "
          f"present; {imp.rows_inserted} index row(s) inserted, {imp.rows_already_indexed} already indexed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
