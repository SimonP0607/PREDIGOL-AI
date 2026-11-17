"""The performance of the readers and of the sources, measured by the owner (IA-135, AD-K03): ``perf-v1`` under the protocol ``AD-K03``.
Read only.

    python -m scripts.ia_reader_performance report --since 2026-10-18 --until 2026-11-17 [--dry-run]

Each reader of the shadow against the rules on the same settled selections (the value against the close of what passes when its veto is
added, with its interval by Bogotá days and the Bonferroni correction; the attribution with Wilson intervals) and each source by type of
fact (the share held of the facts the decisions cited). ``--dry-run`` computes the evaluations after the match of the window without
writing them (``fbi.evalpass.store.dry_run``) when ``intel.selection_evaluations`` has no rows yet. The connection is read-only and each
statement is held to 95 s. Exit status: 0 a report, 2 it cannot run (a bad day or option).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Final

import psycopg

from fbi.ai.calendar import day_bounds
from fbi.core.clock import now
from fbi.evalpass import performance, performance_reads, store

READ_ONLY: Final = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000"
OK, CANNOT = 0, 2


def bounds(since: date, until: date, *, at: datetime) -> tuple[datetime, datetime]:
    if until <= since:
        raise ValueError("--until must be after --since")
    return day_bounds(since)[0], min(day_bounds(until)[0], at)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_reader_performance", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("report",))
    ap.add_argument("--since", required=True, type=date.fromisoformat)
    ap.add_argument("--until", required=True, type=date.fromisoformat)
    ap.add_argument("--dry-run", action="store_true", help="compute the evaluations of the window instead of reading the kept ones")
    ap.add_argument("--dsn", default=None)
    return ap


def run(conn: psycopg.Connection[Any], *, start: datetime, end: datetime, dry_run: bool) -> dict[str, Any]:
    judged = performance_reads.stances(conn, start=start, end=end)
    if dry_run:
        evs, _ = store.dry_run(conn, start=start, end=end)
        cited = performance_reads.cited_from_evaluations(conn, evs)
    else:
        cited = performance_reads.cited(conn, start=start, end=end)
    return performance.report(judged, cited, period={"start": start.isoformat(), "end": end.isoformat(),
                                                     "evaluations": "dry_run" if dry_run else "intel.selection_evaluations"})


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        start, end = bounds(args.since, args.until, at=now())
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return CANNOT
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=READ_ONLY) as conn:
        doc = run(conn, start=start, end=end, dry_run=args.dry_run)
        conn.rollback()
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
