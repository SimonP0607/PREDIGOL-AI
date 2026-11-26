"""The counters of experiment EXP-E8 (RP-9.8, ``research-yield-v1``) from the command line. Reading only.

    python -m scripts.ia_exp_e8_counters                 # the last 30 days, in Spanish
    python -m scripts.ia_exp_e8_counters --days 14 --json

Confirmed web facts per match and per dollar of the research (search and extraction), all together and by level of the research order, for the
share in force; and how far the counters are from the 300 matches per criterion the protocol asks for. It compares no criterion, changes no
budget and turns nothing on. ``--dsn`` overrides the database (the worker's own by default). Exit status: 0 done, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai import research_yield

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"


def build(conn: psycopg.Connection[Any], *, now: datetime, days: int) -> dict[str, Any]:
    """The counters of the ``days`` days before ``now``. The connection is the caller's and is only read."""
    since = now - timedelta(days=days)
    return research_yield.report(
        research_yield.read(conn, since=since, until=now), since=since, until=now
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="ia_exp_e8_counters", description=(__doc__ or "").split("\n\n")[0]
    )
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    if args.days < 1:
        ap.error("--days must be at least 1")
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        doc = build(conn, now=datetime.now(UTC), days=args.days)
    if args.as_json:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write("\n".join(research_yield.lines(doc)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
