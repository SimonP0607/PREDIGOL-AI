"""The replay bank as a regression test (IA-136, AD-K04): ``replay-regression-v1`` over what the bank already collected. It asks no
model and pays nothing (the answers are those of the last run of ``scripts/ia_replay_bank.py``).

    python -m scripts.ia_replay_regression check                       # per scope: verdict with the tolerance, its cause, what is due
    python -m scripts.ia_replay_regression propose                     # the tolerance as a proposal for the owner (writes nothing)
    python -m scripts.ia_replay_regression propose --write             # append it to the registry of IA-139 (pendiente de firma)
    python -m scripts.ia_replay_regression record --confirm-owner      # append the verdicts; only with the tolerance signed

``check`` and ``propose`` without ``--write`` open a READ-ONLY session. ``record`` is refused while the tolerance is not signed in the
registry (``scripts/ia_proposals.py sign``), and a scope whose stored runs an earlier regression already used is not written again: the
protocol forbids repeating to change a verdict. ``--variant`` (``same`` by default), ``--dsn``.

Exit status: 0 every scope measured PASA, 1 a scope NO PASA or INSUFICIENTE, 2 could not run or refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

import psycopg

from fbi.ai.replay import SAME, measure, regression, regression_store
from fbi.proposals import Proposal, Row
from fbi.proposals import store as register

COMMANDS: Final = ("check", "propose", "record")
OK, NO, CANNOT = 0, 1, 2
READ_ONLY: Final = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000"
WRITING: Final = "-c TimeZone=UTC -c statement_timeout=95000"
SIGNED_STATES: Final = ("firmada", "aplicada")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_replay_regression", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--variant", default=SAME)
    ap.add_argument("--write", action="store_true", help="propose: append the proposal (pendiente de firma)")
    ap.add_argument("--confirm-owner", action="store_true", help="record: the owner's word")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def proposal(report: Mapping[str, Any]) -> Proposal:
    """The tolerance as a ``umbral`` proposal: from the point rule of INT-C02 to the upper end of the interval within 5 points. Its
    evidence is the figures of ``check`` (no text)."""
    scopes = {s: {"verdict": e["regression"]["verdict"], "upper": e["regression"]["upper"],
                  "units": e["assessment"].get("complete_units"), "matches": e["assessment"].get("matches"),
                  "cause": (e.get("diagnosis") or {}).get("cause")}
              for s, e in sorted((report.get("scopes") or {}).items())}
    stamp = report.get("protocol") or {}
    evidence = {"method": regression.METHOD, "tolerance": regression.TOLERANCE, "scopes": scopes,
                "protocol": {k: stamp.get(k) for k in ("protocol", "version", "fingerprint")}}
    refs = ({"table": "ai.replay_results", "bank": str(report.get("bank")), "variant": str(report.get("variant"))},)
    return Proposal("umbral", regression.TARGET, measure.METHOD, regression.METHOD,
                    {"from": "cambios(S,R1) <= cambios(R2,R1)", "to": "extremo superior del IC95 <= 0,05", "tolerance": regression.TOLERANCE,
                     "direction": "new_rule"},
                    evidence, refs, "AD-K04: tolerancia preregistrada del banco como prueba de regresión; la firma el dueño")


def signed(rows: Sequence[Row]) -> bool:
    """Whether the owner signed THIS tolerance: a proposal of the target, with the tolerance the code has, firmada or aplicada."""
    return any(r.proposal.target == regression.TARGET and r.proposal.change.get("tolerance") == regression.TOLERANCE
               and r.status in SIGNED_STATES for r in rows)


def exit_code(report: Mapping[str, Any]) -> int:
    scopes = report.get("scopes") or {}
    if not scopes:
        return CANNOT
    return OK if all(e["regression"]["verdict"] == regression.PASS for e in scopes.values()) else NO


def run(conn: psycopg.Connection[Any], args: argparse.Namespace, *, at: datetime) -> tuple[dict[str, Any], int]:
    report = regression_store.check(conn, variant=args.variant)
    if args.command == "check":
        return report, exit_code(report)
    if args.command == "propose":
        p = proposal(report)
        doc: dict[str, Any] = {"proposal": {"kind": p.kind, "target": p.target, "from": p.current_version, "to": p.proposed_version,
                                            "change": p.change, "evidence": p.evidence, "hash": p.hash}, "written": None}
        if args.write:
            doc["written"] = register.register(conn, p)
            conn.commit()
        return doc, OK
    try:
        result = regression_store.record(conn, report, at=at, signed=signed(register.rows(conn, limit=200)))
    except (PermissionError, LookupError) as exc:
        conn.rollback()
        return {"error": str(exc), "report": report}, CANNOT
    conn.commit()
    return {"report": report, "recorded": result}, exit_code(report)


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.command == "record" and not args.confirm_owner:
        ap.error("record is the owner's action: --confirm-owner")
    from fbi.core.config import settings as platform

    writes = args.command == "record" or (args.command == "propose" and args.write)
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=WRITING if writes else READ_ONLY) as conn:
        doc, code = run(conn, args, at=datetime.now(UTC))
        conn.rollback()
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
