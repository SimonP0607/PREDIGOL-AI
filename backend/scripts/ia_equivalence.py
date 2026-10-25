"""The equivalence test of the optimisations (Plan Maestro IA, Phase 0, gate A): does asking for a review with structured outputs, or with
the match's common block first, change the verdict more than asking the same thing twice?

The plan's rule: «cambio de veredicto con las optimizaciones ≤ el de repetir la misma llamada, sobre ≥ 200 paquetes guardados». The inputs are
reviews the layer already made (the packet and the candidate as they were); each one is asked four times in the LAB, through the Message
Batches route (half price): twice as today (A1, A2), with structured outputs (B) and with the common block first (C). Nothing of it is a review,
a pick or a state of production. Every call is the LAB workspace's - its own key and its own envelope - and the whole experiment is paid for
(or refused) before the first request: it costs about US$14 of the LAB's US$15 a month in phases 0-2.

    python -m scripts.ia_equivalence plan      # how many inputs, what it would cost, whether the LAB can pay (no calls)
    python -m scripts.ia_equivalence submit    # sends the experiment as ONE batch, all or nothing (the same day it finds what is sent)
    python -m scripts.ia_equivalence collect   # takes the results; with every ask closed, decides and records the two gates
    python -m scripts.ia_equivalence status    # the newest experiment: asks still open, what the gates say

Options: ``--tier analysis`` (the model whose reviews are replayed; the gates name it, another model is not covered), ``--inputs 210``,
``--since-days 21``, ``--experiment ID`` (collect: default the newest), ``--no-record`` (collect: show the verdict, write nothing),
``--dsn``. The verdict of each variant is PASA, NO PASA or INSUFICIENTE and the evidence keeps every input's verdicts, so anyone can
recompute it. A failing re-run closes a gate that a passing one opened; every attempt is a row of ``ai.feature_gates``.

Exit status: 0 done and the verdicts pass, 1 done and one does not, 2 could not run (see ``blockers``) or usage error, 3 results still on
their way (run ``collect`` again later).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
from psycopg.rows import tuple_row

from fbi.ai import gates, lab
from fbi.ai.batch import BatchClient
from fbi.ai.config import AiSettings, Tier
from fbi.ai.usage import UsageLedger

COMMANDS = ("plan", "submit", "collect", "status")
OK, NO, CANNOT, WAITING = 0, 1, 2, 3
TIERS = ("bulk", "analysis", "final")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_equivalence", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--tier", choices=TIERS, default="analysis", help="default: %(default)s")
    ap.add_argument("--inputs", type=int, default=lab.MIN_INPUTS + 10,
                    help=f"stored reviews to replay (at least {lab.MIN_INPUTS}; default: %(default)s)")
    ap.add_argument("--since-days", type=int, default=21, help="how far back the stored reviews are taken (default: %(default)s)")
    ap.add_argument("--experiment", help="collect/status: the experiment to take (default: the newest)")
    ap.add_argument("--no-record", action="store_true", help="collect: show the verdicts, do not write the gates")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def newest_experiment(conn: psycopg.Connection[Any]) -> str | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(lab.LATEST_EXPERIMENT_SQL, {"version": lab.EQUIVALENCE_VERSION})
        row = cur.fetchone()
    return None if row is None or row[0] is None else str(row[0])


def status(conn: psycopg.Connection[Any], settings: AiSettings, *, experiment: str | None, at: datetime) -> dict[str, Any]:
    """The experiment as the ledger knows it (asks per state) and the gates it feeds."""
    experiment = experiment or newest_experiment(conn)
    states: dict[str, int] = {}
    if experiment is not None:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT status, count(*) FROM ai.batch_items WHERE purpose = 'other' AND prompt_version = %s "
                        "AND context ->> 'experiment' = %s GROUP BY status ORDER BY status", (lab.EQUIVALENCE_VERSION, experiment))
            states = {str(s): int(n) for s, n in cur.fetchall()}
    return {"at": at.isoformat(), "experiment": experiment, "asks_by_state": states,
            "gates": {g: gates.gate_state(conn, g).as_json() for g in ("batch", "native_schema", "cache_layout")}}


def run(command: str, conn: psycopg.Connection[Any], settings: AiSettings, *, tier: Tier, at: datetime, inputs: int = lab.MIN_INPUTS + 10,
        since_days: int = 21, experiment: str | None = None, record: bool = True, ledger: UsageLedger | None = None,
        client: BatchClient | None = None, transport: httpx.BaseTransport | None = None) -> tuple[dict[str, Any], int]:
    """One command: its report and its exit status. The connection is the caller's; whatever a command writes it commits."""
    if command == "status":
        return status(conn, settings, experiment=experiment, at=at), OK
    if command in ("plan", "submit"):
        report = lab.equivalence_submit(conn, settings, at=at, tier=tier, n=inputs, since_days=since_days, ledger=ledger,
                                        client=client, transport=transport, dry_run=command == "plan")
        conn.commit()
        if report.get("blockers"):
            return report, CANNOT
        if command == "plan":
            return report, OK
        return report, NO if report.get("failed") or report.get("error") else OK
    report = lab.equivalence_collect(conn, settings, at=at, experiment=experiment, ledger=ledger, client=client, transport=transport,
                                     record=record)
    conn.commit()
    state = report.get("state")
    if state == "waiting":
        return report, WAITING
    if state == "nothing_submitted":
        return report | {"blockers": ["no experiment was sent: run submit first"]}, CANNOT
    verdicts = [v.get("verdict") for v in report.get("variants", {}).values()]
    return report, OK if verdicts and all(v == "PASA" for v in verdicts) else NO


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.inputs < lab.MIN_INPUTS:
        ap.error(f"--inputs: the plan asks for at least {lab.MIN_INPUTS} stored reviews")
    from fbi.core.config import settings as platform

    settings = AiSettings.from_env()
    at = datetime.now(UTC)
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        report, code = run(args.command, conn, settings, tier=args.tier, at=at, inputs=args.inputs, since_days=args.since_days,
                           experiment=args.experiment, record=not args.no_record)
    sys.stdout.write(json.dumps(report, indent=1, default=str, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
