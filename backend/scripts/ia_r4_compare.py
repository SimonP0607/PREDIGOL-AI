"""The review of production (``review-v2``) beside the Council of the shadow, from the command line (IA-029, R4; ``r4-compare-v1``).

    python -m scripts.ia_r4_compare                          # since 26 Oct 2026 (the Council's first day in the shadow) until now
    python -m scripts.ia_r4_compare --since 2026-11-03       # another first day (UTC)
    python -m scripts.ia_r4_compare --since 2026-11-03 --until 2026-11-10
    python -m scripts.ia_r4_compare --json                   # only the JSON

Reads only (the connection is opened read-only) and writes nothing: on the selections two engines both reviewed before the kick-off, how often they
agree, where they do not and what those selections did after the match (outcome at a flat stake of 1, CLV), what each engine kept and rejected and
what it cost, and the spend of the window by prompt and model. Every rate carries its cases and its 95 % interval. It decides nothing: it retires
no prompt, changes no routing and names no threshold. ``--dsn`` overrides the database (the worker's own by default).

Exit status: 0 the report was made, 2 could not run (a usage error).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time

import psycopg

from fbi.ai import r4_compare, r4_readers

DEFAULT_SINCE = date(2026, 10, 26)
OK, CANNOT = 0, 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_r4_compare", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", type=date.fromisoformat, default=DEFAULT_SINCE, help="first day of the window (UTC, YYYY-MM-DD)")
    ap.add_argument("--until", type=date.fromisoformat, default=None, help="the day after the last one (UTC, YYYY-MM-DD); now by default")
    ap.add_argument("--json", action="store_true", help="print only the JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def window(since: date, until: date | None, *, now: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(since, time(0), tzinfo=UTC)
    end = now if until is None else datetime.combine(until, time(0), tzinfo=UTC)
    if end <= start:
        raise ValueError(f"the window is empty ({start.isoformat()} to {end.isoformat()})")
    return start, end


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        start, end = window(args.since, args.until, now=datetime.now(UTC))
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return CANNOT
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC -c default_transaction_read_only=on") as conn:
        conn.read_only = True
        rows = r4_readers.reviews(conn, since=start, until=end)
        spend = r4_readers.usage(conn, since=start, until=end)
    rep = r4_compare.report(rows, spend, since=start, until=end)
    sys.stdout.write(json.dumps(rep, indent=1, default=str, ensure_ascii=False) + "\n")
    if not args.json:
        sys.stdout.write("\n".join(r4_compare.lines(rep)) + "\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
