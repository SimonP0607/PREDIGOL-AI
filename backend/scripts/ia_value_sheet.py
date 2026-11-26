"""The value sheet of each AI process (RP-12.1, ``value-sheet-v1``) from the command line. Reading only.

    python -m scripts.ia_value_sheet                       # the last 7 and 30 days, in Spanish
    python -m scripts.ia_value_sheet --days 14 --json      # one window, the whole sheet as JSON

Per process: its cost (from the ledger's capability report), what it produced, what part of that was useful by the unit written in advance
(``fbi.ai.value_sheet.PROCESSES``), the cost per unit and per useful unit with the interval of the useful share, and, for the review, whether
what it rejected did worse than what it let through. A process with no measurable useful unit is marked as such. It turns nothing off and moves
no budget. ``--dsn`` overrides the database (the worker's own by default). Exit status: 0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai import costs_v3, r4_compare, r4_readers, value_sheet, value_sheet_readers

DEFAULT_DAYS = (7, 30)


def build(conn: psycopg.Connection[Any], *, now: datetime, days: int) -> dict[str, Any]:
    """The sheet of the ``days`` days before ``now``. The connection is the caller's and is only read."""
    since, until = now - timedelta(days=days), now
    cap = costs_v3.attribution(conn, since, until)
    reviews = r4_readers.reviews(conn, since=since, until=until)
    r4 = r4_compare.report(reviews, since=since, until=until)
    counts = value_sheet_readers.counts(conn, since=since, until=until)
    doc = value_sheet.sheet(cap, r4, counts, days=days)
    return {"since": since.isoformat(), "until": until.isoformat(), **doc}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_value_sheet", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--days", type=int, action="append", help="window in days (repeat for several); default 7 and 30")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    windows = tuple(args.days) if args.days else DEFAULT_DAYS
    if any(d < 1 for d in windows):
        ap.error("--days must be at least 1")
    from fbi.core.config import settings as platform

    options = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"
    docs: list[dict[str, Any]] = []
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=options) as conn:
        now = datetime.now(UTC)
        for d in windows:
            docs.append(build(conn, now=now, days=d))
            conn.rollback()
    if args.as_json:
        sys.stdout.write(json.dumps(docs, indent=1, default=str, ensure_ascii=False) + "\n")
    else:
        for doc in docs:
            sys.stdout.write("\n".join(value_sheet.lines(doc)) + "\n\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
