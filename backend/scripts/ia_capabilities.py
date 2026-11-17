"""The registry of capabilities (IA-056, AD-003), from the command line.

    python -m scripts.ia_capabilities list                     # every capability: state, verdicts, gates, warnings (writes nothing)
    python -m scripts.ia_capabilities list --json              # the same as JSON (what GET /admin/intelligence/capabilities serves)
    python -m scripts.ia_capabilities history --key council    # the chain of one capability (writes nothing)
    python -m scripts.ia_capabilities sync                     # what the code catalog would register (writes nothing)
    python -m scripts.ia_capabilities sync --write             # register it: a NEW capability enters at «construida» (system)
    python -m scripts.ia_capabilities propose --key readers --to en_sombra --safety "PENDIENTE POR ACCIONES MANUALES" \\
        --validation "PENDIENTE POR DEPENDENCIAS" --reason "..."          # the PLAN of a move: checked, printed, NOT written
    python -m scripts.ia_capabilities propose ... --write      # the same, appended (decided_by = 'system'; never «autorizada»)
    python -m scripts.ia_capabilities propose --key council --to autorizada --safety PASA --safety-evidence '{"gate": "battery", ...}' \\
        --validation VALIDADO --sample 412 --validation-evidence '{...}' --reason "..." \\
        --signature "Autorizo el Council, el dueño, 2026-12-01" --confirm-owner   # THE OWNER'S ACTION

Rules (``fbi.intel.capabilities``): no state is skipped forward; «autorizada» only with ``--confirm-owner`` and the owner's signature, and
a safety PASA; a safety NO PASA keeps a capability at «construida»; a measured validation carries ``--sample``; nothing moves forward
while a gate it answers to says NO PASA. Every row of the owner (``--confirm-owner``) carries ``--signature``. The registry switches
nothing: authorising is a signature, not a switch. ``--dsn`` overrides the database (the worker's own by default).

Exit status: 0 done (or nothing to do), 1 refused by the rules (nothing written), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg

from fbi.core.version import code_version
from fbi.intel import capabilities as registry

COMMANDS = ("list", "history", "sync", "propose")
OK, REFUSED, USAGE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_capabilities", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--key", help="history/propose: the capability")
    ap.add_argument("--to", dest="to_state", choices=registry.STATES, help="propose: the state it moves to (or stays in, new verdicts)")
    ap.add_argument("--safety", choices=registry.SAFETY, help="propose: the safety verdict")
    ap.add_argument("--safety-evidence", default="{}", help="propose: the safety evidence, a JSON object")
    ap.add_argument("--validation", choices=registry.VALIDATION, help="propose: the validation verdict")
    ap.add_argument("--validation-evidence", default="{}", help="propose: the validation evidence, a JSON object")
    ap.add_argument("--sample", type=int, help="propose: the validation's sample (required with VALIDADO, NO VALIDADO, INSUFICIENTE)")
    ap.add_argument("--observed", default="{}", help="propose: what was seen (rows, switch words), a JSON object")
    ap.add_argument("--reason", help="propose: why (kept with the row)")
    ap.add_argument("--signature", help="propose --confirm-owner: the owner's signature, in their own words")
    ap.add_argument("--confirm-owner", action="store_true", help="propose: I am the owner and I sign this row (needed for autorizada)")
    ap.add_argument("--write", action="store_true", help="sync/propose: append (without it, only the plan is printed)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def _object(text: str, name: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} is not JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def proposal(args: argparse.Namespace) -> registry.Proposal:
    """The row the arguments describe (raises ValueError on what argparse cannot check)."""
    missing = [flag for flag, value in (("--key", args.key), ("--to", args.to_state), ("--safety", args.safety),
                                        ("--validation", args.validation), ("--reason", args.reason)) if value is None]
    if missing:
        raise ValueError(f"propose needs {', '.join(missing)}")
    if args.signature is not None and not args.confirm_owner:
        raise ValueError("--signature belongs to the owner's row: add --confirm-owner")
    return registry.Proposal(
        key=args.key, to_state=args.to_state, safety=args.safety, validation=args.validation, reason=args.reason,
        safety_evidence=_object(args.safety_evidence, "--safety-evidence"),
        validation_evidence=_object(args.validation_evidence, "--validation-evidence"), validation_sample=args.sample,
        observed=_object(args.observed, "--observed"), decided_by="owner" if args.confirm_owner else "system",
        owner_signature=args.signature if args.confirm_owner else None)


def list_lines(view: dict[str, Any]) -> list[str]:
    lines = [f"Registro de capacidades ({view['version']}), {view['at']}: "
             + ", ".join(f"{s} {n}" for s, n in view["by_state"].items())]
    for c in view["capabilities"]:
        sample = c["validation"]["sample"]
        lines.append(f"- {c['key']} [{c['piece']}] {c['state'] or 'SIN REGISTRAR'} · seguridad {c['safety']['verdict']} · validación "
                     f"{c['validation']['verdict']}{'' if sample is None else f' (n = {sample})'} · interruptor {c['switch'] or '—'}")
        lines.extend(f"    ! {w}" for w in c["warnings"])
    if view["not_in_code"]:
        lines.append(f"En la base y no en el código: {', '.join(view['not_in_code'])}")
    return lines


def run(conn: psycopg.Connection[Any], args: argparse.Namespace, *, at: datetime, version: str | None) -> tuple[dict[str, Any], int]:
    """The answer (JSON-ready, with its lines) and the exit status. Writes (and commits) only with ``--write``."""
    if args.command == "list":
        view = registry.overview(conn, at=at)
        return {**view, "lines": list_lines(view)}, OK
    if args.command == "history":
        if not args.key:
            return {"error": "history needs --key"}, USAGE
        rows = registry.history(conn, args.key)
        return {"key": args.key, "rows": rows, "lines": [
            f"{r['id']}: {r['from_state'] or '—'} -> {r['to_state']} · {r['safety']} · {r['validation']}"
            f"{'' if r['validation_sample'] is None else ' (n = ' + str(r['validation_sample']) + ')'} · {r['decided_by']}"
            f"{' (firmada)' if r['signed'] else ''} · {r['at']:%Y-%m-%d %H:%M} UTC · {r['reason']}" for r in rows]}, OK
    if args.command == "sync":
        plan = registry.sync_plan(registry.catalog_rows(conn))
        planned = [{"key": c.key, "version": v, "supersedes": s} for c, s, v in plan]
        if not args.write or not plan:
            return {"planned": planned, "written": [], "lines": [f"Pendiente de registrar: {p['key']} (versión {p['version']})"
                                                                 for p in planned] or ["Nada que registrar."]}, OK
        written = registry.sync(conn, at=at, code_version=version)
        conn.commit()
        return {"planned": planned, "written": written, "lines": [f"Registrada: {w['key']} (versión {w['version']})" for w in written]}, OK
    try:
        p = proposal(args)
    except ValueError as exc:
        return {"error": str(exc)}, USAGE
    if p.to_state == registry.AUTHORISED and not args.confirm_owner:
        return {"error": f"{registry.AUTHORISED} is the owner's action: add --confirm-owner and --signature (nothing was written)"}, REFUSED
    tip = registry.tip_of(registry.tips(conn).get(p.key))
    cap = registry.BY_KEY.get(p.key)
    live = {g: str(v["verdict"]) for g, v in registry.live_gates(conn, cap.safety_gates if cap else ()).items()}
    found = registry.problems(tip, p, live_safety=live)
    plan_doc = {"key": p.key, "from": None if tip is None else tip.state, "to": p.to_state, "safety": p.safety,
                "validation": p.validation, "sample": p.validation_sample, "decided_by": p.decided_by,
                "live_safety": live, "problems": found}
    if found:
        return {**plan_doc, "error": "refused: " + "; ".join(found) + " (nothing was written)"}, REFUSED
    if not args.write:
        return {**plan_doc, "lines": [f"Plan (no escrito): {p.key} {plan_doc['from'] or '—'} -> {p.to_state}. Añade --write para anotarlo."]}, OK
    try:
        row = registry.record(conn, p, at=at, confirmed_by_owner=bool(args.confirm_owner), code_version=version)
    except (ValueError, PermissionError, psycopg.errors.IntegrityError) as exc:
        conn.rollback()
        return {**plan_doc, "error": f"refused: {exc} (nothing was written)"}, REFUSED
    conn.commit()
    return {**plan_doc, "recorded_row": row,
            "lines": [f"Anotado en intel.capability_transitions, fila {row}: {p.key} {plan_doc['from'] or '—'} -> {p.to_state}."]}, OK


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.command != "propose" and (args.to_state or args.safety or args.validation or args.reason or args.signature
                                      or args.confirm_owner or args.sample is not None):
        ap.error("--to, --safety, --validation, --sample, --reason, --signature and --confirm-owner belong to propose")
    if args.write and args.command not in ("sync", "propose"):
        ap.error("--write belongs to sync and propose")
    from fbi.core.config import settings as platform

    writes = args.write and args.command in ("sync", "propose")
    options = "-c TimeZone=UTC" if writes else "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=60000"
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=options) as conn:
        doc, code = run(conn, args, at=datetime.now(UTC), version=code_version())
        conn.rollback()  # what it wrote, it committed
    if args.as_json or "lines" not in doc:
        sys.stdout.write(json.dumps({k: v for k, v in doc.items() if k != "lines"}, indent=1, default=str, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write("\n".join(doc["lines"]) + "\n")
    if "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
