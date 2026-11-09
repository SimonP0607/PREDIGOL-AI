"""The ``chronicle_review`` job: a pass of ``fbi.chronicle.review.run`` as a run of the ledger (IA-023, stage A of the single flow).

Like ``fbi.narrative.job`` it opens the ledger's run itself (the import is inside the function so that ``fbi.chronicle`` keeps out of the
import cycle of the ingestion layer); Intelligence never reads it. Database only: no model, no provider, no cost."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
import structlog

from fbi.chronicle import review

log = structlog.get_logger(__name__)

JOB = "chronicle_review"
"""The name the ledger, the watchdog and the worker know the job by."""
NOTES_LIMIT = 1000


def run_job(conn: psycopg.Connection[Any], *, at: datetime, commit: bool = True) -> review.RunReport:
    """One pass: the chronicles of the matches that finished long enough ago and were not reviewed yet. A pass that found nothing due
    leaves no row in the ledger (the worker runs it every hour; a quiet hour, or one with matches only waiting for data, is the usual one). A pass that wrote is a run with its counts;
    matches still waiting for line-ups or minutes are in its notes and, quietly, in the log of the worker."""
    from fbi.ingestion.ledger import RunCounters, RunLedger

    report = review.run(conn, at=at)
    if commit:
        conn.commit()
    if not report.written:
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"version": review.VERSION, "limit": review.LIMIT})
    counters = RunCounters()
    counters.rows_inserted = report.written
    counters.rows_normalized = report.due
    ledger.close(run_id, counters, notes=json.dumps({"due": report.due, "written": report.written, "waiting": report.waiting,
                                                     "firm": report.firm, "contradicted": report.contradicted,
                                                     "version": review.VERSION})[:NOTES_LIMIT])
    if commit:
        conn.commit()
    return report
