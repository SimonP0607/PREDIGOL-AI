"""ctx-adj-v1 in shadow: what decision-v1 did against what the Council's adjustment would have proposed (plan IA, P0). Read-only.

    python -m scripts.ia_ctx_shadow report --from 2026-11-01 --to 2026-11-05              # both Council engines, days in Bogotá, --to included
    python -m scripts.ia_ctx_shadow report --from 2026-11-01 --to 2026-11-05 --engine ma-v1 --json
    python -m scripts.ia_ctx_shadow report --from 2026-11-01 --to 2026-11-05 --max-age-hours 0   # no age limit on the verdicts

For each decision of ``decision-v1`` recorded in the window, the newest verdict of each Council engine (``ma-v1``, ``ma-v1-h``) known at the
decision's moment is typed (``fbi.intel.context_adjustment``) and its effect proposed (never raising a state). Reported per engine: the counts by
verdict, the agreement with decision-v1 (over every judged row, and over the rows with a Council verdict), the confusion table, the rows the parser
refused and the selections an APROBADO or a CAUTELA would have been blocked or held back from. The connection is read-only: nothing is written.
Exit status: 0 a report, 2 it cannot run (a bad argument).
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
from fbi.intel import context_adjustment as ctx

COMMANDS = ("report",)
OK, CANNOT = 0, 2


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_ctx_shadow", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--from", dest="first", required=True, help="the first day (Bogotá) of the window")
    ap.add_argument("--to", dest="last", required=True, help="the last day of the window, included")
    ap.add_argument("--engine", choices=ctx.ENGINES, help="one Council engine (default: both)")
    ap.add_argument("--max-age-hours", type=float, default=ctx.REVIEW_MAX_AGE.total_seconds() / 3600,
                    help="how old a verdict may be at the decision's moment (default: 12, as filter 6; 0: no limit)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run(conn: psycopg.Connection[Any], *, first: date, last: date, engines: Sequence[str] = ctx.ENGINES,
        max_age: timedelta | None = ctx.REVIEW_MAX_AGE) -> tuple[dict[str, Any], int]:
    """The report (JSON-ready) and the exit status. The connection is the caller's; nothing is written."""
    if first > last:
        return {"error": "--from is after --to"}, CANNOT
    since, until = day_bounds(first)[0], day_bounds(last)[1]
    return ctx.shadow_report(conn, since=since, until=until, engines=engines, max_age=max_age), OK


def render(doc: dict[str, Any]) -> str:
    age = "no age limit" if doc["max_age_hours"] is None else f"verdicts at most {doc['max_age_hours']:g} h old"
    lines = [f"{doc['version']} over {doc['decision_version']}: {doc['decisions']} decisions, {doc['from']} .. {doc['to']} ({age})"]
    for engine, e in doc["engines"].items():
        a, c = e["agreement"], e["agreement_with_council"]
        lines.append(f"\n## {engine}: {e['rows']} rows, {e['with_review']} with a review, {e['refused']} refused")
        lines.append("  verdicts: " + ", ".join(f"{k} {v}" for k, v in e["by_verdict"].items()))
        lines.append(f"  agreement: {a['agree']}/{a['n']} ({a['rate']}); with a Council verdict: {c['agree']}/{c['n']} ({c['rate']})")
        lines.append("  confusion (decision-v1 -> proposed):")
        for actual, row in e["confusion"].items():
            lines.append(f"    {actual:14s} " + ", ".join(f"{k} {v}" for k, v in row.items()))
        lines.append(f"  held back or blocked ({len(e['held_back'])}):")
        for h in e["held_back"]:
            lines.append(f"    #{h['decision_id']} {h['known_at']} {h['checkpoint']} fixture {h['fixture_id']} {h['market_key']} {h['selection']} "
                         f"{h['line']}: {h['state']} -> {h['proposed']} ({h['verdict']}, {h['severity']}; {','.join(h['factor_codes']) or '-'})")
        for r in e["refused_rows"]:
            lines.append(f"    refused review #{r['review_id']} (decision #{r['decision_id']}): {r['why']}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        first, last = parse_day(args.first), parse_day(args.last)
    except ValueError as exc:
        ap.error(str(exc))
    engines = (args.engine,) if args.engine else ctx.ENGINES
    max_age = None if args.max_age_hours <= 0 else timedelta(hours=args.max_age_hours)
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on") as conn:
        doc, code = run(conn, first=first, last=last, engines=engines, max_age=max_age)
    if code == CANNOT:
        sys.stderr.write(f"{doc['error']}\n")
        return code
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n" if args.as_json else render(doc))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
