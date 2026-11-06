"""state-v2 recorded from decision-v1's states: RECOMMENDED, CAUTION, WATCH, ABSTAIN, REJECTED (plan IA, P0). Read-only.

    python -m scripts.ia_state_v2 report --day 2026-11-05          # the day's newest row per selection and checkpoint (Bogotá)
    python -m scripts.ia_state_v2 report --day 2026-11-05 --json

The counts per state and per reason (``fbi.intel.state_v2.classify``), the labels on RECOMMENDED (PICK_DEL_DIA, PICK_PREMIUM, CANDIDATO_PARLAY),
decision-v1's state against state-v2's, and every INVESTIGACION no rule knows (ABSTAIN ``unclassified``), listed. The connection is read-only:
nothing is written. Exit status: 0 a report, 2 it cannot run (a bad day).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg

from fbi.intel import state_v2

COMMANDS = ("report",)
OK, CANNOT = 0, 2


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_state_v2", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--day", required=True, help="the day (Bogotá) whose decisions are read")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run(conn: psycopg.Connection[Any], *, day: date) -> tuple[dict[str, Any], int]:
    """The report (JSON-ready) and the exit status. The connection is the caller's; nothing is written."""
    return state_v2.day_report(conn, day=day), OK


def render(doc: dict[str, Any]) -> str:
    lines = [f"{doc['version']} over {doc['decision_version']}, {doc['day']}: {doc['rows']} rows (newest per selection and checkpoint)"]
    for state, n in doc["by_state"].items():
        reasons = doc["by_reason"].get(state, {})
        lines.append(f"  {state:12s} {n:5d}  " + ", ".join(f"{k} {v}" for k, v in reasons.items()))
    if doc["labels"]:
        lines.append("  labels on RECOMMENDED: " + ", ".join(f"{k} {v}" for k, v in doc["labels"].items()))
    lines.append("  decision-v1 -> state-v2:")
    for old, row in doc["crosswalk"].items():
        lines.append(f"    {old:16s} " + ", ".join(f"{k} {v}" for k, v in row.items()))
    lines.append(f"  unclassified: {doc['unclassified']}")
    for r in doc["unclassified_rows"]:
        lines.append(f"    #{r['decision_id']} {r['checkpoint']} fixture {r['fixture_id']} {r['market_key']} {r['selection']} {r['line']}: "
                     f"reasons {r['reasons']}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        day = parse_day(args.day)
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on") as conn:
        doc, code = run(conn, day=day)
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n" if args.as_json else render(doc))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
