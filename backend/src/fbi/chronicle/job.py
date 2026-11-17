"""The ``chronicle_review`` job: a pass of ``fbi.chronicle.review.run`` as a run of the ledger (IA-023, stage A of the single flow).

Like ``fbi.narrative.job`` it opens the ledger's run itself (the import is inside the function so that ``fbi.chronicle`` keeps out of the
import cycle of the ingestion layer); Intelligence never reads it. Database only: no model, no provider, no cost."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
import structlog

from fbi.chronicle import review, review_v2

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
    if not report.written and not report.failed:
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"version": review.VERSION, "limit": review.LIMIT})
    counters = RunCounters()
    counters.rows_inserted = report.written
    counters.errors = report.failures[:5]
    counters.rows_normalized = report.due
    ledger.close(run_id, counters, notes=json.dumps({"due": report.due, "written": report.written, "waiting": report.waiting,
                                                     "firm": report.firm, "contradicted": report.contradicted,
                                                     "failed": report.failed, "failures": report.failures[:3],
                                                     "version": review.VERSION})[:NOTES_LIMIT])
    if commit:
        conn.commit()
    return report


JOB_V2 = review_v2.JOB
"""``chronicle-review-v2`` (IA-118): the single chronicle judged on its cited facts, only while ``FBI_CHRONICLE_REVIEW_V2=shadow``."""


def run_v2_job(conn: psycopg.Connection[Any], *, at: datetime, commit: bool = True) -> review_v2.RunReport:
    """One pass of ``chronicle-review-v2``, with its ledger row only when it wrote or failed. Off: nothing is read."""
    if review_v2.mode() == "off":
        return review_v2.RunReport()
    from fbi.ingestion.ledger import RunCounters, RunLedger

    report = review_v2.run(conn, at=at)
    if commit:
        conn.commit()
    if not report.written and not report.failed:
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB_V2, params={"version": review_v2.VERSION, "metrics": review_v2.METRICS_VERSION, "limit": review_v2.LIMIT})
    counters = RunCounters()
    counters.rows_inserted = report.written
    counters.errors = report.failures[:5]
    counters.rows_normalized = report.due
    ledger.close(run_id, counters, notes=json.dumps({"due": report.due, "written": report.written, "waiting": report.waiting,
                                                     "unsupported": report.unsupported, "firm": report.firm,
                                                     "contradicted": report.contradicted, "failed": report.failed,
                                                     "version": review_v2.VERSION})[:NOTES_LIMIT])
    if commit:
        conn.commit()
    return report
