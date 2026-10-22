"""The ``player_history`` job: a pass over the clubs and national-team caps of the players and over the careers of the coaches, as a run of
the ledger (plan F3).

It lives here and not in ``fbi.people`` because the run ledger is the ingestion layer's: the people package stays below it
(``tests/unit/test_architecture.py`` keeps the import graph from growing a loop through it).

A pass reads the facts already stored and writes only the difference, so most passes write nothing and leave no row in the ledger. The
scheduled one looks at the players of recent matches, transfers and squad lists; the daily sweep looks at everyone (which also catches
what arrived late: the statistics of an old match, a backfill) and then audits the tables and says so in the log when something is off:
streaks out of order, a cap of a match not played or of a team that is not a senior national side, a career tied to the wrong person
or club, a pass that would still write."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
import structlog

from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.people import coach_links, player_history

log = structlog.get_logger(__name__)

JOB = player_history.JOB


@dataclass(slots=True)
class JobReport:
    """What one run did: the pass over the players and the pass over the coaches."""

    history: player_history.BuildReport
    coaches: coach_links.BuildReport

    @property
    def changed(self) -> bool:
        return self.history.changed or self.coaches.changed

    @property
    def skipped_locked(self) -> bool:
        """Both passes gave way to a person's build (a run that did only one of them is not 'skipped')."""
        return self.history.skipped_locked and self.coaches.skipped_locked

    def as_dict(self) -> dict[str, Any]:
        return {"history": self.history.as_dict(), "coaches": self.coaches.as_dict()}


def run_job(conn: psycopg.Connection[Any], *, sweep: bool = False, commit: bool = True, wait: bool = False) -> JobReport:
    """The scheduled job. ``sweep`` (once a day) looks at everyone and also audits and logs. ``commit=False`` leaves the transaction
    to the caller (a test). ``wait`` is for a person at the console: take the locks and wait for them instead of giving way to the
    worker."""
    history = player_history.build(conn, apply=True, wait=wait, sweep=sweep)
    if commit:
        conn.commit()
    coaches = coach_links.build(conn, apply=True, wait=wait)
    if commit:
        conn.commit()
    report = JobReport(history, coaches)
    if sweep:
        _audit(conn, commit=commit)
    if not report.changed:
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"version": history.version, "sweep": sweep})
    counters = RunCounters()
    counters.rows_inserted = history.spells_written + history.caps_written + coaches.persons_created
    counters.rows_updated = coaches.careers_coach_linked + coaches.careers_team_linked
    counters.rows_normalized = history.players + history.fixtures
    ledger.close(run_id, counters, notes=str(report.as_dict())[:2000])
    return report


def problems_of(result: dict[str, Any]) -> list[str]:
    """What an audit result says is wrong (empty when all is well): the invariants of the tables and a pass that would still write."""
    found = [f"history.{name}" for name in player_history.broken_invariants(result["history"])]
    found += [f"coaches.{name}" for name in coach_links.broken_invariants(result["coaches"])]
    for part in ("history", "coaches"):
        if any(result[part]["pass_would_write"].values()):
            found.append(f"{part}.pass_would_write")
    return found


def _audit(conn: psycopg.Connection[Any], *, commit: bool = True) -> dict[str, Any]:
    result = {"history": player_history.audit(conn), "coaches": coach_links.audit(conn)}
    if commit:
        conn.commit()
    problems = problems_of(result)
    (log.warning if problems else log.info)(
        "player_history.audit", problems=problems,
        history={k: v for k, v in result["history"].items() if k != "pass_would_write"},
        history_pass_would_write=result["history"]["pass_would_write"],
        coaches={k: v for k, v in result["coaches"].items() if k != "pass_would_write"},
        coaches_pass_would_write=result["coaches"]["pass_would_write"])
    return result
