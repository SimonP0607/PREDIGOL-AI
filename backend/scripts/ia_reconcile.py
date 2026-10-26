"""Monthly reconciliation of the AI ledger with the Console (Plan Maestro IA, section 32; manual action 12).

Once a month, export the CSV of the Console's Cost page (platform.claude.com/cost: the workspace, "All Models", the month, the
export button) and run it here, on the server where the database is:

    python -m scripts.ia_reconcile --csv cost-oct.csv                           # one export with a workspace column
    python -m scripts.ia_reconcile --csv prod.csv=production --csv lab.csv=lab  # one export per workspace
    python -m scripts.ia_reconcile --csv cost-oct.csv --month 2026-10           # the file holds several months

It compares Claude's spend in ``ai.usage`` (and the analyst's runs, which the production workspace pays) with the CSV, workspace
by workspace and day by day (UTC days, as the Console's). More than 5 % apart is investigated; a difference under US$0.50 is
rounding. Exa has no Console: reconcile it with its invoice. Nothing is written: the report is JSON on the standard output,
with the CSV's SHA-256 so the evidence can be traced to the file.

``--cost-column``, ``--date-column`` and ``--workspace-column`` name a column when the export's spelling is not one the script
knows; ``--cost-divisor 100`` reads a figure in cents; ``--date-format`` gives a strptime format for an unusual date.

Exit status: 0 the month agrees, 1 something differs by more than the tolerance (see ``days_off``), 2 the CSV could not be read or
the database was not reached, 3 nothing was spent on either side.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import psycopg

from fbi.ai import reconcile

OK, DIFFERS, CANNOT, EMPTY = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_reconcile", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", action="append", required=True, metavar="FILE[=production|lab]",
                    help="an export of the Console's Cost page; =production or =lab fixes its workspace when it has no column")
    ap.add_argument("--month", help="YYYY-MM: the month to compare (default: the one the CSV holds)")
    ap.add_argument("--cost-column")
    ap.add_argument("--date-column")
    ap.add_argument("--workspace-column")
    ap.add_argument("--cost-divisor", default="1", help="100 when the figures are cents (default: %(default)s)")
    ap.add_argument("--date-format", action="append", help="a strptime format for the dates (repeatable)")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def parse_month(text: str | None) -> date | None:
    if text is None:
        return None
    try:
        year, month = text.split("-")
        return date(int(year), int(month), 1)
    except ValueError as exc:
        raise reconcile.CsvError(f"--month must look like 2026-10, not {text!r}") from exc


def split_scope(arg: str) -> tuple[str, str | None]:
    path, sep, scope = arg.rpartition("=")
    if sep and scope in reconcile.SCOPES:
        return path, scope
    return arg, None


def read(args: argparse.Namespace) -> reconcile.ConsoleCosts:
    try:
        divisor = Decimal(args.cost_divisor)
    except InvalidOperation as exc:
        raise reconcile.CsvError(f"--cost-divisor is not a number: {args.cost_divisor!r}") from exc
    if divisor <= 0:
        raise reconcile.CsvError("--cost-divisor must be positive")
    formats = tuple(args.date_format) if args.date_format else reconcile.DATE_FORMATS
    parts = []
    for arg in args.csv:
        path, scope = split_scope(arg)
        try:
            raw = Path(path).read_bytes()
        except OSError as exc:
            raise reconcile.CsvError(f"cannot read {path}: {exc.strerror}") from exc
        parts.append(reconcile.parse_console_csv(
            raw, month=parse_month(args.month), scope=scope, cost_column=args.cost_column, date_column=args.date_column,
            workspace_column=args.workspace_column, divisor=divisor, date_formats=formats))
    return reconcile.merge_all(parts)


def run(console: reconcile.ConsoleCosts, conn: psycopg.Connection[Any]) -> tuple[dict[str, Any], int]:
    """The report of one month and its exit status. Read only: nothing is written."""
    report = reconcile.reconcile(conn, console).as_json()
    return report, {reconcile.OK: OK, reconcile.INVESTIGATE: DIFFERS}.get(report["verdict"], EMPTY)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        console = read(args)
    except reconcile.CsvError as exc:
        sys.stderr.write(f"ia_reconcile: {exc}\n")
        return CANNOT
    from fbi.core.config import settings as platform

    try:
        with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
            report, code = run(console, conn)
    except psycopg.Error as exc:
        sys.stderr.write(f"ia_reconcile: the database could not be read ({type(exc).__name__})\n")
        return CANNOT
    sys.stdout.write(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
