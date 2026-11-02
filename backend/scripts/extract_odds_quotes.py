"""The price clock from the command line (plan F1): structure the prices already sitting in RAW.

    python -m scripts.extract_odds_quotes sample --n 300      read-only dry run on the newest RAW /odds payloads: what would
                                                               be structured, what would be refused. Needs no new table.
    python -m scripts.extract_odds_quotes status               what is structured, what is pending, how big it is
    python -m scripts.extract_odds_quotes run --since 2026-09-25 [--limit 20000] [--max-seconds 3000]
                                                               structure the pending payloads (the worker does the same
                                                               a few hundred at a time; this is the backfill)

``run`` writes only ``market.market_definitions``, ``market.odds_extractions`` and ``market.odds_quotes``. It asks the provider
nothing and can be repeated: a payload already structured by this version of the extractor is not read again.

Exit status: 0 done (or nothing to do), 1 failures worth a look, 2 usage error.
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

from fbi.core.config import settings
from fbi.odds.quote_extract import (
    EXTRACTOR_VERSION,
    ExtractionReport,
    backlog,
    run_extraction,
    sample_extraction,
    table_bytes,
)


def _moment(text: str | None) -> datetime | None:
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _print(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, default=str, ensure_ascii=False)
    sys.stdout.write("\n")


def cmd_sample(conn: psycopg.Connection, args: argparse.Namespace) -> int:
    report = sample_extraction(conn, settings.runtime.raw_store_dir, sample=args.n, since=_moment(args.since),
                               until=_moment(args.until), verify_hashes=args.verify)
    conn.rollback()
    _print({"mode": "dry run - nothing was written", "extractor": EXTRACTOR_VERSION, **report.as_dict()})
    return 1 if report.payloads_failed or report.payloads_missing_file else 0


def cmd_status(conn: psycopg.Connection, _args: argparse.Namespace) -> int:
    out: dict[str, Any] = {"extractor": EXTRACTOR_VERSION}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT count(*), min(fetched_at), max(fetched_at) FROM raw.ingestion_payloads "
                    "WHERE endpoint = '/odds' AND http_status = 200 AND results_count > 0")
        n, first, last = cur.fetchone() or (0, None, None)
        out["raw_odds_payloads"] = {"count": n, "first": first, "last": last}
        cur.execute("SELECT status, extractor_version, count(*), coalesce(sum(quotes_written), 0), "
                    "       coalesce(sum(quotes_refused), 0) FROM market.odds_extractions GROUP BY 1, 2 ORDER BY 1, 2")
        out["ledger"] = [{"status": s, "version": v, "payloads": c, "quotes": q, "refused": r}
                         for s, v, c, q, r in cur.fetchall()]
        cur.execute("SELECT count(*), min(captured_at), max(captured_at), count(DISTINCT fixture_id) "
                    "FROM market.odds_quotes")
        rows, first_q, last_q, fixtures = cur.fetchone() or (0, None, None, 0)
        out["quotes"] = {"rows": rows, "first": first_q, "last": last_q, "fixtures": fixtures,
                         "gigabytes": round(table_bytes(conn) / 1e9, 3)}
        cur.execute("SELECT family, count(*) FILTER (WHERE extract), count(*) FROM market.market_definitions "
                    "GROUP BY 1 ORDER BY 1")
        out["definitions"] = [{"family": f, "extracted": e, "bets": t} for f, e, t in cur.fetchall()]
    out["backlog"] = backlog(conn)
    conn.rollback()
    _print(out)
    return 0


def cmd_run(conn: psycopg.Connection, args: argparse.Namespace) -> int:
    started = time.monotonic()
    total = ExtractionReport()
    since, until = _moment(args.since), _moment(args.until)
    left = args.limit
    rounds = 0
    while left > 0:
        remaining = None if args.max_seconds is None else args.max_seconds - (time.monotonic() - started)
        if remaining is not None and remaining <= 0:
            total.stopped_for_time = True
            break
        report = run_extraction(conn, settings.runtime.raw_store_dir, limit=min(left, args.batch), since=since,
                                until=until, max_seconds=remaining, verify_hashes=not args.no_verify)
        rounds += 1
        total.merge(report)
        total.payloads_seen += report.payloads_seen
        total.payloads_missing_file += report.payloads_missing_file
        total.problems.extend(report.problems)
        total.skipped_locked = total.skipped_locked or report.skipped_locked
        total.stopped_for_time = total.stopped_for_time or report.stopped_for_time
        left -= max(report.payloads_seen, 1)
        print(f"round {rounds}: {report.payloads_seen} payloads, {report.quotes_written} quotes, "
              f"{report.payloads_failed} failed, {time.monotonic() - started:.0f}s", file=sys.stderr)
        if report.skipped_locked or report.stopped_for_time or report.payloads_seen == 0:
            break
    _print({"mode": "run", "extractor": EXTRACTOR_VERSION, "rounds": rounds, "seconds": round(time.monotonic() - started),
            "backlog": backlog(conn), "gigabytes": round(table_bytes(conn) / 1e9, 3), **total.as_dict()})
    conn.rollback()
    if total.skipped_locked:
        return 0
    return 1 if total.payloads_failed or total.payloads_missing_file else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="extract_odds_quotes", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sample = sub.add_parser("sample", help="read-only dry run on the newest payloads")
    sample.add_argument("--n", type=int, default=300)
    sample.add_argument("--since")
    sample.add_argument("--until")
    sample.add_argument("--verify", action="store_true", help="re-hash every file (slower)")
    sub.add_parser("status", help="what is structured and what is pending")
    run = sub.add_parser("run", help="structure the pending payloads")
    run.add_argument("--since", default="2026-09-25", help="first fetched_at to read (default: where the RAW /odds series starts)")
    run.add_argument("--until")
    run.add_argument("--limit", type=int, default=20000, help="most payloads to read in this command")
    run.add_argument("--batch", type=int, default=500, help="payloads per round")
    run.add_argument("--max-seconds", type=float, default=None)
    run.add_argument("--no-verify", action="store_true", help="skip the re-hash of every file")
    args = parser.parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10) as conn:
        if args.command == "sample":
            return cmd_sample(conn, args)
        if args.command == "status":
            return cmd_status(conn, args)
        return cmd_run(conn, args)


if __name__ == "__main__":
    raise SystemExit(main())
