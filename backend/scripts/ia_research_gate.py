"""The gate of research v2 (Plan Maestro IA, phase 2; the research part of Gate B, section 24), from the command line: the verdict of the week in
which research v2 ran in shadow beside v1, read from the ledger.

    python -m scripts.ia_research_gate evaluate               # the verdict for the seven complete days that ended yesterday (writes nothing)
    python -m scripts.ia_research_gate evaluate --record      # the same, and a PASA or NO PASA is appended to ai.feature_gates (research_v2)
    python -m scripts.ia_research_gate evaluate --json        # the whole report (every check with its figures) as JSON
    python -m scripts.ia_research_gate evaluate --through 2026-11-10   # a window that ended on that day (to look back; never recorded)
    python -m scripts.ia_research_gate evaluate --changed-on 2026-11-02   # a deploy that changed what research v2 does that day (repeatable)

Run it where the worker runs. The verdict is ``PASA``, ``NO PASA`` or ``PENDIENTE POR TIEMPO REAL`` (fewer than seven complete days in which
every pass of the cycle ran research v2 in shadow, or a check that has no data to be judged). Nothing is simulated: a pending verdict is not
recorded and is not evidence. ``--dsn`` overrides the database (the worker's own by default).

Recording a ``PASA`` switches nothing by itself: ``FBI_AI_RESEARCH_V2=on`` is the owner's word and it holds only while the NEWEST row of this
gate says ``PASA`` (``fbi.ai.gates.research_mode``) - a ``NO PASA`` re-run puts research v2 back in shadow without anybody touching the switch.

Exit status: 0 PASA, 1 NO PASA, 2 could not run (usage error or a day that is not complete), 3 pending.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from fbi.ai import gate_research
from fbi.ai.config import AiSettings
from fbi.core.version import code_version

COMMANDS = ("evaluate",)
OK, NO, CANNOT, PENDING = 0, 1, 2, 3


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_research_gate", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--through", help="evaluate: the last day of the window (default: yesterday, Bogotá time); never recorded")
    ap.add_argument("--changed-on", action="append", default=[], metavar="YYYY-MM-DD",
                    help="evaluate: a day research v2 changed in a way the ledger cannot show (a deploy); the window starts after the latest "
                         "one. It can only delay the gate")
    ap.add_argument("--record", action="store_true", help="evaluate: append a PASA or NO PASA to ai.feature_gates")
    ap.add_argument("--json", action="store_true", dest="as_json", help="evaluate: print the whole report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run(command: str, conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, through: date | None = None,
        changes: Sequence[date] = (), record: bool = False, version: str | None = None) -> tuple[dict[str, Any], int]:
    """One command: its report (JSON-ready) and its exit status. The connection is the caller's; what a command writes it commits."""
    if command not in COMMANDS:
        return {"error": f"unknown command {command!r}"}, CANNOT
    if record and through is not None:
        return {"error": "--record is only for the window that ended yesterday: a verdict looked at from the past is not recorded"}, CANNOT
    try:
        report = gate_research.evaluate(conn, settings, at=at, through=through, changes=changes)
    except ValueError as exc:
        return {"error": str(exc)}, CANNOT
    doc = report.as_json()
    doc["lines"] = report.lines()
    if report.verdict == gate_research.PASS:
        code = OK
    elif report.verdict == gate_research.FAIL:
        code = NO
    else:
        code = PENDING
    if record:
        row = gate_research.record(conn, report, code_version=version)
        conn.commit()
        doc["recorded_row"] = row
        if row is None:
            doc["recorded_note"] = "pending verdicts are not evidence: nothing was written"
    return doc, code


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
        doc, code = run(args.command, conn, settings, at=at, through=through, changes=changes, record=args.record, version=code_version())
    if not args.as_json and "lines" in doc:
        sys.stdout.write("\n".join(doc["lines"]) + "\n")
        if doc.get("recorded_row") is not None:
            sys.stdout.write(f"Registrado en ai.feature_gates (research_v2), fila {doc['recorded_row']}.\n")
        elif doc.get("recorded_note"):
            sys.stdout.write(f"No se registra: {doc['recorded_note']}.\n")
    else:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    if code == CANNOT and "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
