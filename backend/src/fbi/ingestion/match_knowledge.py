"""The ``match_knowledge`` job: a pass of ``fbi.knowledge.builder.refresh_pending`` as a run of the ledger (plan F7).

It lives here and not in ``fbi.knowledge`` because the run ledger is the ingestion layer's: the knowledge package stays below it
(``tests/unit/test_architecture.py`` keeps the import graph from growing a loop through it). Database only: no request to the provider."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
import structlog

from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.knowledge import builder, layers
from fbi.knowledge import events as ev

log = structlog.get_logger(__name__)

JOB = builder.JOB
"""``match_knowledge``: the name the ledger, the watchdog and the worker know the job by."""
NOTES_LIMIT = 2000


def run_job(conn: psycopg.Connection[Any], *, now: datetime, days: int = builder.DEFAULT_DAYS, max_seconds: float = 240.0,
            limit: int | None = 300, commit: bool = True) -> builder.BuildReport:
    """The scheduled job: a pass of ``refresh_pending`` as a ledger run - but only when it built, failed or was cut short, so a quiet
    half hour (every match built from what it still is) leaves no row in the ledger. The worker runs it every half hour over the last
    ``days`` days with a budget, and once a day over a much wider window (the sweep: a result the provider corrects weeks after the
    match, a rule that changed, a match that was missed).

    It never raises for a match: a match that fails is the report's ``failed`` and the others go on. What can raise is the database."""
    report = builder.refresh_pending(conn, now=now, days=days, max_seconds=max_seconds, limit=limit, commit=commit)
    if commit:
        conn.commit()
    wide = days > builder.DEFAULT_DAYS
    if wide:
        log.info("match_knowledge.sweep", days=days, seen=report.seen, due=report.due, built=report.built, failed=report.failed,
                 stopped=report.stopped, left=report.left, seconds=round(report.seconds, 1))
    if not (report.built or report.failed or report.stopped):
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"days": days, "limit": limit, "max_seconds": max_seconds, "layers": layers.VERSION,
                                      "events": ev.VERSION, "sweep": wide})
    counters = RunCounters()
    counters.rows_inserted = report.built
    counters.rows_updated = report.kinds
    counters.rows_normalized = report.seen
    counters.errors.extend(report.errors[:5])
    if report.stopped:
        counters.stopped_early = f"{report.stopped}: {report.left} matches left for the next pass"
    ledger.close(run_id, counters, notes=json.dumps(report.as_dict(), default=str)[:NOTES_LIMIT])
    if commit:
        conn.commit()
    return report
