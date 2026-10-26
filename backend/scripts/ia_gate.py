"""Gate A of the Plan Maestro IA (section 24), from the command line: the verdict of the end of phase 0, read from the ledger.

    python -m scripts.ia_gate evaluate               # the verdict for the seven complete days that ended yesterday (writes nothing)
    python -m scripts.ia_gate evaluate --record      # the same, and a PASA or NO PASA is appended to ai.feature_gates (gate_a)
    python -m scripts.ia_gate evaluate --json        # the whole report (every check with its figures) as JSON
    python -m scripts.ia_gate evaluate --through 2026-11-03   # a window that ended on that day (to look back; never recorded)
    python -m scripts.ia_gate evaluate --changed-on 2026-11-02   # a deploy that changed what the layer does that day (repeatable)
    python -m scripts.ia_gate revert batch --reason "expired 3 %"   # «se revierte el interruptor que falle»: batch | native_schema | cache_layout

Run it where the worker runs (it has the variables the manual-actions check reads - names and numbers only, never a key). The verdict is
``PASA``, ``NO PASA``, ``PENDIENTE POR TIEMPO REAL`` (fewer than seven complete days with the configuration stable) or ``PENDIENTE POR
ACCIONES MANUALES`` (evidence or an action of the owner is missing). Nothing is simulated: a pending verdict is not recorded and is not
evidence. ``--dsn`` overrides the database (the worker's own by default).

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

from fbi.ai import gate_a
from fbi.ai.config import AiSettings
from fbi.core.version import code_version

COMMANDS = ("evaluate", "revert")
OK, NO, CANNOT, PENDING = 0, 1, 2, 3


def parse_day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a day (YYYY-MM-DD)") from exc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_gate", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("gate", nargs="?", choices=gate_a.OPTIMISATIONS, help="revert: the optimisation to switch off")
    ap.add_argument("--through", help="evaluate: the last day of the window (default: yesterday, Bogotá time); never recorded")
    ap.add_argument("--changed-on", action="append", default=[], metavar="YYYY-MM-DD",
                    help="evaluate: a day the configuration changed in a way the ledger cannot show (a deploy); the window starts "
                         "after the latest one. It can only delay the gate")
    ap.add_argument("--record", action="store_true", help="evaluate: append a PASA or NO PASA to ai.feature_gates")
    ap.add_argument("--json", action="store_true", dest="as_json", help="evaluate: print the whole report as JSON")
    ap.add_argument("--reason", help="revert: why (kept in the gate's evidence)")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run(command: str, conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, through: date | None = None,
        changes: Sequence[date] = (), record: bool = False, gate: str | None = None, reason: str | None = None,
        version: str | None = None, baseline: tuple[date, date] | None = None) -> tuple[dict[str, Any], int]:
    """One command: its report (JSON-ready) and its exit status. The connection is the caller's; what a command writes it commits.
    ``baseline``: the days the coverage and the unit cost are compared with - the 16 and 7 days of ``IA_BASELINE_F0.md`` when None
    (a test's world has its own)."""
    if command == "revert":
        if gate is None or not reason or not reason.strip():
            return {"error": "revert needs the optimisation and --reason"}, CANNOT
        reverted = gate_a.revert(conn, gate, reason=reason.strip(), at=at, code_version=version)
        conn.commit()
        return {"reverted": gate, "row": reverted, "reason": reason.strip()[:300]}, OK
    if record and through is not None:
        return {"error": "--record is only for the window that ended yesterday: a verdict looked at from the past is not recorded"}, CANNOT
    try:
        report = gate_a.evaluate(conn, settings, at=at, through=through, changes=changes,
                                 baseline_coverage=baseline or gate_a.BASELINE_COVERAGE_DAYS,
                                 baseline_unit=baseline or gate_a.BASELINE_UNIT_DAYS)
    except ValueError as exc:
        return {"error": str(exc)}, CANNOT
    doc = report.as_json()
    doc["lines"] = report.lines()
    if report.verdict == gate_a.PASS:
        code = OK
    elif report.verdict == gate_a.FAIL:
        code = NO
    else:
        code = PENDING
    if record:
        row = gate_a.record(conn, report, code_version=version)
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
        doc, code = run(args.command, conn, settings, at=at, through=through, changes=changes, record=args.record, gate=args.gate,
                        reason=args.reason, version=code_version())
    if args.command == "evaluate" and not args.as_json and "lines" in doc:
        sys.stdout.write("\n".join(doc["lines"]) + "\n")
        if doc.get("recorded_row") is not None:
            sys.stdout.write(f"Registrado en ai.feature_gates (gate_a), fila {doc['recorded_row']}.\n")
        elif doc.get("recorded_note"):
            sys.stdout.write(f"No se registra: {doc['recorded_note']}.\n")
    else:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    if code == CANNOT and "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
