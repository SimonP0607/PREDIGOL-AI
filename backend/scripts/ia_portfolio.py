"""The Portfolio Engine in shadow (``portfolio-v1``, plan IA P2, IA-013): the day's RECOMMENDED selections as a portfolio.
Read-only.

    python -m scripts.ia_portfolio day --day 2026-11-07                     # as of now
    python -m scripts.ia_portfolio day --day 2026-11-07 --at 2026-11-07T15:00:00+00:00 --json
    python -m scripts.ia_portfolio day --day 2026-11-07 --what-if-caution  # CAUTION too, HYPOTHETICAL

Correlations with their source, stakes (stake-v1, scaled for a shared budget, held by the exposure limits, with the limit
that binds), the day set and the pick of the day (comp-priority-v1, select_day's caps) and the parlays of RECOMMENDED legs
(``fbi.portfolio.build``). A day with no RECOMMENDED selection is reported as such. The connection is read-only: nothing
is written. Exit status: 0 a report, 2 it cannot run (a bad day or moment).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from fbi.portfolio import build

COMMANDS = ("day",)
OK, CANNOT = 0, 2


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def parse_at(text: str | None) -> datetime:
    if text is None:
        return datetime.now(UTC)
    try:
        at = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a moment (ISO 8601 with its offset)") from exc
    if at.tzinfo is None:
        raise ValueError(f"{text!r} has no offset")
    return at


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_portfolio", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--day", required=True, help="the day (Bogotá) whose matches are read")
    ap.add_argument("--at", help="the moment the portfolio is built as of (default: now)")
    ap.add_argument("--what-if-caution", action="store_true", dest="what_if",
                    help="also treat CAUTION as eligible, for measurement only (HYPOTHETICAL)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run(conn: psycopg.Connection[Any], *, day: date, at: datetime, what_if: bool = False) -> tuple[dict[str, Any], int]:
    """The report (JSON-ready) and the exit status. The connection is the caller's; nothing is written."""
    return build.build_day(conn, day, at=at, what_if=what_if), OK


def render(doc: dict[str, Any]) -> str:
    c = doc["counts"]
    lines = [f"{doc['version']} (shadow{', HYPOTHETICAL' if doc['hypothetical'] else ''}) {doc['day']} as of {doc['at']}",
             f"  {doc['message']}",
             "  state-v2: " + ", ".join(f"{k} {v}" for k, v in c["by_state_v2"].items()),
             f"  staked {c['staked']} of {c['eligible']} eligible, {c['total_units']} u in all"]
    for s in doc["selections"]:
        st = s["stake"]
        ind = st["individual"]["units"] if st["individual"] else 0.0
        tag = " [HYPOTHETICAL]" if s["hypothetical"] else ""
        lines.append(f"    #{s['decision_id']} fixture {s['fixture_id']} {s['market_key']} {s['selection']} {s['line']} "
                     f"@{s['odds']} p_cal {s['p_cal']} {s['state_v2']}{tag}: stake-v1 {ind} -> scaled {st['scaled_units']} "
                     f"-> {st['final_units']} u" + (f" (limit {st['binding_limit']})" if st["binding_limit"] else ""))
    for x in doc["correlations"]:
        lines.append(f"    corr #{x['a']}~#{x['b']} rho {x['rho']} {x['source']}" + (" (shared budget)" if x["shares_budget"] else ""))
    lines.append(f"  day set: {[d['decision_id'] for d in doc['day_set']]}")
    pod = doc["pick_of_the_day"]
    lines.append(f"  pick of the day: {'none' if pod is None else '#' + str(pod['decision_id'])}")
    p = doc["parlays"]
    lines.append(f"  parlays: {len(p['built'])}" + (f" ({p['reason']})" if p["reason"] else ""))
    for b in p["built"]:
        lines.append(f"    {[leg['decision_id'] for leg in b['legs']]} @{b['combined_odds']} p_all_low {b['p_all_low']} "
                     f"stake {b['stake']['final_units']} u")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        day = parse_day(args.day)
        at = parse_at(args.at)
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on") as conn:
        doc, code = run(conn, day=day, at=at, what_if=args.what_if)
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n" if args.as_json else render(doc))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
