"""The agent evaluation bench (``eval-bench-v1``, ``fbi.ai.eval_bench``) from the command line: per agent, version and Bogotá day, what the stored
runs of the shadow say - runs, valid on the first attempt, invalid by code, retries, cost, tokens, latency, and over the range the coverage of the
sample, the stability of repeated inputs and, once the attribution exists, the precision of the signals and the cost of a useful one.

    python -m scripts.ia_eval_bench report --from 2026-11-01 --to 2026-11-14
    python -m scripts.ia_eval_bench report --from 2026-11-01 --to 2026-11-14 --agent council --json

It reads only: no model, no search, no row written. A figure the rows cannot support is omitted and the report says why. ``--dsn`` overrides the
database (the worker's own by default).

Exit status: 0 done, 2 could not run (usage error).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from fbi.ai import eval_bench

COMMANDS = ("report",)
OK, CANNOT = 0, 2


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_eval_bench", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--from", dest="first", required=True, metavar="YYYY-MM-DD", help="the first Bogotá day of the range")
    ap.add_argument("--to", dest="last", required=True, metavar="YYYY-MM-DD", help="the last Bogotá day of the range (included)")
    ap.add_argument("--agent", help="one agent only (match, council, stats...)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the whole report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run(conn: psycopg.Connection[Any], *, first: date, last: date, at: datetime, agent: str | None = None) -> tuple[dict[str, Any], int]:
    """The report (JSON-ready, with its lines) and the exit status. Reads only; the connection is the caller's."""
    try:
        rep = eval_bench.report(conn, first=first, last=last, at=at, agent=agent)
    except ValueError as exc:
        return {"error": str(exc)}, CANNOT
    doc = rep.as_json()
    doc["lines"] = rep.lines()
    return doc, OK


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        first, last = parse_day(args.first), parse_day(args.last)
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        doc, code = run(conn, first=first, last=last, at=datetime.now(UTC), agent=args.agent)
        conn.rollback()  # it only read
    if not args.as_json and "lines" in doc:
        sys.stdout.write("\n".join(doc["lines"]) + "\n")
    else:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    if code == CANNOT and "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
