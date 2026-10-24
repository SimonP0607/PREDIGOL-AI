"""Is every change of the model code on record? (plan F12) - the model-code ledger against what production forecast with.

    python -m scripts.promotion_trace show [--days 30] [--json]      # which fingerprints forecast in production and the promotion that covers each
    python -m scripts.promotion_trace sync                           # dry run: the ledger entries intel.promotions does not have yet
    python -m scripts.promotion_trace sync --confirm                 # write them (entity 'model', append-only)

The ledger is ``fbi.research.promotions.LEDGER``: one entry per fingerprint of the model packages, added in the same commit as the change
(``tests/unit/test_model_code_ledger.py`` fails otherwise). ``show`` reads through a connection that cannot write; ``sync`` writes the ledger's own
rows and nothing else, and refuses an entry that cites a hypothesis or an experiment that does not exist. 0 provider requests, 0 AI; nothing it
prints or writes reaches a model, a forecast or a pick.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import psycopg

from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.research import trace


def jsonable(value: Any) -> Any:
    """The report with its datetimes as text, to print as JSON."""
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value.isoformat() if hasattr(value, "isoformat") else value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("show", "sync"))
    ap.add_argument("--days", type=int, default=trace.DEFAULT_DAYS, help="the window to look back over (show)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON (show)")
    ap.add_argument("--confirm", action="store_true", help="write the missing rows; without it, a dry run (sync)")
    args = ap.parse_args(argv)
    now = clock_now()
    if args.command == "show":
        with psycopg.connect(settings.database.psycopg_url, options="-c default_transaction_read_only=on") as conn:
            report = trace.trace(conn, now=now, days=args.days)
        print(json.dumps(jsonable(report), indent=1, sort_keys=True) if args.json else trace.render(report))
        return 0
    with psycopg.connect(settings.database.psycopg_url) as conn:
        try:
            lines = trace.sync(conn, now=now, confirm=args.confirm)
        except LookupError as exc:
            conn.rollback()
            print(f"refused: {exc}", file=sys.stderr)
            return 3
        if args.confirm:
            conn.commit()
        else:
            conn.rollback()
    print("\n".join(lines))
    if not args.confirm and not lines[0].startswith("nothing"):
        print("Nothing was written. Add --confirm to write these rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
