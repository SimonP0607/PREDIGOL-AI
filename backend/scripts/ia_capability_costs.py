"""Every dollar of the month given to one capability (IA-137, AD-K05), from the command line. Reading only.

    python -m scripts.ia_capability_costs                          # this Bogotá month, as the cost panel shows it (``attribution``)
    python -m scripts.ia_capability_costs --from 2026-11-01 --to 2026-11-16

The report says, per capability, what it spent, its share of the month, how many of its calls went by Message Batch, how much of its
input came from the prompt cache and how much it paid twice for the same input; and the rows no capability claims (``sin_capacidad``).
It checks the rows against the ledgers' own sums (``reconciles``) and says whether the month is ``complete``. ``--dsn`` overrides the
database (the worker's own by default). Exit status: 0 complete, 1 not complete (rows without a capability, or a difference), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import psycopg

from fbi.ai import costs_v3
from fbi.ai.calendar import day_start, local_day, month_start


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_capability_costs", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--from", dest="start", type=date.fromisoformat)
    ap.add_argument("--to", dest="end", type=date.fromisoformat, help="exclusive")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    now = datetime.now(UTC)
    since = day_start(args.start) if args.start else day_start(month_start(local_day(now)))
    until = day_start(args.end) if args.end else now + timedelta(seconds=1)
    if until <= since:
        ap.error("--to must be after --from")
    from fbi.core.config import settings as platform

    options = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=options) as conn:
        doc = costs_v3.attribution(conn, since, until)
        conn.rollback()
    doc = {"since": since.isoformat(), "until": until.isoformat(), **doc}
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    return 0 if doc.get("complete") else 1


__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
