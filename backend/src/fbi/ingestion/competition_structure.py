"""The ``competition_structure`` job: a pass of ``fbi.competitions.builder.refresh_pending`` as a run of the ledger (plan F2).

It lives here and not in ``fbi.competitions`` because the run ledger is the ingestion layer's: the competitions package
stays below it (``tests/unit/test_architecture.py`` keeps the import graph from growing a loop through it)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
import structlog

from fbi.competitions import builder
from fbi.competitions import stages as stg
from fbi.competitions import ties as tl
from fbi.ingestion.ledger import RunCounters, RunLedger

log = structlog.get_logger(__name__)

JOB = builder.JOB


def run_job(conn: psycopg.Connection[Any], *, now: datetime, max_seconds: float = 120.0, limit: int | None = 400,
            commit: bool = True, everything: bool = False) -> builder.BuildReport:
    """The scheduled job: a pass of ``refresh_pending`` as a ledger run - but only when it changed or broke something, so a
    quiet hour leaves no row in the ledger. The worker runs it every few minutes with a budget, and once a day with
    ``everything`` (no limit, a longer budget): the sweep that reads every season, whatever its age."""
    report = builder.refresh_pending(conn, now=now, max_seconds=max_seconds, limit=limit, commit=commit, everything=everything)
    if commit:
        conn.commit()
    if everything:
        log.info("competition_structure.sweep", seasons=report.seasons, changed=report.changed, failed=report.failed,
                 left=report.seasons_left)
    if not (report.changed or report.failed):
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"limit": limit, "max_seconds": max_seconds, "stages": stg.VERSION, "ties": tl.VERSION,
                                      "sweep": everything})
    counters = RunCounters()
    counters.rows_inserted = report.rows_written
    counters.rows_updated = report.fixtures_updated
    counters.rows_normalized = report.seasons
    counters.errors.extend(report.errors[:5])
    if report.stopped_for_time:
        counters.stopped_early = f"time budget of {max_seconds:g} s reached: {report.seasons_left} seasons left for the next pass"
    ledger.close(run_id, counters, notes=str(report.as_dict())[:2000])
    return report
