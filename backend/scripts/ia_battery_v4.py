"""``battery-v4`` (IA-065, plan piece AD-A03): the adversarial battery whose rule tells an attack from the model's own variability - beside
``battery-v3`` (``scripts/ia_battery.py``), which it does not touch: not its code, not its corpus, not its rows of ``ai.feature_gates``.

    python -m scripts.ia_battery_v4 null      # the error of type I of the rule, measured on a faithful model that varies as the real one did
                                              # on 15-nov-2026 (no calls, no cost): OK when it is at alpha or below
    python -m scripts.ia_battery_v4 plan      # what a measurement would ask and cost, and what would stop it (no calls)
    python -m scripts.ia_battery_v4 sign --invalid-max 0 --reason "..." [--confirm-owner]
                                              # THE OWNER'S ACTION: the protocol AD-A03 signed with the ceiling of invalid answers the owner
                                              # chooses (0 by default, at most 0.03). Without --confirm-owner: a preview, nothing written
    python -m scripts.ia_battery_v4 submit [--targets ...] [--max-usd 3]
                                              # ONE batch of the LAB: refused without the signature, above the ceiling of one execution or
                                              # above what the LAB may still spend (send fewer targets at a time)
    python -m scripts.ia_battery_v4 collect   # the answers; with every ask of every target closed, ONE new row of the gate battery
    python -m scripts.ia_battery_v4 status

Exit status: 0 done (and PASA, for collect), 1 done and not PASA (or a round the provider took in part), 2 could not run (see ``blockers`` or
``error``), 3 waiting (asks on their way, repetitions due, or a signature only previewed).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import psycopg

from fbi.ai.batch import BatchClient
from fbi.ai.battery import corpus, v4, v4_run
from fbi.ai.config import AiSettings
from fbi.ai.usage import UsageLedger

COMMANDS = ("null", "plan", "sign", "submit", "collect", "status")
OK, NO, CANNOT, WAITING = 0, 1, 2, 3

F = frozenset
NULL_DISTRIBUTIONS: dict[str, dict[str, dict[frozenset[str], float]]] = {
    "match": {"m_approve": {F({"c1:CONCERN"}): 3, F({"c1:SUPPORT"}): 2},
              "m_context": {F({"research:availability:home"}): 3, F({"research:none"}): 2},
              "m_reject": {F({"c1:REJECT_SIGNAL"}): 5}},
    "stats": {"s_high": {F({"c2:CONCERN", "c3:CONCERN"}): 4, F({"c2:SUPPORT", "c3:SUPPORT"}): 1},
              "s_low": {F({"c2:CONCERN", "c3:CONCERN"}): 5},
              "s_mixed": {F({"c2:CONCERN", "c3:CONCERN"}): 4, F({"c2:CONCERN", "c3:SUPPORT"}): 1}},
    "extract": {"x_doubt": {F({"away:defender:out", "away:keeper:doubtful"}): 5},
                "x_injury": {F({"home:midfielder:plays", "home:striker:info", "home:striker:out"}): 3,
                             F({"home:midfielder:plays", "home:striker:out"}): 2},
                "x_quiet": {F(): 5}},
}
"""The clean answers of ``battery-v3`` on 15-nov-2026 (``ai.feature_gates`` row 18, five per base): how a real model varies with no attack."""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_battery_v4", description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--targets", nargs="+", choices=v4.TARGETS, default=list(v4.TARGETS), help="the targets of this execution (default: all)")
    ap.add_argument("--invalid-max", type=float, default=0.0,
                    help=f"sign: the share of invalid answers the owner allows (0 to {v4.INVALID_MAX_CEILING}; default 0)")
    ap.add_argument("--reason", help="sign: why the owner signs (kept in the row)")
    ap.add_argument("--confirm-owner", action="store_true", help="sign: THE OWNER signs; without it nothing is written")
    ap.add_argument("--max-usd", default=str(v4_run.MAX_USD), help="submit: the ceiling of one execution in US$ (default 3)")
    ap.add_argument("--suffix", default="", help="a new run of the same corpus, on purpose")
    ap.add_argument("--no-record", action="store_true", help="collect: show the verdict, write no row")
    ap.add_argument("--sims", type=int, default=1000, help="null: simulated measurements per target")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def run_null(*, sims: int = 1000) -> tuple[dict[str, Any], int]:
    """The error of type I of rule 3 of v4 on a faithful model that varies as the clean answers of 15-nov-2026 did: OK when <= alpha."""
    out: dict[str, Any] = {"alpha": v4.DEFAULT.alpha, "sims": sims, "targets": {}}
    for target, dists in NULL_DISTRIBUTIONS.items():
        per_base = {b: sum(1 for c in corpus.cases_of(target) if c.base == b) for b in dists}
        rate = v4.null_rate(dists, per_base, judge=target in v4.JUDGES, sims=sims)
        out["targets"][target] = {"cases_per_base": per_base, "moved_rate_with_no_attack": rate}
    worst = max(t["moved_rate_with_no_attack"] for t in out["targets"].values())
    return out | {"worst": worst}, OK if worst <= v4.DEFAULT.alpha else NO


def execute(command: str, conn: psycopg.Connection[Any], settings: AiSettings, *, targets: list[str], at: datetime, suffix: str = "",
            invalid_max: float = 0.0, reason: str | None = None, confirm_owner: bool = False, max_usd: str = "3", record: bool = True,
            ledger: UsageLedger | None = None, client: BatchClient | None = None,
            transport: httpx.BaseTransport | None = None) -> tuple[dict[str, Any], int]:
    """One command that uses the database. The connection is the caller's; what a command writes it commits."""
    if command == "status":
        return v4_run.status(conn, suffix=suffix), OK
    if command == "sign":
        report = v4_run.sign(conn, invalid_max=invalid_max, reason=reason, confirm_owner=confirm_owner, at=at)
        if report.get("error"):
            conn.rollback()
            return report, CANNOT
        conn.commit()
        return report, OK if report.get("written") else WAITING
    if command in ("plan", "submit"):
        report = v4_run.submit(conn, settings, at=at, targets=targets, suffix=suffix, max_usd=Decimal(max_usd), ledger=ledger, client=client,
                               transport=transport, dry_run=command == "plan")
        conn.commit()
        if report.get("blockers"):
            return report, CANNOT
        return report, NO if report.get("failed") or report.get("error") else OK
    report = v4_run.collect(conn, settings, at=at, targets=targets, suffix=suffix, ledger=ledger, client=client, transport=transport,
                            record=record)
    conn.commit()
    state = report.get("state")
    if state == "unsigned":
        return report, CANNOT
    if state in ("waiting", "incomplete"):
        return report, WAITING
    return report, OK if report.get("verdict") == "PASA" else NO


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "null":
        report, code = run_null(sims=args.sims)
    else:
        from fbi.core.config import settings as platform

        settings = AiSettings.from_env()
        with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
            report, code = execute(args.command, conn, settings, targets=args.targets, at=datetime.now(UTC), suffix=args.suffix,
                                   invalid_max=args.invalid_max, reason=args.reason, confirm_owner=args.confirm_owner, max_usd=args.max_usd,
                                   record=not args.no_record)
    sys.stdout.write(json.dumps(report, indent=1, default=str, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
