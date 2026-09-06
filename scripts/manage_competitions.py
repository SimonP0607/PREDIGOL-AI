"""Catalogue and activation of competitions.

    python -m scripts.manage_competitions import-legacy --dry-run
    python -m scripts.manage_competitions import-legacy
    python -m scripts.manage_competitions apply --dry-run
    python -m scripts.manage_competitions apply
    python -m scripts.manage_competitions list

import-legacy writes core.competitions / competition_seasons / market.bookmakers /
market.markets from the audited backups and prints a migration report.
apply reads config/competitions.yaml and is the only thing that ever flips
is_tracked. list shows what is known and what is active.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
from psycopg.rows import tuple_row

from fbi.catalog import activation, legacy_import
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging

REPO = Path(__file__).resolve().parent.parent
DEFAULT_LEGACY = REPO / "data" / "legacy"
DEFAULT_CONFIG = REPO / "config" / "competitions.yaml"


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.database.psycopg_url)


def cmd_import(args: argparse.Namespace) -> int:
    legacy_dir = Path(args.legacy_dir)
    conn = None if args.dry_run else _connect()
    try:
        report = legacy_import.run(conn, legacy_dir, dry_run=args.dry_run)
    finally:
        if conn is not None:
            conn.close()
    print(f"mode: {'DRY RUN' if args.dry_run else 'WRITE'}\n")
    print(report.summary_table())
    print("\nwritten:", report.written)
    if report.warnings:
        print(f"\n{len(report.warnings)} warning(s):")
        for w in report.warnings:
            print("  -", w)
    rejected = [r for r in report.rows if r.outcome == "rejected"]
    if rejected:
        print(f"\n{len(rejected)} rejected:")
        for r in rejected:
            print(f"  - {r.source} {r.key}: {r.reason}")
    if args.report:
        Path(args.report).write_text(report.to_json(), encoding="utf-8")
        print(f"\nfull report -> {args.report}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    toggles = activation.load_config(Path(args.config))
    with _connect() as conn:
        diff = activation.apply(conn, toggles, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
        active = activation.active_league_ids(conn)
    print(f"mode: {'DRY RUN' if args.dry_run else 'WRITE'}")
    print(f"enable : {diff.enabled or '-'}")
    print(f"disable: {diff.disabled or '-'}")
    print(f"unknown (not in catalogue, ignored): {diff.unknown or '-'}")
    print(f"unchanged: {diff.unchanged}")
    print(f"active after{' (would be)' if args.dry_run else ''}: {active if not args.dry_run else '(run without --dry-run)'}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    with _connect() as conn, conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT c.provider_league_id, c.name, c.country, c.type, c.competition_type, c.elo_weight, "
            "       c.is_tracked, count(s.id) AS seasons "
            "FROM core.competitions c LEFT JOIN core.competition_seasons s ON s.competition_id = c.id "
            "GROUP BY c.id ORDER BY c.is_tracked DESC, c.provider_league_id"
        )
        rows = cur.fetchall()
    print(f"{'id':>5}  {'name':<26} {'country':<12} {'fmt':<6} {'kind':<16} {'elo':>4}  tracked seasons")
    for lid, name, country, fmt, kind, elo, tracked, seasons in rows:
        print(f"{lid:>5}  {name[:26]:<26} {(country or '-')[:12]:<12} {fmt:<6} {kind:<16} {float(elo):>4.1f}  {'YES' if tracked else '.':<7} {seasons}")
    print(f"\n{len(rows)} known · {sum(1 for r in rows if r[6])} active")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manage_competitions", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("import-legacy")
    p.add_argument("--legacy-dir", default=str(DEFAULT_LEGACY))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--report", default=None, help="write the full JSON report here")
    p = sub.add_parser("apply")
    p.add_argument("--config", default=str(DEFAULT_CONFIG))
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    configure_logging(settings.runtime.log_level)
    return {"import-legacy": cmd_import, "apply": cmd_apply, "list": cmd_list}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
