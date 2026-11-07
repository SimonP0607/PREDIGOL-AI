"""The trace of a pick, a decision, a selection or a match from end to end (``trace-v1``, Plan Maestro IA, phase P0), from the command line.

    python -m scripts.ia_trace show --pick 123                                  # the pick's selection, every span, what is missing
    python -m scripts.ia_trace show --decision 456 --json
    python -m scripts.ia_trace show --fixture 789 --market OU --selection Over --line 2.5
    python -m scripts.ia_trace show --fixture 789                               # the match: its data, its agents, every decision of it
    python -m scripts.ia_trace coverage --day 2026-11-05                        # the share of the day's traces that are complete

Read-only: every statement is a SELECT (``fbi.observability.trace``) and nothing is committed. ``show`` exits 0 when the trace is complete
and 1 when a mandatory span is missing; ``coverage`` exits 0 when every trace of the day is complete, 1 when some is not, 3 when the day has
nothing to judge (zero of zero is not 100 %), and 2 when it cannot run (bad arguments).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg

from fbi.core.decision_versions import LAYERS
from fbi.observability import trace

COMMANDS = ("show", "coverage")
OK, NO, CANNOT, PENDING = 0, 1, 2, 3


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_trace", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--pick", type=int, help="show: a pick (picks.picks.id)")
    ap.add_argument("--decision", type=int, help="show: a decision (intel.decisions.id), of either layer")
    ap.add_argument("--fixture", type=int, help="show: a match; with --market and --selection, one of its selections")
    ap.add_argument("--market", help="show: the market key (with --fixture)")
    ap.add_argument("--selection", help="show: the selection (with --fixture and --market)")
    ap.add_argument("--line", help="show: the line (default 0)")
    ap.add_argument("--layer", choices=sorted(LAYERS), default="core", help="the decision layer read for a pick or a fixture (default core)")
    ap.add_argument("--day", help="coverage: the Bogotá day (YYYY-MM-DD)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the result as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def render(t: trace.Trace) -> str:
    """The trace as a reader looks at it: one line per span, the missing ones marked."""
    c = trace.completeness(t)
    head = [f"{t.version} {t.anchor}  trace {t.trace_id}  ({t.scope}, {t.decision_version})",
            f"  {'COMPLETE' if c.complete else 'INCOMPLETE'}: present {', '.join(c.present) or '-'}"
            f" | n/a {', '.join(c.not_applicable) or '-'} | missing {', '.join(c.missing) or '-'}"]
    marks = {trace.PRESENT: "+", trace.MISSING: "!", trace.NOT_APPLICABLE: "·", trace.NOT_READ: "?"}
    lines = []
    for s in t.spans:
        ids = ",".join(s.row_ids) or "-"
        versions = " ".join(f"{k}={v}" for k, v in s.versions.items())
        when = "" if s.at is None else s.at.isoformat(timespec="minutes")
        detail = s.note or ", ".join(f"{k}={v}" for k, v in list(s.payload.items())[:6] if k not in ("filters",))
        lines.append(f"  {marks.get(s.status, ' ')} {s.kind:<12} {s.source:<34} {ids:<24} {when:<22} {versions}  {detail}".rstrip())
    return "\n".join([*head, *lines])


def run(args: argparse.Namespace, conn: psycopg.Connection[Any]) -> tuple[dict[str, Any] | str, int]:
    version = LAYERS[args.layer]
    if args.command == "show":
        try:
            t = trace.trace_of(conn, pick_id=args.pick, decision_id=args.decision, fixture_id=args.fixture, market_key=args.market,
                               selection=args.selection, line=args.line, decision_version=version)
        except ValueError as exc:
            return {"error": str(exc)}, CANNOT
        code = OK if trace.completeness(t).complete else NO
        return (t.as_json() if args.as_json else render(t)), code
    if not args.day:
        return {"error": "coverage needs --day YYYY-MM-DD"}, CANNOT
    try:
        day = date.fromisoformat(args.day)
    except ValueError:
        return {"error": f"{args.day!r} is not a day (YYYY-MM-DD)"}, CANNOT
    cov = trace.coverage(conn, day, decision_version=version)
    doc = cov.as_json()
    total = cov.selections.total + cov.published.total
    code = PENDING if total == 0 else OK if cov.selections.complete == cov.selections.total and cov.published.complete == cov.published.total else NO
    if args.as_json:
        return doc, code
    lines = [f"{cov.version} coverage {cov.day} ({cov.decision_version})"]
    for unit in (cov.selections, cov.published):
        share = "-" if unit.share is None else f"{100 * unit.share:.1f} %"
        missing = ", ".join(f"{k} ({n})" for k, n in unit.missing) or "-"
        lines.append(f"  {unit.population:<10} {unit.complete}/{unit.total} complete = {share}; missing most: {missing}")
    return "\n".join(lines), code


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        conn.read_only = True
        out, code = run(args, conn)
        conn.rollback()
    if isinstance(out, str):
        sys.stdout.write(out + "\n")
    else:
        sys.stdout.write(json.dumps(out, indent=1, default=str, ensure_ascii=False) + "\n")
        if code == CANNOT and "error" in out:
            sys.stderr.write(f"{out['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
