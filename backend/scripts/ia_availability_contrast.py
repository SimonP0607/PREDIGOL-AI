"""How often a report of availability is contradicted by the official match sheet, by level of source (RP-4.4, ``availability-contrast-v1``). Reading only.

    python -m scripts.ia_availability_contrast                  # the last 90 days of played matches with both sheets, state read 90 minutes before kick-off
    python -m scripts.ia_availability_contrast --days 180 --lead-minutes 60 --limit 5000
    python -m scripts.ia_availability_contrast --json

For each played match the state of every player named by a report (provider, official sources, outlets) is read as it was ``--lead-minutes`` before kick-off,
resolved by the precedence of ``fbi.people.availability`` and set against the official sheet. The table gives, per level of source, how many reports of
«baja»/«sancionado» named a man who then appeared on the sheet (contradicted), with the Wilson interval; how many «duda» played; and how many «disponible»
were not on the sheet. It writes nothing and returns no health detail. ``--dsn`` overrides the database.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import psycopg

from fbi.ai import availability_contrast as ac

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=120000"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_availability_contrast", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--lead-minutes", type=int, default=int(ac.LEAD.total_seconds() // 60))
    ap.add_argument("--limit", type=int, default=3000, help="at most this many matches, newest first")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    if args.days < 1 or args.lead_minutes < 1 or args.limit < 1:
        ap.error("--days, --lead-minutes and --limit must be at least 1")
    from fbi.core.config import settings as platform

    until = datetime.now(UTC)
    since = until - timedelta(days=args.days)
    lead = timedelta(minutes=args.lead_minutes)
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        doc = ac.summarize(ac.collect(conn, since=since, until=until, limit=args.limit, lead=lead))
        doc["matches"] = ac.matches_read(conn, since=since, until=until, limit=args.limit)
    doc["lead_minutes"] = args.lead_minutes
    sys.stdout.write((json.dumps(doc, indent=1, ensure_ascii=False) if args.as_json else "\n".join([*ac.lines(doc), f"  partidos leídos: {doc['matches']}"])) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
