"""Gate B of the Plan Maestro IA (section 24), from the command line: the functional shadow after 14 days, read from the database (``gate-b-v1``).

    python -m scripts.ia_gate_b evaluate               # the verdict for the fourteen complete days that ended yesterday (writes nothing)
    python -m scripts.ia_gate_b evaluate --record      # the same, and a PASA or NO PASA is appended to ai.feature_gates (gate_b)
    python -m scripts.ia_gate_b evaluate --json        # the whole report (every check with its figures, threshold and verdict) as JSON
    python -m scripts.ia_gate_b evaluate --through 2026-11-20   # a window that ended on that day (to look back; never recorded)
    python -m scripts.ia_gate_b evaluate --changed-on 2026-11-12   # a deploy that changed what the shadow does that day (repeatable)

    python -m scripts.ia_gate_b set-lab-plan --days 2 --reason "..." --confirm-owner   # THE OWNER'S ACTION: the LAB days planned to exclude

    python -m scripts.ia_gate_b close --not-evaluated --reason "..."                   # preview of the owner's closure (writes nothing)
    python -m scripts.ia_gate_b close --not-evaluated --reason "..." --confirm-owner   # THE OWNER'S ACTION: Gate B closed as NO EVALUADO

``--record`` appends ``PASA`` or ``NO PASA`` only (``decided_by = 'script'``, the whole report as evidence with its hash); a pending verdict is
not evidence and writes nothing. ``set-lab-plan`` is the owner's action, never the code's: it appends a ``lab_plan`` row (``decided_by =
'owner'``) with the number of excluded LAB days planned at the start of the shadow and why, and refuses without ``--confirm-owner``. Gate B
reads the newest one; without it the LAB check stays ``PENDIENTE POR ACCIONES MANUALES``. The verdict is ``PASA``, ``NO PASA``, ``PENDIENTE POR TIEMPO REAL`` (fewer
than fourteen complete days with the configuration stable, or a figure without a sample yet) or ``PENDIENTE POR ACCIONES MANUALES`` (evidence
someone has to produce, or a figure stored nowhere). Nothing is simulated. ``--dsn`` overrides the database (the worker's own by default).

``close`` (AD-001, IA-055) is the owner's action too: it appends ONE row of ``gate_b`` (``passed = false``, ``decided_by = 'owner'``,
evidence ``gate-b-closure-v1``) that says ``NO EVALUADO — ventana interrumpida por decisión del dueño``, with the owner's reason and the
informative cut that ``evaluate`` (read-only) gives at that instant; no measurement is altered. Without ``--confirm-owner`` (or with
``--dry-run``) it is a preview on a read-only connection and writes nothing. Once a closure is on file a second ``close`` writes nothing and
says which row it found, and ``evaluate --record`` records nothing more of ``gate-b-v1``. With the closure ``set-lab-plan`` is no longer
needed (the command stays, for the record and for a later gate).

Exit status: 0 PASA, 1 NO PASA, 2 could not run (usage error or a day that is not complete), 3 pending (time or manual actions);
``set-lab-plan``: 0 written, 2 nothing written; ``close``: 0 closed (now, or already on file: nothing written twice), 2 nothing written
(usage), 3 preview (nothing written, waiting for ``--confirm-owner``).
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
from fbi.core.version import code_version

COMMANDS = ("evaluate", "set-lab-plan", "close")
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
    ap.add_argument("--record", action="store_true", help="evaluate: append a PASA or NO PASA to ai.feature_gates (never a pending verdict)")
    ap.add_argument("--days", type=int, help="set-lab-plan: the number of LAB days planned to be excluded at the start of the shadow")
    ap.add_argument("--reason", help="set-lab-plan / close: why (kept with the plan or the closure)")
    ap.add_argument("--confirm-owner", action="store_true",
                    help="set-lab-plan / close: I am the owner and I write this (without it nothing is written)")
    ap.add_argument("--not-evaluated", action="store_true",
                    help="close: Gate B is closed as NO EVALUADO, its window interrupted by the owner's decision (the only closure there is)")
    ap.add_argument("--dry-run", action="store_true", help="close: show what would be written and write nothing (implied without --confirm-owner)")
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
        changes: Sequence[date] = (), record: bool = False, version: str | None = None) -> tuple[dict[str, Any], int]:
    """The report (JSON-ready, with its lines) and the exit status. The connection is the caller's; with ``record`` a PASA or NO PASA is
    appended and committed, and a pending verdict writes nothing."""
    if record and through is not None:
        return {"error": "--record is only for the window that ended yesterday: a verdict looked at from the past is not recorded"}, CANNOT
    try:
        report = gate_b.evaluate(conn, settings, at=at, through=through, changes=changes)
    except ValueError as exc:
        return {"error": str(exc)}, CANNOT
    doc = report.as_json()
    doc["lines"] = report.lines()
    if record:
        closed = gate_b.closure(conn)
        row = None if closed is not None else gate_b.record(conn, report, code_version=version)
        conn.commit()
        doc["recorded_row"] = row
        if closed is not None:
            doc["recorded_note"] = (f"the owner closed gate-b-v1 as {gate_b.NOT_EVALUATED} (ai.feature_gates, row {closed.row}): "
                                    "nothing more of it is recorded, nothing was written")
        elif row is None:
            doc["recorded_note"] = "pending verdicts are not evidence: nothing was written"
    return doc, exit_code(report.verdict)


def closure_lines(c: gate_b.Closure, *, written: bool) -> list[str]:
    head = (f"Cierre registrado en ai.feature_gates (gate_b, {gate_b.CLOSURE_KIND}), fila {c.row}, firmado por el dueño."
            if written else f"Gate B ya estaba cerrado: fila {c.row} de ai.feature_gates ({c.at.isoformat()}). No se escribe otro cierre.")
    return [f"GATE B · {gate_b.NOT_EVALUATED_ES}", head, f"Motivo: {c.reason}",
            f"Corte informativo adjunto (gate-b-v1, solo lectura): {c.cut_verdict} — información, no evidencia del gate.",
            "Las mediciones no se alteran: es una fila añadida; ninguna fila anterior de ai.feature_gates ni de intel.audit_checks cambia."]


def close(conn: psycopg.Connection[Any], settings: AiSettings, *, not_evaluated: bool, reason: str | None, confirm_owner: bool,
          dry_run: bool, at: datetime, version: str | None = None) -> tuple[dict[str, Any], int]:
    """THE OWNER'S ACTION (AD-001): close ``gate-b-v1`` as NO EVALUADO. Without ``--confirm-owner``, or with ``--dry-run``, a PREVIEW: the row
    that would be written, with the informative cut of this instant, and nothing written (exit 3). With it, the row is appended and committed
    (exit 0); when a closure is already on file nothing is written and the existing row is shown (exit 0)."""
    if not not_evaluated:
        return {"error": "close needs --not-evaluated: Gate B is closed as NO EVALUADO, never as a pass or a failure (nothing was written)"}, CANNOT
    if reason is None or not reason.strip():
        return {"error": "close needs --reason \"...\" (nothing was written)"}, CANNOT
    existing = gate_b.closure(conn)
    if existing is not None:
        conn.rollback()
        return {"verdict": gate_b.NOT_EVALUATED, "already_closed": True, "recorded_row": None, "closure": existing.as_json(),
                "lines": closure_lines(existing, written=False)}, OK
    if dry_run or not confirm_owner:
        try:
            report = gate_b.evaluate(conn, settings, at=at)
            evidence = gate_b.closure_evidence(report, reason=reason)
        except ValueError as exc:
            conn.rollback()
            return {"error": f"{exc} (nothing was written)"}, CANNOT
        conn.rollback()
        why = "--dry-run" if dry_run else "sin --confirm-owner"
        return {"verdict": gate_b.NOT_EVALUATED, "preview": True, "recorded_row": None,
                "would_write": {"table": "ai.feature_gates", "gate": gate_b.GATE, "passed": False, "decided_by": "owner", "evidence": evidence},
                "lines": [f"VISTA PREVIA ({why}): no se ha escrito nada.", f"GATE B · {gate_b.NOT_EVALUATED_ES}",
                          f"Se escribiría UNA fila de ai.feature_gates: gate_b, passed=false, decided_by=owner, {gate_b.CLOSURE_KIND}.",
                          f"Motivo: {evidence['reason']}", f"Corte informativo de este instante (gate-b-v1, solo lectura): {report.verdict}",
                          *[f"    {line}" for line in report.lines()],
                          "Para firmar el cierre, repite el comando con --confirm-owner."]}, PENDING
    try:
        c, written = gate_b.record_closure(conn, settings, reason=reason, at=at, confirmed_by_owner=True, code_version=version)
    except ValueError as exc:
        conn.rollback()
        return {"error": f"{exc} (nothing was written)"}, CANNOT
    conn.commit()
    return {"verdict": gate_b.NOT_EVALUATED, "already_closed": not written, "recorded_row": c.row if written else None,
            "closure": c.as_json(), "lines": closure_lines(c, written=written)}, OK


def set_lab_plan(conn: psycopg.Connection[Any], *, days: int | None, reason: str | None, confirm_owner: bool, at: datetime,
                 version: str | None = None) -> tuple[dict[str, Any], int]:
    """THE OWNER'S ACTION: append the plan of the LAB (``decided_by = 'owner'``) and commit. Nothing is written without ``--confirm-owner``,
    ``--days`` and ``--reason``."""
    if not confirm_owner:
        return {"error": "set-lab-plan is the owner's action: add --confirm-owner to write it (nothing was written)"}, CANNOT
    if days is None or reason is None:
        return {"error": "set-lab-plan needs --days N and --reason \"...\" (nothing was written)"}, CANNOT
    try:
        row = gate_b.record_lab_plan(conn, days=days, reason=reason, at=at, confirmed_by_owner=True, code_version=version)
    except ValueError as exc:
        conn.rollback()
        return {"error": f"{exc} (nothing was written)"}, CANNOT
    conn.commit()
    plan = gate_b.lab_plan(conn, at)
    return {"recorded_row": row, "plan": None if plan is None else plan.as_json(),
            "lines": [f"Plan del LAB registrado en ai.feature_gates (lab_plan), fila {row}: {days} día(s) excluido(s) previsto(s)."]}, OK


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
    if args.command == "evaluate" and (args.days is not None or args.reason is not None or args.confirm_owner):
        ap.error("--days, --reason and --confirm-owner belong to set-lab-plan and close")
    if args.command != "evaluate" and (args.record or through is not None or changes):
        ap.error("--record, --through and --changed-on belong to evaluate")
    if args.command != "close" and (args.not_evaluated or args.dry_run):
        ap.error("--not-evaluated and --dry-run belong to close")
    if args.command == "close" and args.days is not None:
        ap.error("--days belongs to set-lab-plan")
    from fbi.core.config import settings as platform

    if args.command == "set-lab-plan" and not args.confirm_owner:
        sys.stderr.write("set-lab-plan is the owner's action: add --confirm-owner to write it (nothing was written)\n")
        return CANNOT
    if args.command == "close" and (not args.not_evaluated or not (args.reason or "").strip()):
        sys.stderr.write("close needs --not-evaluated and --reason \"...\" (nothing was written)\n")
        return CANNOT
    settings = AiSettings.from_env()
    at = datetime.now(UTC)
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        if args.command == "set-lab-plan":
            doc, code = set_lab_plan(conn, days=args.days, reason=args.reason, confirm_owner=args.confirm_owner, at=at, version=code_version())
        elif args.command == "close":
            conn.read_only = args.dry_run or not args.confirm_owner  # a preview cannot write, even by mistake
            doc, code = close(conn, settings, not_evaluated=args.not_evaluated, reason=args.reason, confirm_owner=args.confirm_owner,
                              dry_run=args.dry_run, at=at, version=code_version())
        else:
            doc, code = run(conn, settings, at=at, through=through, changes=changes, record=args.record, version=code_version())
            conn.rollback()  # what it wrote, it committed
    if not args.as_json and "lines" in doc:
        sys.stdout.write("\n".join(doc["lines"]) + "\n")
        if args.command == "evaluate" and doc.get("recorded_row") is not None:
            sys.stdout.write(f"Registrado en ai.feature_gates (gate_b), fila {doc['recorded_row']}.\n")
        elif doc.get("recorded_note"):
            sys.stdout.write(f"No se registra: {doc['recorded_note']}.\n")
    else:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    if code == CANNOT and "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
