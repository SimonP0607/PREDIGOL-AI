"""The panel of the gates of the plan and the value per dollar of each component of the AI, from the command line (IA-050; ``gates-panel-v1``).

    python -m scripts.ia_gates_panel show                                   # the panel, in Spanish
    python -m scripts.ia_gates_panel show --json                            # the whole panel as JSON (the shape the admin view will read)
    python -m scripts.ia_gates_panel show --cost-days 7                     # the cost of the last 7 whole UTC days (14 by default)
    python -m scripts.ia_gates_panel show --cost-since 2026-10-28 --cost-until 2026-11-11   # the cost over whole UTC days ([since, until))

Reads only, and writes nothing in any mode: the connection is opened read-only (``default_transaction_read_only``, a ``statement_timeout`` of
95 s) and every statement runs in ONE snapshot (``REPEATABLE READ``). The evaluators of Gate B and of research v2 run as their own scripts run
them without ``--record``: nothing is recorded, switched or published, and the panel changes no gate, threshold or verdict. Every gate of the plan
with its status, its figures and their intervals, its threshold, the day it can be judged and where each figure comes from; the newest row of
every gate of ``ai.feature_gates``; and each component of the AI with its cost (``cost-paths-v1``), its measured benefit and its value per
dollar where that benefit is demonstrated. ``--dsn`` overrides the database (the worker's own by default).

Exit status: 0 the panel was made and no pending gate shows as approved; 1 it was made and that rule failed (a defect: it must never happen);
2 could not run (a usage error).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import psycopg

from fbi.ai import cost_paths, cost_paths_readers, gates_panel
from fbi.ai import gates_panel_readers as readers
from fbi.ai.config import AiSettings

COMMANDS = ("show",)
DEFAULT_COST_DAYS = 14
OK, BROKEN, CANNOT = 0, 1, 2
OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=95000"
"""Read-only and bounded, whatever the server's defaults: a write is refused by the database itself."""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_gates_panel", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="show", choices=COMMANDS)
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the whole panel as JSON")
    ap.add_argument("--cost-days", type=int, default=DEFAULT_COST_DAYS, help="the cost window: whole UTC days ending today (default 14)")
    ap.add_argument("--cost-since", type=date.fromisoformat, default=None, help="first day of the cost window (UTC, YYYY-MM-DD)")
    ap.add_argument("--cost-until", type=date.fromisoformat, default=None, help="the day after the last one (UTC, YYYY-MM-DD); today by default")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def cost_window(days: int, since: date | None, until: date | None, *, now: datetime) -> tuple[datetime, datetime]:
    """Whole UTC days: ``[since, until)``, by default the ``days`` that ended at today's 00:00 UTC."""
    if since is None and days <= 0:
        raise ValueError(f"--cost-days must be positive ({days})")
    end = datetime.combine(until or now.astimezone(UTC).date(), time(0), tzinfo=UTC)
    start = end - timedelta(days=days) if since is None else datetime.combine(since, time(0), tzinfo=UTC)
    if end <= start:
        raise ValueError(f"the cost window is empty ({start.isoformat()} to {end.isoformat()})")
    if end > now:
        raise ValueError(f"the cost window ends after now ({end.isoformat()}): it measures whole days")
    return start, end


def collect(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, since: datetime, until: datetime) -> dict[str, Any]:
    """The whole panel from ONE snapshot (the caller's transaction): the gates, the evidence rows and the cost of the window."""
    inputs = readers.read(conn, settings, at=at)
    got = cost_paths_readers.read(conn, since=since, until=until)
    cost = cost_paths.report(got.calls, got.links, got.routes, got.lab_items, ledger=got.ledger, user_ledger=got.user_ledger, since=since,
                             until=until)
    days = (until - since).total_seconds() / 86400
    return gates_panel.panel(dataclasses.replace(inputs, cost=cost, cost_days=days))


def exit_code(doc: dict[str, Any]) -> int:
    return OK if doc.get("rule_holds") and not doc.get("violations") else BROKEN


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = datetime.now(UTC)
    try:
        since, until = cost_window(args.cost_days, args.cost_since, args.cost_until, now=now)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return CANNOT
    from fbi.core.config import settings as platform

    settings = AiSettings.from_env()
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        conn.read_only = True
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        with conn.transaction():
            doc = collect(conn, settings, at=now, since=since, until=until)
    if args.as_json:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write("\n".join(gates_panel.lines(doc)) + "\n")
    code = exit_code(doc)
    if code == BROKEN:
        sys.stderr.write("the rule failed: " + "; ".join(doc.get("violations") or []) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
