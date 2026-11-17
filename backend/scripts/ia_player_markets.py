"""The player markets in private evaluation (IA-130, AD-E04), measured from the command line. Read-only.

    python -m scripts.ia_player_markets measure --from 2026-11-01 --to 2026-11-17 [--competition 39] [--limit 400]

Over the finished matches that kicked off in ``[--from, --to)``: the player-shot prices of the answer in force 10 minutes before
kick-off (read back from RAW), the houses behind each selection and the share of «una sola casa», the names matched to the sheet, the
settlement of each price on the statistics (``player_count_ft@v1``) and the state each would have in the private evaluation with the
families on (``fbi.playermarkets.admission``) - the sample registered for AD-K02. JSON on stdout.

The connection refuses writes; nothing is asked of a provider or a model; nothing here is read by a decision, a pick or a page.
Exit 0 with a report, 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time

import psycopg

COMMANDS = ("measure",)
OK, CANNOT = 0, 2


def parse_day(text: str) -> datetime:
    return datetime.combine(date.fromisoformat(text), time(0), tzinfo=UTC)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_player_markets", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--from", dest="start", required=True, help="first kick-off day, YYYY-MM-DD (UTC)")
    ap.add_argument("--to", dest="end", required=True, help="the day after the last, YYYY-MM-DD (UTC)")
    ap.add_argument("--competition", type=int, action="append", default=[], help="only these competitions (repeatable)")
    ap.add_argument("--limit", type=int, default=400, help="at most this many matches (default 400)")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    args = ap.parse_args(argv)
    try:
        start, end = parse_day(args.start), parse_day(args.end)
    except ValueError as exc:
        ap.error(str(exc))
    if end <= start:
        sys.stderr.write("--to must be after --from\n")
        return CANNOT
    from fbi.core.config import settings as platform
    from fbi.playermarkets import lab
    from fbi.storage.payload_store import PayloadStore

    store = PayloadStore(platform.runtime.raw_store_dir)
    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000") as conn:
        doc = lab.measure(conn, store, start=start, end=end, at=datetime.now(UTC), competitions=args.competition,
                          limit=max(1, min(args.limit, 2000)))
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
