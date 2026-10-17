"""Write the line value of every started pick that has none: odds taken against the same bookmaker's last
pre-match price (fbi.picks.fast_settlement.fill_line_value).

    python -m scripts.line_value              # dry run: computed, then rolled back
    python -m scripts.line_value --apply      # keep it
    python -m scripts.line_value --apply --all-history

Database only - zero provider requests. Only derived rows in picks.pick_line_value are written; a pick, a price
or a result is never touched. The worker's pipeline does the last three days on every pass; ``--all-history``
reaches every pick ever made, once.
"""

from __future__ import annotations

import argparse

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.picks.fast_settlement import fill_line_value


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="line_value", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--all-history", action="store_true")
    args = parser.parse_args()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        before = conn.execute("SELECT count(*) FROM picks.pick_line_value").fetchone()
        written = fill_line_value(conn, at=now(), all_history=args.all_history)
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    print(f"line values before: {before[0] if before else 0}; written now: {written} "
          f"({'all history' if args.all_history else 'last three days'})")
    print("applied" if args.apply else "dry run - rolled back (use --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
