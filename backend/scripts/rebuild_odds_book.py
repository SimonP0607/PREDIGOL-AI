"""Rebuild the current-price book by hand (plan Cuotas, BE-010): ``market.book_current`` from the answers in force, read back from RAW.

    python -m scripts.rebuild_odds_book                          DRY RUN: every match the book should hold (kick-off in the last
                                                                 6 hours or later), read and counted; nothing is written
    python -m scripts.rebuild_odds_book --fixture 9207           one match (repeat --fixture for more)
    python -m scripts.rebuild_odds_book --since 2026-11-08       the matches kicking off from that instant (UTC unless it says)
    python -m scripts.rebuild_odds_book --apply                  write it, and delete the rows of matches that kicked off more
                                                                 than 6 hours ago (not with --fixture)

It asks the provider nothing and writes only ``market.book_current`` (with ``--apply``). It works whatever ``FBI_ODDS_BOOK`` says:
the switch is the worker's. It prints the counts (matches by state, rows that would be or were inserted, updated, left as they
were, deleted, purged; the types hidden and why) and the size of the table. A build with an older ``--since`` than 6 hours
writes rows the worker's next pass deletes again.

Exit status: 0 done, 1 a match failed or a RAW body could not be read, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.odds.book import BUILDER_VERSION, PURGE_AFTER, build, held_fixtures, table_bytes
from fbi.odds.book_taxonomy import BOOK_TAXONOMY_VERSION, book_spec


def _moment(text: str | None) -> datetime | None:
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _table(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT count(*), count(DISTINCT fixture_id), min(kickoff_at), max(kickoff_at), max(built_at) "
                    "FROM market.book_current")
        rows, fixtures, first, last, built = cur.fetchone() or (0, 0, None, None, None)
    size = table_bytes(conn)
    return {"rows": rows, "fixtures": fixtures, "first_kickoff": first, "last_kickoff": last, "last_built": built,
            "bytes": size, "megabytes": round(size / 1e6, 2)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rebuild_odds_book", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the rows (without it nothing is written)")
    parser.add_argument("--fixture", type=int, action="append", default=[], help="our fixture id (repeatable)")
    parser.add_argument("--since", help="kick-off from this instant (default: 6 hours ago)")
    parser.add_argument("--max-seconds", type=float, default=None, help="stop after this long (the rest is not built)")
    parser.add_argument("--no-verify", action="store_true", help="skip the re-hash of every RAW file")
    args = parser.parse_args(argv)
    moment = now()
    since = _moment(args.since) or moment - PURGE_AFTER
    started = time.monotonic()
    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10) as conn:
        fixtures = list(args.fixture) or held_fixtures(conn, kickoff_from=since)
        conn.commit()
        report = build(conn, settings.runtime.raw_store_dir, fixtures, apply=args.apply, now=moment,
                       purge_old=args.apply and not args.fixture, max_seconds=args.max_seconds,
                       verify_hashes=not args.no_verify)
        table = _table(conn)
        conn.rollback()
    out = report.as_dict()
    hidden: dict[str, Any] = {}
    for bet_id, answers in sorted(report.hidden_by_taxonomy.items()):
        spec = book_spec(bet_id)
        hidden[str(bet_id)] = {"answers": answers, "why": spec.hidden_reason if spec else None}
    out["hidden_by_taxonomy"] = hidden
    estimate = round(report.summary_bytes / max(report.fixtures_priced, 1))
    json.dump({"mode": "apply" if args.apply else "dry run - nothing was written", "taxonomy": BOOK_TAXONOMY_VERSION,
               "builder": BUILDER_VERSION, "kickoff_from": None if args.fixture else since, "fixtures_asked": len(fixtures),
               "seconds": round(time.monotonic() - started, 1), "summary_bytes_per_priced_match": estimate,
               **out, "table": table}, sys.stdout, indent=2, default=str, ensure_ascii=False)
    sys.stdout.write("\n")
    if report.skipped_locked:
        print("another build of the book is running (the worker?): nothing was done", file=sys.stderr)
        return 0
    return 1 if report.failed or report.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
