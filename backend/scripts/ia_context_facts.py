"""How many facts of a window follow the one schema of a context fact, by kind and category (RP-4.1). Reading only.

    python -m scripts.ia_context_facts                 # the last 7 days, in Spanish
    python -m scripts.ia_context_facts --days 30 --json

Counts the facts written under ``context-fact-v1`` (complete by construction) apart from the ones written before, by kind and by category (the category
is derived from the state: ``fbi.ai.factor_schema.category_of``), and says which of the six new kinds have no fact yet. It writes nothing and
turns nothing on. ``--dsn`` overrides the database (the worker's own by default).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import psycopg

from fbi.ai import factor_counts, value_sheet_readers

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_context_facts", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    if args.days < 1:
        ap.error("--days must be at least 1")
    from fbi.core.config import settings as platform

    now = datetime.now(UTC)
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        doc = factor_counts.report(value_sheet_readers.fact_rows(conn, since=now - timedelta(days=args.days), until=now, typed=True))
    if args.as_json:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write("\n".join(factor_counts.lines(doc)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
