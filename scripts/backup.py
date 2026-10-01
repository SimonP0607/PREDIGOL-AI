"""Back up the database and the raw payload store, and prove the backup restores.

    python -m scripts.backup create [--label L]          # data/backups/<UTC stamp>/: db.dump, raw.tar, manifest.json
    python -m scripts.backup verify <folder>             # re-hash the two files against the manifest
    python -m scripts.backup restore-test <folder>       # restore into a scratch database and compare everything
    python -m scripts.backup create --restore-test       # both, in one go

The restore test REFUSES while the worker is beating. It held the live database
for 19,123 seconds once - five hours and twenty-one minutes - and the capture
stopped for all of it; an in-play price missed cannot be re-fetched, because
/odds/live keeps no history. Stop the worker, run it, start the worker, or pass
--force on a machine that is not serving live capture.

The restore test creates its own database (fbi_restore_<random>) on the same
server, restores into it, compares every table's row count and content
fingerprint with the manifest, re-hashes every archived raw file, checks the
restored payload index against the files, and drops the scratch database
(--keep to inspect it). It never writes to the application database.

Exit status: 0 good, 1 a check failed, 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ops.backup import RestoreReport, create_backup, restore_test, verify_files

REPO = Path(__file__).resolve().parents[1]
BACKUP_DIR = REPO / "data" / "backups"


def _say(msg: str) -> None:
    print(msg, flush=True)


def _raw_root() -> Path:
    root = Path(settings.runtime.raw_store_dir)
    return root if root.is_absolute() else REPO / root


def _print_restore(report: RestoreReport) -> None:
    for c in report.checks:
        _say(f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.detail}")
    _say(f"restore test {'PASSED' if report.passed else 'FAILED'} in {report.seconds:.1f}s "
         f"(scratch database {report.scratch_db})")


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="backup", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    cr = sub.add_parser("create")
    cr.add_argument("--label", default="")
    cr.add_argument("--restore-test", action="store_true")
    cr.add_argument("--force", action="store_true",
                    help="run the restore test even while the worker is beating; "
                         "it holds this database for hours and the capture tick "
                         "needs it, so only on a machine that is not serving live "
                         "capture")
    cr.add_argument("--keep", action="store_true")
    cr.add_argument("--out", default=str(BACKUP_DIR))
    sub.add_parser("verify").add_argument("folder")
    rt = sub.add_parser("restore-test")
    rt.add_argument("--force", action="store_true",
                    help="run even while the worker is beating; see create --force")
    rt.add_argument("folder")
    rt.add_argument("--keep", action="store_true")
    for p in (cr, rt):
        p.add_argument("--admin-url", default="", help="DSN of the same server with CREATEDB (default: the configured "
                                                       "role on database 'postgres')")
    args = parser.parse_args()
    db_url = settings.database.psycopg_url
    if args.cmd == "verify":
        problems = verify_files(Path(args.folder))
        _say("; ".join(problems) if problems else "dump and raw archive match the manifest")
        return 1 if problems else 0
    admin = args.admin_url or db_url.rsplit("/", 1)[0] + "/postgres"
    if args.cmd == "create":
        rep = create_backup(db_url, _raw_root(), Path(args.out), label=args.label)
        m = rep.manifest
        _say(f"backup {rep.folder.relative_to(REPO) if rep.folder.is_relative_to(REPO) else rep.folder} "
             f"in {rep.seconds:.1f}s")
        _say(f"  database {m['database']} at revision {m['alembic_revision']}: {len(m['tables'])} tables, "
             f"{m['rows_total']} rows; dump {m['files']['db.dump']['bytes']} bytes")
        _say(f"  raw store: {m['raw_store']['files']} files, {m['raw_store']['bytes']} bytes; archive "
             f"{m['files']['raw.tar']['bytes']} bytes")
        if m["changed_during_dump"]:
            _say(f"  NOTE: written to during the dump: {', '.join(m['changed_during_dump'])} - the manifest "
                 "describes the state after; the dump is one consistent snapshot in between")
        if not args.restore_test:
            return 0
        report = restore_test(rep.folder, admin, keep=args.keep, force=args.force,
                              app_url=db_url)
        _print_restore(report)
        return 0 if report.passed else 1
    report = restore_test(Path(args.folder), admin, keep=args.keep, force=args.force,
                          app_url=db_url)
    _print_restore(report)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
