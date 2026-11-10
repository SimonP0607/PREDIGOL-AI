"""decision-v2 (the one Decision & Risk Engine, in shadow) replayed against decision-v1 and decision-fam-v1 (plan IA, P1, IA-012). Read-only.

    python -m scripts.ia_decision_v2 replay --day 2026-11-05            # every decision of the day (Bogotá), recomputed as of its moment
    python -m scripts.ia_decision_v2 replay --day 2026-11-05 --json
    python -m scripts.ia_decision_v2 replay --day 2026-11-05 --council ma-v1    # plus the Council's typed adjustment (ctx-adj-v1)
    python -m scripts.ia_decision_v2 replay --day 2026-11-05 --signals          # plus the market's signals as risk inputs
    python -m scripts.ia_decision_v2 replay --day 2026-11-05 --view             # plus how far each probability is from the common view

The agreement per family, the confusion table (decision-v1's state read through state-v2 against decision-v2's), and every disagreement with
the stage that caused it (``fbi.decision.replay``). Without ``--council`` and ``--signals`` it is the equivalence of the engine: the evidence of
the P1 gate. The connection is read-only: nothing is written. Exit status: 0 a report, 2 it cannot run (a bad day or option).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg

from fbi.decision import replay
from fbi.intel.context_adjustment import ENGINES

COMMANDS = ("replay",)
OK, CANNOT = 0, 2


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_decision_v2", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--day", required=True, help="the day (Bogotá) whose decisions are replayed")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--council", choices=ENGINES, help="give the context stage the Council's typed adjustment of this engine")
    ap.add_argument("--signals", action="store_true", help="give the risk stage the market's signals")
    ap.add_argument("--view", action="store_true", help="measure each probability against the common probability view (shadow)")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run(conn: psycopg.Connection[Any], *, day: date, council: str | None = None, signals: bool = False, view: bool = False) -> tuple[dict[str, Any], int]:
    """The report (JSON-ready) and the exit status. The connection is the caller's; nothing is written."""
    return replay.replay_day(conn, day=day, council=council, signals=signals, view=view), OK


def render(doc: dict[str, Any]) -> str:
    a = doc["agreement"]
    overall = "-" if a["rate"] is None else f"{a['rate']:.2%}"
    lines = [f"{doc['version']} replayed against {', '.join(doc['versions'])}, {doc['day']}: {doc['rows']} rows in {doc['moments']} moments "
             f"(skipped: {doc['skipped']['selection_copies']} copies of the day's picks, {doc['skipped']['unclaimed']} unclaimed)",
             f"  inputs: council {doc['inputs']['council'] or 'none'}, signals {'yes' if doc['inputs']['signals'] else 'no'}",
             f"  agreement: {a['agree']}/{a['n']} ({overall}), {a['unmatched']} not rebuilt"]
    for name, f in doc["families"].items():
        rate = "-" if f["rate"] is None else f"{f['rate']:.2%}"
        lines.append(f"  {name:11s} {f['agree']:5d}/{f['n']:<5d} {rate:>8s}  not rebuilt {f['unmatched']}, labels {f['labels']['agree']}/"
                     f"{f['labels']['n']}, checkpoints {f['checkpoints']['agree']}/{f['checkpoints']['n']}")
    lines.append("  decision-v1 (state-v2) -> decision-v2:")
    for old, row in doc["confusion"].items():
        lines.append(f"    {old:12s} " + ", ".join(f"{k} {v}" for k, v in row.items()))
    lines.append(f"  disagreements: {len(doc['disagreements'])}")
    for d in doc["disagreements"]:
        lines.append(f"    #{d['decision_id']} {d['family']} {d['known_at']} {d['checkpoint']} fixture {d['fixture_id']} {d['market_key']} "
                     f"{d['selection']} {d['line']}: v1 {d['v1_state']} ({d['v1_state2']}) v2 {d['v2_state']} - stage {d['stage']}: "
                     f"{d['v2_why']}")
    if "common_view" in doc:
        c = doc["common_view"]
        lines.append(f"  common view: {c['with_view']}/{c['rows']} rows have a reading; of {c['with_v1_probability']} with a calibrated probability in "
                     f"decision-v1, {c['within_tolerance']} within {c['tolerance_pp']} pp (median {c['median_pp']}, p90 {c['p90_pp']}, max {c['max_pp']}); "
                     f"view calibration {c['view_calibration']}")
        for cause, v in c["causes"].items():
            lines.append(f"    {cause:18s} {v['selections']:5d} selections, median {v['median_pp']}, max {v['max_pp']}, over tolerance {v['over_tolerance']}")
    for u in doc["unmatched"]:
        lines.append(f"    #{u['decision_id']} {u['family']} {u['known_at']} fixture {u['fixture_id']} {u['market_key']} {u['selection']} "
                     f"{u['line']}: not rebuilt")
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
        doc, code = run(conn, day=day, council=args.council, signals=args.signals, view=args.view)
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False, sort_keys=True) + "\n" if args.as_json else render(doc))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
