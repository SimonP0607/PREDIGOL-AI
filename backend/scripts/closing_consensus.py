"""The consensus of the real close of the market: backfill and measure (plan RP-1.4).

    python -m scripts.closing_consensus backfill [--days N]     compute what is missing and the value of every settled decision against it
    python -m scripts.closing_consensus measure [--days N]      the plan's acceptance and the two references side by side (read-only)

``backfill`` only adds rows (``ON CONFLICT DO NOTHING``): it rewrites nothing, and it is safe to run twice.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta

import psycopg

from fbi.core.config import settings as platform
from fbi.market import closing_consensus


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("backfill", "measure"))
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn", default=None)
    args = ap.parse_args(argv)
    now = datetime.now(UTC)
    if args.days < 1:
        ap.error("--days must be at least 1")
    options = "-c TimeZone=UTC" if args.action == "backfill" else "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=options) as conn:
        if args.action == "backfill":
            made = closing_consensus.run(conn, at=now, days=args.days, commit=True)
            conn.commit()
            n = closing_consensus.settle(conn, at=now)
            conn.commit()
            print(json.dumps({**made, "decisions": n}))
            return 0
        doc = closing_consensus.measure(conn, since=now - timedelta(days=args.days), until=now)
    print(json.dumps(doc, default=str, ensure_ascii=False) if args.as_json else "\n".join(closing_consensus.lines(doc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
