"""What each path of decision costs, and whether every call to Opus has its rule, from the command line (IA-034; ``cost-paths-v1``).

    python -m scripts.ia_cost_paths                                  # the preview: the last 14 days until now, in Spanish
    python -m scripts.ia_cost_paths --days 7                         # another window, ending now
    python -m scripts.ia_cost_paths --since 2026-10-28 --until 2026-11-11   # a window of whole UTC days ([since, until))
    python -m scripts.ia_cost_paths --json                           # the whole report as JSON

Reads only, and writes nothing in any mode: the connection is opened read-only and every statement runs in ONE snapshot (``REPEATABLE READ``),
so the paths and the ledger's own sum read the same rows. The cost of each path - the review of production with its brief, the shadow's
deliberation, Research and Exa, the chronicles, the rest - by part, per match and per candidate with their n; every call to Opus with the rule
the code recorded for it; what went by Batch and what the cache read; and the readers' chronicle from its own ledger, beside the total. It
decides nothing: no route, model, switch or threshold changes. ``--dsn`` overrides the database (the worker's own by default).

Exit status: 0 the report was made and its total is the ledger's to the cent, 1 it was made and the total does NOT reconcile (or a call to
Opus has no rule), 2 could not run (a usage error).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

import psycopg

from fbi.ai import cost_paths, cost_paths_readers

DEFAULT_DAYS = 14
OK, MISMATCH, CANNOT = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_cost_paths", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS, help="the window's length in days, ending now (default 14)")
    ap.add_argument("--since", type=date.fromisoformat, default=None, help="first day of the window (UTC, YYYY-MM-DD); overrides --days")
    ap.add_argument("--until", type=date.fromisoformat, default=None, help="the day after the last one (UTC, YYYY-MM-DD); now by default")
    ap.add_argument("--json", action="store_true", help="print the whole report as JSON instead of the preview")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def window(days: int, since: date | None, until: date | None, *, now: datetime) -> tuple[datetime, datetime]:
    end = now if until is None else datetime.combine(until, time(0), tzinfo=UTC)
    start = end - timedelta(days=days) if since is None else datetime.combine(since, time(0), tzinfo=UTC)
    if days <= 0 and since is None:
        raise ValueError(f"--days must be positive ({days})")
    if end <= start:
        raise ValueError(f"the window is empty ({start.isoformat()} to {end.isoformat()})")
    return start, end


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        start, end = window(args.days, args.since, args.until, now=datetime.now(UTC))
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return CANNOT
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000") as conn:
        conn.read_only = True
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction():
            got = cost_paths_readers.read(conn, since=start, until=end)
    rep = cost_paths.report(got.calls, got.links, got.routes, got.lab_items, ledger=got.ledger, user_ledger=got.user_ledger,
                            since=start, until=end)
    if args.json:
        sys.stdout.write(json.dumps(rep, indent=1, default=str, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write("\n".join(cost_paths.lines(rep)) + "\n")
    return OK if rep["total"]["reconciles"] and rep["opus"]["all_registered"] else MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())
