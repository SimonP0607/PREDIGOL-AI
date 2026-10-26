"""The LAB's probes (Plan Maestro IA, Phase 0): the evidence that opens the ``batch`` gate and says whether the prompt cache works.

Every call here is the LAB workspace's - its own key (``FBI_AI_KEY_ANTHROPIC_LAB``), its own name in the ledger, inside its own envelope
(``FBI_AI_LAB_MONTHLY_BUDGET_USD``) - and costs cents. Run it where the worker runs, which has those variables; it never prints a key and
never reads the production key. What is missing says so, by NAME, and nothing runs half way.

    python -m scripts.ia_probe status          # what is missing and where each gate stands (no calls)
    python -m scripts.ia_probe cache           # two identical calls per tier: does the cache write and then read? (real time)
    python -m scripts.ia_probe schema          # the same question through the tool call and through structured outputs (real time)
    python -m scripts.ia_probe batch-submit    # the probe batch of the day (half price; it ends within the hour, 24 h at most)
    python -m scripts.ia_probe batch-collect   # takes the results and records the ``batch`` gate - passed or not, with its evidence

``--tiers bulk,analysis`` (the default) are the models the batches and the reviews use; ``final`` can be added. ``--dsn`` overrides the
database (the worker's own by default). ``--no-record`` on ``batch-collect`` shows the verdict without writing the gate.

Exit status: 0 done and ok, 1 done and the probe says no, 2 could not run (see ``blockers``) or usage error, 3 results still on their way
(run ``batch-collect`` again later).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, get_args

import httpx
import psycopg

from fbi.ai import budget_v3, gates, lab
from fbi.ai.batch import BatchClient
from fbi.ai.config import AiSettings, Tier
from fbi.ai.usage import UsageLedger

COMMANDS = ("status", "cache", "schema", "batch-submit", "batch-collect")
DEFAULT_TIERS = "bulk,analysis"
OK, NO, CANNOT, WAITING = 0, 1, 2, 3


def parse_tiers(text: str) -> list[Tier]:
    """``bulk,analysis`` -> the tiers, in order, without repeats; a name that is not a tier is a usage error."""
    known = get_args(Tier)
    out: list[Tier] = []
    for name in (part.strip() for part in text.split(",") if part.strip()):
        if name not in known:
            raise ValueError(f"unknown tier {name!r} (the tiers are {', '.join(known)})")
        tier: Tier = name  # type: ignore[assignment]
        if tier not in out:
            out.append(tier)
    if not out:
        raise ValueError("no tier given")
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_probe", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--tiers", default=DEFAULT_TIERS, help="comma separated (default: %(default)s)")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    ap.add_argument("--run", help="batch-collect: the run to take (default: the newest)")
    ap.add_argument("--no-record", action="store_true", help="batch-collect: show the verdict, do not write the gate")
    return ap


def status(conn: psycopg.Connection[Any], settings: AiSettings, tiers: Sequence[Tier], *, at: datetime) -> dict[str, Any]:
    """What stands between the LAB and a probe, and what the gates say today. Names and states only: no value of a variable."""
    day = budget_v3.lab_day(conn, at=at, settings=settings)
    return {"at": at.isoformat(), "lab_key": "anthropic" in settings.lab_keys, "lab_envelope_usd": str(settings.lab_monthly_budget),
            "lab_tiers": {t: (None if (tm := settings.tier(t, lab=True)) is None else tm.model) for t in tiers},
            "lab_month": day.as_json() | {"can_spend": day.can_spend},
            "blockers": lab.blockers(settings, tiers), "optimisations": gates.describe(conn, settings)}


def run(command: str, conn: psycopg.Connection[Any], settings: AiSettings, *, tiers: Sequence[Tier], at: datetime,
        run_id: str | None = None, record: bool = True, ledger: UsageLedger | None = None, client: BatchClient | None = None,
        transport: httpx.BaseTransport | None = None) -> tuple[dict[str, Any], int]:
    """One command: its report and its exit status. The connection is the caller's; whatever a command writes it commits."""
    if command == "status":
        report = status(conn, settings, tiers, at=at)
        return report, CANNOT if report["blockers"] else OK
    if command == "cache":
        report = lab.probe_cache(conn, settings, at=at, tiers=tiers, ledger=ledger, transport=transport)
    elif command == "schema":
        report = lab.probe_schema(conn, settings, at=at, tiers=tiers, ledger=ledger, transport=transport)
    elif command == "batch-submit":
        report = lab.probe_batch_submit(conn, settings, at=at, tiers=tiers, ledger=ledger, client=client, transport=transport)
        conn.commit()
        if report.get("blockers"):
            return report, CANNOT
        return report, NO if report.get("failed") or report.get("error") else OK
    else:
        report = lab.probe_batch_collect(conn, settings, at=at, run=run_id, ledger=ledger, client=client, transport=transport,
                                         record=record)
        conn.commit()
        if report.get("state") == "waiting":
            return report, WAITING
        if report.get("state") == "nothing_submitted":
            return report | {"blockers": ["no probe batch was sent: run batch-submit first"]}, CANNOT
        return report, OK if report.get("passed") else NO
    conn.commit()
    if report.get("blockers"):
        return report, CANNOT
    return report, OK if report.get("ok") else NO


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        tiers = parse_tiers(args.tiers)
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    settings = AiSettings.from_env()
    at = datetime.now(UTC)
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        report, code = run(args.command, conn, settings, tiers=tiers, at=at, run_id=args.run, record=not args.no_record)
    sys.stdout.write(json.dumps(report, indent=1, default=str, ensure_ascii=False) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
