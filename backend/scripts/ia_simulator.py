"""The joint match simulator in shadow (``sim-v1``, IA-013), from the command line: the simulator against the models in force.

    python -m scripts.ia_simulator check --day 2026-11-07
    python -m scripts.ia_simulator check --day 2026-11-07 --json

``check`` takes every fixture of that day (Bogotá time) with model predictions in force (``models.predictions``: the newest real-time
forecast of each model, as of now and never after kick-off), recovers each goal model's expected goals from its own fixed rows, builds
the joint distribution by halves, derives every stored market from it and reports the largest and mean absolute differences per model
and market; and it lists every incoherence in the stored numbers themselves (sums, double chance and handicaps against the 1X2,
monotone lines, the BTTS / over-under bounds). See ``fbi.simulator.consistency``.

Read-only: the connection refuses writes, nothing is asked of a provider or a model, and nothing here is read by a decision, a pick, a
forecast or a page. Exit 0 with a report, 2 when it cannot run (a bad argument).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from fbi.simulator import consistency

OK, CANNOT = 0, 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_simulator", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("check",))
    ap.add_argument("--day", required=True, help="the day of the kick-offs, YYYY-MM-DD (Bogotá)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def check(conn: psycopg.Connection[Any], the_day: date, *, now: datetime) -> tuple[dict[str, Any], int]:
    return consistency.check_day(conn, the_day, now=now), OK


def render(doc: dict[str, Any]) -> str:
    c = doc["constants"]
    lines = [f"{doc['version']} (shadow) day {doc['day']}: {doc['fixtures_with_predictions']} of {doc['fixtures_of_the_day']} fixtures "
             f"with predictions in force; {doc['incoherences']} incoherence(s) in the stored numbers "
             f"(max {c['max_half_goals']} goals per side and half, first-half share {c['first_half_share_home']:g}/"
             f"{c['first_half_share_away']:g}, tolerance {c['tolerance']:g})"]
    for model, markets in doc["markets"].items():
        lines.append(f"  {model}")
        for market, s in markets.items():
            lines.append(f"    {market:<22} n={s['n']:<5} max |diff| {s['max_abs']:.2e}  mean {s['mean_abs']:.2e}")
    for f in doc["fixtures"]:
        for m in f["models"]:
            if m["incoherences"] or m.get("status") != "compared":
                lines.append(f"  fixture {f['fixture_id']} {m['model']} v{m['version_id']}: {m.get('status')}"
                             + (f" ({m['reason']})" if m.get("reason") else ""))
                lines += [f"    {i['rule']}: {i['detail']}" for i in m["incoherences"]]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        the_day = date.fromisoformat(args.day)
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on") as conn:
        doc, code = check(conn, the_day, now=datetime.now(UTC))
    sys.stdout.write((json.dumps(doc, indent=1, default=str, ensure_ascii=False) if args.as_json else render(doc)) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
