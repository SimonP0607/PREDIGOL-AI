"""The ``referee_identity`` job: a pass of ``fbi.people.referees.build`` as a run of the ledger (plan F3).

It lives here and not in ``fbi.people`` because the run ledger is the ingestion layer's: the people package stays below it
(``tests/unit/test_architecture.py`` keeps the import graph from growing a loop through it).

A pass reads the facts already stored and writes only the difference, so most hours it writes nothing and leaves no row in the
ledger. The daily sweep also audits the result and says so in the log when something is off: a referee left without
spellings, an alias on a merged referee, matches with a referee in the facts and none placed, a pass that would still write."""

from __future__ import annotations

from typing import Any

import psycopg
import structlog

from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.people import referees

log = structlog.get_logger(__name__)

JOB = referees.JOB
MIN_PLACED_SHARE = 0.95
"""The criterion of the plan: at least this share of the matches with a referee in the facts has a referee id."""


def run_job(conn: psycopg.Connection[Any], *, sweep: bool = False, commit: bool = True, wait: bool = False) -> referees.BuildReport:
    """The scheduled job. ``sweep`` (once a day) also audits and logs. ``commit=False`` leaves the transaction to the caller
    (a test). ``wait`` is for a person at the console: take the lock and wait for it instead of giving way to the worker."""
    report = referees.build(conn, apply=True, wait=wait)
    if commit:
        conn.commit()
    if sweep:
        _audit(conn, commit=commit)
    if report.skipped_locked or not report.changed:
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"version": report.version, "sweep": sweep})
    counters = RunCounters()
    counters.rows_inserted = report.new_referees + report.new_aliases + report.officials_to_write + report.candidates_added
    counters.rows_updated = report.renamed + report.candidates_changed + report.candidates_removed
    counters.rows_normalized = report.fixtures
    ledger.close(run_id, counters, notes=str(report.as_dict())[:2000])
    return report


def problems_of(result: dict[str, Any]) -> list[str]:
    """What an audit result says is wrong (empty when all is well): the criteria of the plan and the invariants of the tables."""
    found = referees.broken_invariants(result)
    if result["placed_share"] < MIN_PLACED_SHARE:
        found.append("placed_share")
    if any(result["pass_would_write"].values()):
        found.append("pass_would_write")
    return found


def _audit(conn: psycopg.Connection[Any], *, commit: bool = True) -> dict[str, Any]:
    result = referees.audit(conn)
    if commit:
        conn.commit()
    problems = problems_of(result)
    (log.warning if problems else log.info)("referee_identity.audit", problems=problems, **{
        k: v for k, v in result.items() if k != "pass_would_write"}, pass_would_write=result["pass_would_write"])
    return result
