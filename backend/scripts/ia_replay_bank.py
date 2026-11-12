"""The replay bank of the deliberations (IA-047, plan piece INT-C02): stored runs of the shadow asked again, as they were asked,
through the LAB's Message Batches route - without touching the shadow, its sample, the switches, the envelopes or the anchor of
Gate B (``fbi.ai.replay``; the owner's guide is ``docs/owner/IA_047_BANCO_REPETICION.md``).

    python -m scripts.ia_replay_bank build                 # which stored runs can be rebuilt byte for byte, and why the others cannot
    python -m scripts.ia_replay_bank build --write         # the same, appended to ai.replay_bank_items (no cost)
    python -m scripts.ia_replay_bank plan                  # what a run would ask (each admitted run twice) and cost, and why it may not be sent
    python -m scripts.ia_replay_bank run                   # the plan again: nothing is sent without the owner's word
    python -m scripts.ia_replay_bank run --confirm-owner   # ONE batch of the LAB, all or nothing (needs the protocol INT-C02 registered)
    python -m scripts.ia_replay_bank report                # collects what came back and gives the verdict of each scope

Options: ``--days N`` (the complete Bogotá days before today whose runs are read; 14 by default) or ``--since`` / ``--until``
(YYYY-MM-DD, Bogotá); ``--scope`` (repeatable: ``match/context``, ``match/evaluation``, ``stats/evaluation``, ``player/evaluation``,
``council/ma-v1``, ``council/ma-v1-h``, ``council/cs-v1``); ``--limit-per-scope N`` (200 by default; 0 = all), ``--seed`` (which
runs a limit keeps); ``--max-usd`` (the run's cap on its prudent cost, 5 by default, never above 15); ``--no-record`` (report:
judge what was already collected and write nothing); ``--dsn``.

``build`` without ``--write``, ``plan``, ``run`` without ``--confirm-owner`` and ``report --no-record`` open a READ-ONLY session:
they cannot write.
``report`` does not poll the provider: the worker's ``ai_batch_poll`` takes the results every five minutes.

Exit status: 0 done (``report``: every scope asked PASA), 1 ``report`` with a scope that does not pass (NO PASA or INSUFICIENTE)
or a run the provider did not take whole, 2 could not run (see ``blockers``), 3 answers still on their way.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import psycopg

from fbi.ai.calendar import day_start
from fbi.ai.config import AiSettings
from fbi.ai.replay import bank, harness

COMMANDS = ("build", "plan", "run", "report")
OK, NO, CANNOT, WAITING = 0, 1, 2, 3
READ_ONLY = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000"
WRITING = "-c TimeZone=UTC -c statement_timeout=95000"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_replay_bank", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--days", type=int, default=14, help="the complete Bogotá days before today whose stored runs are read")
    ap.add_argument("--since", type=date.fromisoformat, help="first Bogotá day read (YYYY-MM-DD); with --until it replaces --days")
    ap.add_argument("--until", type=date.fromisoformat, help="the Bogotá day the window ends BEFORE (YYYY-MM-DD; default: today)")
    ap.add_argument("--scope", action="append", choices=bank.SCOPES, help="only these scopes (repeatable)")
    ap.add_argument("--limit-per-scope", type=int, default=harness.DEFAULT_LIMIT_PER_SCOPE, help="0 = every admitted run")
    ap.add_argument("--seed", default=bank.VERSION, help="which runs a limit keeps (the same ones every time)")
    ap.add_argument("--max-usd", type=Decimal, default=harness.DEFAULT_MAX_USD, help="the run's cap on its prudent cost")
    ap.add_argument("--write", action="store_true", help="build: append what it found to ai.replay_bank_items")
    ap.add_argument("--confirm-owner", action="store_true", help="run: the owner's word to spend (else the run is its plan)")
    ap.add_argument("--no-record", action="store_true", help="report: show the verdicts, append nothing")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def window_of(args: argparse.Namespace, at: datetime) -> tuple[datetime, datetime]:
    since, until = harness.window(at, days=args.days)
    if args.until is not None:
        until = day_start(args.until)
    if args.since is not None:
        since = day_start(args.since)
    if since >= until:
        raise ValueError("the window is empty: --since must be before --until")
    return since, until


def make_build(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> bank.Build:
    runs = bank.read_runs(conn, since=since, until=until)
    return bank.build(conn, runs=runs, changed_at=bank.optimisations_changed_at(conn), since=since, until=until)


def build_report(built: bank.Build) -> dict[str, Any]:
    counts = built.counts()
    return {"bank": bank.VERSION, "since": None if built.since is None else built.since.isoformat(),
            "until": None if built.until is None else built.until.isoformat(),
            "optimisations_changed_at": None if built.optimisations_changed_at is None else built.optimisations_changed_at.isoformat(),
            "read": len(built.items) + len(built.excluded), "admitted": len(built.items), "by_scope": counts}


def execute(command: str, conn: psycopg.Connection[Any], settings: AiSettings, args: argparse.Namespace, *, at: datetime
            ) -> tuple[dict[str, Any], int]:
    """One command: its report and its exit status. The connection is the caller's; whatever a command writes it commits."""
    if command == "report":
        out = harness.report(conn, at=at, record=not args.no_record)
        conn.commit()
        if out.get("state") == "nothing_submitted":
            return out | {"blockers": ["no run of the bank was sent: run plan, then run --confirm-owner"]}, CANNOT
        if out.get("state") == "waiting":
            return out, WAITING
        verdicts = [s.get("verdict") for s in out.get("scopes", {}).values()]
        return out, OK if verdicts and all(v == "PASA" for v in verdicts) else NO
    since, until = window_of(args, at)
    built = make_build(conn, since=since, until=until)
    summary = build_report(built)
    if command == "build":
        if args.write:
            ids = harness.write_bank(conn, built, at=at)
            conn.commit()
            summary["written"] = len(ids)
        return summary, OK
    p = harness.plan(conn, settings, built, at=at, scopes=args.scope, limit_per_scope=args.limit_per_scope or None, seed=args.seed,
                     max_usd=args.max_usd)
    if command == "plan":
        return {"build": summary, "plan": p.as_json()}, CANNOT if p.blockers else OK
    out = harness.submit(conn, settings, built, p, confirmed_by_owner=bool(args.confirm_owner))
    out = {"build": summary, "run": out}
    if out["run"].get("dry_run"):
        return out, CANNOT if p.blockers else OK
    if out["run"].get("blockers"):
        return out, CANNOT
    return out, NO if out["run"].get("failed") or out["run"].get("error") else OK


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    from fbi.core.config import settings as platform

    writes = ((args.command == "build" and args.write) or (args.command == "run" and args.confirm_owner)
              or (args.command == "report" and not args.no_record))
    settings = AiSettings.from_env()
    at = datetime.now(UTC)
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=WRITING if writes else READ_ONLY) as conn:
        try:
            report, code = execute(args.command, conn, settings, args, at=at)
        except ValueError as exc:
            report, code = {"blockers": [str(exc)]}, CANNOT
    sys.stdout.write(json.dumps(report, indent=1, default=str, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
