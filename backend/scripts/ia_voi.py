"""The budget by value of information (``voi-v1``, ``fbi.budgeting``) from the command line, in SHADOW: for one Bogota day, what the policy
would have given each selection (its depth D0-D3 and its money within budget v3's day) against what the orchestrator actually spent on it, and
the cost of a useful signal by depth once the attribution exists.

    python -m scripts.ia_voi day --day 2026-11-07
    python -m scripts.ia_voi day --day 2026-11-07 --at 2026-11-07T15:00:00Z --checkpoint final --json

It reads only: no model, no search, no row written (budget v3 is read, its alerts are not checked). ``--dsn`` overrides the database (the
worker's own by default). Budget v3's envelopes come from the environment (``AiSettings.from_env``); no key is read for a call.

Exit status: 0 done, 2 could not run (usage error).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from fbi.ai import budget_v3
from fbi.ai.config import AiSettings
from fbi.ai.usage import PASS_SHARE
from fbi.budgeting import replay

COMMANDS = ("day",)
OK, CANNOT = 0, 2


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def parse_at(text: str | None) -> datetime | None:
    if text is None:
        return None
    try:
        at = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a moment (ISO 8601 with a zone)") from exc
    if at.tzinfo is None:
        raise ValueError(f"{text!r} has no time zone")
    return at.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_voi", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--day", required=True, metavar="YYYY-MM-DD", help="the Bogota day whose matches are replayed")
    ap.add_argument("--at", help="the moment (ISO 8601 with a zone); default: each selection as of its last review before the kick-off, budget v3 at the day's start")
    ap.add_argument("--checkpoint", default="pre", choices=sorted(PASS_SHARE), help="the pass whose share of the day is shared (default pre)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the whole report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run(conn: psycopg.Connection[Any], *, day: date, settings: AiSettings, at: datetime | None = None,
        checkpoint: str = "pre") -> tuple[dict[str, Any], int]:
    """The report (JSON-ready, with its lines) and the exit status. Reads only; the connection is the caller's."""
    try:
        budget = budget_v3.budget(conn, at=replay.budget_moment(day, at), settings=settings)
        rep = replay.replay_day(conn, day=day, budget=budget, at=at, checkpoint=checkpoint)
    except ValueError as exc:
        return {"error": str(exc)}, CANNOT
    doc = rep.as_json()
    doc["lines"] = rep.lines()
    return doc, OK


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        day, at = parse_day(args.day), parse_at(args.at)
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        doc, code = run(conn, day=day, settings=AiSettings.from_env(), at=at, checkpoint=args.checkpoint)
        conn.rollback()  # it only read
    if not args.as_json and "lines" in doc:
        sys.stdout.write("\n".join(doc["lines"]) + "\n")
    else:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    if code == CANNOT and "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
