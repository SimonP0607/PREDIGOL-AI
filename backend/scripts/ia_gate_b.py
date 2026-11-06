"""Gate B of the Plan Maestro IA (section 24), from the command line: the functional shadow after 14 days, read from the database (``gate-b-v1``).

    python -m scripts.ia_gate_b evaluate               # the verdict for the fourteen complete days that ended yesterday (writes nothing)
    python -m scripts.ia_gate_b evaluate --json        # the whole report (every check with its figures, threshold and verdict) as JSON
    python -m scripts.ia_gate_b evaluate --through 2026-11-20   # a window that ended on that day (to look back)
    python -m scripts.ia_gate_b evaluate --changed-on 2026-11-12   # a deploy that changed what the shadow does that day (repeatable)

There is no ``--record``: ``ai.feature_gates`` does not accept the gate ``gate_b`` without a migration (its CHECK, last widened by 0116), and
phase P0 ships with none - recording the verdict is for a later PR. The verdict is ``PASA``, ``NO PASA``, ``PENDIENTE POR TIEMPO REAL`` (fewer
than fourteen complete days with the configuration stable, or a figure without a sample yet) or ``PENDIENTE POR ACCIONES MANUALES`` (evidence
someone has to produce, or a figure stored nowhere). Nothing is simulated. ``--dsn`` overrides the database (the worker's own by default).

Exit status: 0 PASA, 1 NO PASA, 2 could not run (usage error or a day that is not complete), 3 pending (time or manual actions).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from fbi.ai import gate_b
from fbi.ai.config import AiSettings

COMMANDS = ("evaluate",)
OK, NO, CANNOT, PENDING = 0, 1, 2, 3


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_gate_b", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--through", help="the last day of the window (default: yesterday, Bogotá time)")
    ap.add_argument("--changed-on", action="append", default=[], metavar="YYYY-MM-DD",
                    help="a day the configuration changed in a way the database cannot show (a deploy); the window starts after the "
                         "latest one. It can only delay the gate")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the whole report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def exit_code(verdict: str) -> int:
    if verdict == gate_b.PASS:
        return OK
    if verdict == gate_b.FAIL:
        return NO
    return PENDING


def run(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, through: date | None = None,
        changes: Sequence[date] = ()) -> tuple[dict[str, Any], int]:
    """The report (JSON-ready, with its lines) and the exit status. Reads only; the connection is the caller's."""
    try:
        report = gate_b.evaluate(conn, settings, at=at, through=through, changes=changes)
    except ValueError as exc:
        return {"error": str(exc)}, CANNOT
    doc = report.as_json()
    doc["lines"] = report.lines()
    return doc, exit_code(report.verdict)


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    through: date | None = None
    changes: list[date] = []
    try:
        if args.through:
            through = parse_day(args.through)
        changes = [parse_day(text) for text in args.changed_on]
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    settings = AiSettings.from_env()
    at = datetime.now(UTC)
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        doc, code = run(conn, settings, at=at, through=through, changes=changes)
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
