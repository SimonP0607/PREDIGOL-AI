"""The scheduled pass of the family forecasts (plan F10): the counts of the upcoming matches, as a ledger run when it wrote or failed.

A pass reads what is stored (the finished matches and their statistics, the upcoming fixtures, the catalogue) and writes the forecast table of
F5 under the version ``family-v1`` (``fbi.families.forecast``). Database only: no request to the provider, no language model, and nothing a
user sees (the page of the forecast of a match reads another version). A pass costs about a minute of CPU for every competition followed, and
most passes write nothing - a result that arrives moves a team's strength by a hair, and a market is written again only when an outcome moved by
half a point - so a quiet pass leaves no row in the ledger: the ledger shows the passes that did something or failed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
import structlog

from fbi.families import versioning
from fbi.families.forecast import (
    SPECS,
    VERSION,
    DispersionCache,
    FamilyReport,
    write_family_forecasts,
)
from fbi.ingestion.ledger import RunCounters, RunLedger

log = structlog.get_logger(__name__)

JOB = "family_forecasts"
"""The ledger job type (``raw.ingestion_runs``); the run watchdog and the worker list know it."""
NOTES_LIMIT = 4000
DISPERSIONS: DispersionCache = {}
"""The dispersions this process measured today: the first pass of the day measures them, the rest reuse them (a restart measures them again)."""


def run_job(conn: psycopg.Connection[Any], *, now: datetime, code_version: str, commit: bool = True,
            dispersions: DispersionCache | None = None) -> FamilyReport:
    """One pass: forecast the upcoming matches for every family and write what is new. Never raises for a family (the writer isolates it);
    what can raise is the database."""
    report = write_family_forecasts(conn, at=now, code_version=code_version, dispersions=DISPERSIONS if dispersions is None else dispersions)
    if commit:
        conn.commit()
    written = sum(r.rows_written for r in report.specs.values())
    failed = [f"{key}: {r.error}" for key, r in report.specs.items() if r.error]
    log.info("family_forecasts.pass", targets=report.targets, not_fit=report.not_fit, rows=written, failed=len(failed),
             **{f"{key}_markets": r.markets_written for key, r in report.specs.items()})
    if not (written or failed):
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"version": VERSION, "code": versioning.code_version(), "families": [s.spec for s in SPECS]})
    counters = RunCounters()
    counters.rows_inserted = written
    counters.rows_normalized = report.targets
    counters.errors.extend(failed[:5])
    ledger.close(run_id, counters, notes=report.summary()[:NOTES_LIMIT])
    if commit:
        conn.commit()
    return report
