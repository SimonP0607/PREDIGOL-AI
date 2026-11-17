"""The cycle of states of a selection (IA-068, AD-D02): measure it, run one pass of the shadow writer, read it.

    python -m scripts.ia_lifecycle measure --from 2026-11-02 --to 2026-11-15 [--json]   # read-only: what the cycle would hold
    python -m scripts.ia_lifecycle run [--dry-run]                                     # one pass (needs FBI_LIFECYCLE=shadow)
    python -m scripts.ia_lifecycle tracking --from 2026-11-14 --to 2026-11-16 [--state descartada] [--json]

``measure`` and ``tracking`` open a read-only connection; ``run --dry-run`` too. ``run`` writes ``intel.selection_lifecycle`` and
nothing else, and only while ``FBI_LIFECYCLE`` is ``shadow``. Days are Bogotá days. Exit status: 0 done, 2 it cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import psycopg

from fbi.ai.calendar import day_bounds
from fbi.core.clock import now
from fbi.lifecycle import machine, reader, store

READ_ONLY = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_lifecycle", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--dsn", help="the database (default: the platform's)")
    sub = ap.add_subparsers(dest="command", required=True)
    m = sub.add_parser("measure", help="selections and rows per day the cycle would hold (read-only)")
    m.add_argument("--from", dest="date_from", required=True)
    m.add_argument("--to", dest="date_to", required=True)
    m.add_argument("--json", action="store_true", dest="as_json")
    r = sub.add_parser("run", help="one pass of the shadow writer")
    r.add_argument("--dry-run", action="store_true")
    t = sub.add_parser("tracking", help="C-03's reading of the cycle (read-only)")
    t.add_argument("--from", dest="date_from", required=True)
    t.add_argument("--to", dest="date_to", required=True)
    t.add_argument("--state", choices=machine.STATES)
    t.add_argument("--family", choices=reader.FAMILIES)
    t.add_argument("--limit", type=int, default=20)
    t.add_argument("--json", action="store_true", dest="as_json")
    return ap


def _days(a: str, b: str) -> list[date]:
    first, last = date.fromisoformat(a), date.fromisoformat(b)
    if last < first or (last - first).days > 62:
        raise ValueError("a period is 1 to 63 days")
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    from fbi.core.config import settings as platform

    dsn = args.dsn or platform.database.psycopg_url
    out: Any
    if args.command == "run":
        if not args.dry_run and store.mode() != "shadow":
            sys.stderr.write(f"{store.SWITCH} is not shadow: nothing is written (use --dry-run to see what a pass would do)\n")
            return 2
        with psycopg.connect(dsn, options=READ_ONLY if args.dry_run else "-c TimeZone=UTC") as conn:
            out = store.run_pass(conn, now=now(), dry_run=args.dry_run).as_json()
    else:
        try:
            days = _days(args.date_from, args.date_to)
        except ValueError as exc:
            ap.error(str(exc))
        with psycopg.connect(dsn, options=READ_ONLY) as conn:
            if args.command == "measure":
                at = now()
                out = {}
                for d in days:
                    start, end = day_bounds(d)
                    out[d.isoformat()] = store.measure(conn, start=start, end=end, now=at)
            else:
                out = reader.tracking(conn, date_from=days[0], date_to=days[-1], state=args.state, family=args.family,
                                      limit=args.limit)
    if getattr(args, "as_json", False) or args.command == "run":
        sys.stdout.write(json.dumps(out, indent=1, default=str, ensure_ascii=False, sort_keys=True) + "\n")
    elif args.command == "measure":
        for d, m in out.items():
            sys.stdout.write(f"{d}: {m['selections']} selections ({m['by_layer']}), {m['rows']} rows, illegal {m['illegal']}, "
                             f"unknown reason {m['unknown_reason_rows']}\n")
    else:
        sys.stdout.write(f"{out['period']}: " + ", ".join(f"{k} {v}" for k, v in out["counts_by_state"].items()) + "\n")
        for it in out["items"]:
            s = it["selection"]
            sys.stdout.write(f"  {it['fixture']['id']} {s['market']} {s['selection']} {s['line']} ({s['family']}): {it['state']} "
                             f"{it['reason']} at {it['known_at']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
