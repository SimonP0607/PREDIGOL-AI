"""The attribution of the shadow (Plan Maestro IA, phase 5), from the command line: recompute the days before the daily step existed and read the figure
Gate B asks for.

    python -m scripts.ia_attribution coverage                          # the share of the matches of the last 14 days with attributions (writes nothing)
    python -m scripts.ia_attribution coverage --since 2026-10-20 --until 2026-11-03
    python -m scripts.ia_attribution scoreboard                        # hits and misses per agent, version and arm, from the last 14 days
    python -m scripts.ia_attribution recompute --from 2026-10-20 --to 2026-11-02    # attribute earlier days of the shadow («batch»; writes)
    python -m scripts.ia_attribution recompute --from 2026-10-20 --to 2026-11-02 --dry-run   # the same, rolled back: how many rows it would write

Run it where the worker runs. The recomputation applies the very rule the daily step applies (``fbi.ai.agents.attribution``): the rows are the same ones, marked
«batch», and the ones that exist already are left alone, so it can be run twice. It writes only into ``intel.agent_attributions``; no model is called and no
pick, filter or decision is read or changed. ``coverage`` exits 0 when the share reaches the 95 % the plan asks of Gate B, 1 when it does not, 3 when there
is no match yet to judge (zero of zero is not 100 %), and 2 when it cannot run (a bad day).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai.agents import attribution
from fbi.ai.calendar import day_bounds

COMMANDS = ("coverage", "scoreboard", "recompute")
GATE_B_SHARE = 0.95
"""Plan section 24, Gate B: «atribución en ≥ 95 %»."""
WINDOW = timedelta(days=14)
OK, NO, CANNOT, PENDING = 0, 1, 2, 3


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_attribution", description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--since", help="coverage, scoreboard: the first day (default: 14 days before --until)")
    ap.add_argument("--until", help="coverage: the last day, included (default: yesterday, Bogotá time)")
    ap.add_argument("--from", dest="first", help="recompute: the first day to attribute")
    ap.add_argument("--to", dest="last", help="recompute: the last day to attribute, included")
    ap.add_argument("--dry-run", action="store_true", help="recompute: do everything and roll it back")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run(command: str, conn: psycopg.Connection[Any], *, at: datetime, since: date | None = None, until: date | None = None, first: date | None = None,
        last: date | None = None, dry_run: bool = False) -> tuple[dict[str, Any], int]:
    """One command: its report (JSON-ready) and its exit status. The connection is the caller's; ``recompute`` commits what it writes unless it is a dry run."""
    from fbi.ai.calendar import local_day

    if command not in COMMANDS:
        return {"error": f"unknown command {command!r}"}, CANNOT
    through = until or local_day(at) - timedelta(days=1)
    start_day = since or through - WINDOW
    if start_day > through:
        return {"error": "the first day is after the last one"}, CANNOT
    if command == "coverage":
        found = attribution.coverage(conn, since=day_bounds(start_day)[0], until=day_bounds(through)[1])
        found |= {"from": start_day.isoformat(), "to": through.isoformat(), "gate_b_share": GATE_B_SHARE}
        share = found["share"]
        return found, PENDING if share is None else OK if share >= GATE_B_SHARE else NO
    if command == "scoreboard":
        return {"version": attribution.VERSION, "from": start_day.isoformat(), "rows": attribution.scoreboard(conn, since=day_bounds(start_day)[0])}, OK
    if first is None or last is None:
        return {"error": "recompute needs --from and --to"}, CANNOT
    if first > last:
        return {"error": "--from is after --to"}, CANNOT
    if last >= local_day(at):
        return {"error": "--to is a day that has not finished: the daily step attributes today when it ends"}, CANNOT
    report = attribution.recompute(conn, first=first, last=last, at=at)
    doc = {"version": attribution.VERSION, "from": first.isoformat(), "to": last.isoformat(), "selections": report.selections, "rows": report.rows,
           "written": report.written, "skipped": report.skipped, "dry_run": dry_run}
    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    return doc, OK


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        since = parse_day(args.since) if args.since else None
        until = parse_day(args.until) if args.until else None
        first = parse_day(args.first) if args.first else None
        last = parse_day(args.last) if args.last else None
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        doc, code = run(args.command, conn, at=datetime.now(UTC), since=since, until=until, first=first, last=last, dry_run=args.dry_run)
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    if code == CANNOT and "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
