"""Settle again what a corrected result changed (fbi.picks.resettlement) - the audit after a deploy, and a manual run.

    python -m scripts.resettle                              # dry run: the matches corrected in the last 7 days
    python -m scripts.resettle --days 30                    # ... in the last 30 days
    python -m scripts.resettle --fixture 123 --fixture 456  # ... these matches, corrected or not
    python -m scripts.resettle --all                        # dry run: AUDIT of every settled record
    python -m scripts.resettle --all --apply --by NAME      # write what the audit found (a person's decision)

The pick pipeline already does the routine pass every 30 minutes (the matches corrected in the last 7 days); this is for
what it does not reach: the audit that finds what was corrected before revision 0080 (no correction was recorded then),
the parlays settled under the old half-line formula, and a worker that was down for more than a week.

A dry run writes inside a transaction it rolls back, so what it prints is exactly what --apply does. --apply needs
--by NAME: the name goes into the reason of every row of the trail (picks.resettlements). More than --max-fixtures
matches changing in one run is refused, whatever the flags: look at the list first.

Exit code: 0 done (or dry run), 2 wrong arguments, 3 refused by the guard or another pass was running.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from typing import Any

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.picks.resettlement import MAX_FIXTURES, RECHECK_WINDOW, resettle


def resettle_command(conn: psycopg.Connection[Any], *, at: datetime, audit: bool, fixtures: list[int], days: int | None,
                     apply: bool, by: str | None, max_fixtures: int) -> tuple[int, list[str]]:
    """(exit code, lines). The caller owns the transaction (``main`` commits only a clean --apply)."""
    if apply and not by:
        return 2, ["--apply needs --by NAME: the name goes into the reason of every row written"]
    if audit and (fixtures or days is not None):
        return 2, ["--all reads every settled record: drop --fixture and --days"]
    since = at - (RECHECK_WINDOW if days is None else timedelta(days=days))
    report = resettle(conn, at=at, apply=apply, audit=audit, fixture_ids=fixtures or None, since=since,
                      max_fixtures=max_fixtures, note=f"manual run by {by}" if by else "")
    return (3 if report.refused or report.busy else 0), report.render()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="audit: every settled record, corrected or not")
    ap.add_argument("--fixture", type=int, action="append", default=[], help="only this match (repeatable)")
    ap.add_argument("--days", type=int, help="the matches corrected in the last N days (default 7)")
    ap.add_argument("--apply", action="store_true", help="write it; without it, a dry run")
    ap.add_argument("--by", help="who runs it (--apply)")
    ap.add_argument("--max-fixtures", type=int, default=MAX_FIXTURES,
                    help=f"refuse to write if more matches than this change (default {MAX_FIXTURES})")
    args = ap.parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        code, lines = resettle_command(conn, at=now(), audit=args.all, fixtures=args.fixture, days=args.days,
                                       apply=args.apply, by=args.by, max_fixtures=args.max_fixtures)
        if code == 0 and args.apply:
            conn.commit()  # the re-settlement, when there was one (a dry run rolled itself back)
        else:
            conn.rollback()  # a refusal leaves no trace, and the advisory lock goes with the transaction
    print("\n".join(lines), file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
