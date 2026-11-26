"""The book of runs of Intelligence's scheduled jobs (plan RP-1.1, finding H29).

``raw.ingestion_runs`` (the ledger) answers "what did the system do at 03:00?" with one row per run: its start, its end, its
status, its last error. The jobs of the data layer have always opened one; 33 jobs of the AI layer, the decision layer, the
evaluations, the news and the research only wrote a line in the text log, so a job that stopped or failed every pass left nothing
a person (or the console) could read. This module gives them the same row, without changing what any of them does:

* ``booked(job_type, connect)`` opens a run before the pass and closes it after, also when the pass fails or is cut;
* an error-level log line emitted inside the pass is recorded as an error of the run (the jobs catch their own failure and log it,
  so the exception never reaches the wrapper; ``fbi.core.logging`` hands each such line to ``record_error``);
* ``skip(reason)`` marks a pass that did nothing on purpose (the job's switch is off): the row is ``completed`` with
  ``params.skipped`` saying why - a run omitted with its reason, never a missing row;
* the ledger can never break a job: when it cannot be opened or closed the pass runs anyway and the failure is logged.

Statuses are the ledger's own (``completed``, ``failed``, ``interrupted``...): a pass whose job logged an error is ``failed`` (the
job's single try/except is the whole pass), a pass cut by the deadline is ``interrupted``, a pass the watchdog closed first keeps
the real outcome the close writes (``RunLedger.close``).
"""

from __future__ import annotations

import contextlib
import functools
import re
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Final, TypeVar, cast

import psycopg
import structlog
from psycopg.types.json import Json

from fbi.core.logging import add_error_sink
from fbi.ingestion.ledger import RunCounters, RunLedger

log = structlog.get_logger(__name__)

BOOKED_JOB_TYPES: Final = (
    "ai_batch_poll", "ai_cycle", "ai_daily_report", "ai_day_close", "ai_day_follow", "ai_day_start", "ai_learn",
    "ai_orchestrate", "ai_package", "ai_pick_review", "ai_requests", "ai_switches", "council_reduced_shadow",
    "decision_v2_shadow", "eval_cycle_e3", "eval_cycle_shadow", "intel_decide", "intel_nightly", "intel_weekly",
    "lifecycle_shadow", "lineup_estimate_shadow", "news_stories", "notifier", "parlay_v6_shadow", "player_forecast_shadow",
    "research_v2_weekly", "run_watchdog", "scenarios_shadow", "selection_eval_shadow", "selection_settle_shadow",
    "signals_ingest", "source_credibility_shadow", "stats_documents",
)
"""The job types that were outside the book (33 of the 46 jobs of the worker's heartbeat the baseline counted without a row; the other 13
are ids of jobs that already have one: the in-play pair, the sweeps, the retries and the three nightly fills)."""

_ID_SUFFIX: Final = re.compile(r"(_sweep|_retry_\d{4}|_\d{4})$")
_IN_PLAY: Final = {"live_odds": "live_odds_capture", "live_match": "live_match_capture"}


def job_type_of(job_id: str) -> str:
    """A scheduled job's id in the worker's heartbeat -> the job type of its ledger rows. Most ids are their type; the in-play pair is
    ``<id>_capture``, and the sweeps, the retries and the nightly fills (``x_sweep``, ``x_retry_0840``, ``x_0050``) write under ``x``."""
    return _IN_PLAY.get(job_id) or _ID_SUFFIX.sub("", job_id)


SKIPPED_SWITCH_OFF: Final = "interruptor_apagado"
MAX_ERRORS: Final = 5
"""Errors kept per run: a pass that fails in a loop of a hundred steps leaves its first five, not a hundred."""


@dataclass
class Pass:
    """One pass of a job: what it did, as the run row will say it."""

    job_type: str
    run_id: int | None = None
    errors: list[str] = field(default_factory=list)
    skipped: str | None = None
    rows: int = 0


_current: ContextVar[Pass | None] = ContextVar("fbi_job_book_pass", default=None)


def current() -> Pass | None:
    return _current.get()


def skip(reason: str = SKIPPED_SWITCH_OFF) -> None:
    """The pass in flight did nothing on purpose (its switch is off, nothing is due): its row says so. A no-op outside a booked pass."""
    p = _current.get()
    if p is not None:
        p.skipped = reason[:80]


def count(rows: int) -> None:
    """What the pass wrote, when the job knows: it is the row's ``rows_written`` (a pass with errors and rows is ``partial``)."""
    p = _current.get()
    if p is not None:
        p.rows += int(rows)


def record_error(event: str, detail: str | None = None) -> None:
    """An error the job caught and logged. Called by the logging pipeline for every error-level line inside a booked pass."""
    p = _current.get()
    if p is not None and len(p.errors) < MAX_ERRORS:
        p.errors.append((f"{event}: {detail}" if detail else event)[:500])


def _open(connect: Callable[[], psycopg.Connection], job_type: str,
          params: dict[str, object] | None) -> tuple[Any, RunLedger | None, int | None]:
    try:
        conn = connect()
        ledger = RunLedger(conn)
        return conn, ledger, ledger.open(job_type, params=params)
    except Exception as exc:  # the ledger never stops a job
        log.warning("job_book.open_failed", job_type=job_type, error=f"{type(exc).__name__}: {exc}"[:200])
        return None, None, None


def _close(conn: Any, ledger: RunLedger | None, run_id: int | None, p: Pass) -> None:
    if conn is None or ledger is None or run_id is None:
        return
    try:
        counters = RunCounters(errors=list(p.errors), rows_inserted=p.rows)
        if p.skipped:
            with conn.cursor() as cur:
                cur.execute("UPDATE raw.ingestion_runs SET params = params || %s::jsonb WHERE id = %s",
                            (Json({"skipped": p.skipped}), run_id))
            conn.commit()
        ledger.close(run_id, counters, notes=f"omitida: {p.skipped}" if p.skipped else None)
    except Exception as exc:
        log.warning("job_book.close_failed", job_type=p.job_type, run_id=run_id, error=f"{type(exc).__name__}: {exc}"[:200])
    finally:
        with contextlib.suppress(Exception):
            conn.close()


@contextlib.contextmanager
def booked(job_type: str, connect: Callable[[], psycopg.Connection], *,
           params: dict[str, object] | None = None) -> Iterator[Pass]:
    """Open the run, let the pass happen, close the run - also when the pass raises or is cancelled (the exception goes on)."""
    p = Pass(job_type=job_type)
    conn, ledger, run_id = _open(connect, job_type, params)
    p.run_id = run_id
    token = _current.set(p)
    try:
        yield p
    finally:
        _current.reset(token)
        _close(conn, ledger, run_id, p)


add_error_sink(record_error)

F = TypeVar("F", bound=Callable[..., Any])


def booked_job(job_type: str, connect: Callable[[], Callable[[], psycopg.Connection]]) -> Callable[[F], F]:
    """Decorator of a job's ``_x_now``: every call is one booked pass. ``connect`` returns the connection factory when called, so a test that
    replaces the scheduler's ``_connect`` is honoured."""

    def wrap(fn: F) -> F:
        @functools.wraps(fn)
        def inner(*args: Any, **kwargs: Any) -> Any:
            with booked(job_type, connect()):
                return fn(*args, **kwargs)

        return cast(F, inner)

    return wrap


def outside_the_book(conn: psycopg.Connection, *, days: int = 30, type_of: Callable[[str], str] = job_type_of) -> list[str]:
    """The jobs of the worker's heartbeat whose job type has no run in the last ``days``: what RP-1.1 brought from 46 to 0 (the baseline's
    I20b counted by id; a job id that is not its type counts as its type here)."""
    with conn.cursor() as cur:
        cur.execute(
            "WITH hb AS (SELECT DISTINCT jsonb_object_keys(jobs) AS job FROM raw.worker_heartbeats "
            "            WHERE stopped_at IS NULL AND last_beat_at > now() - interval '10 minutes') "
            "SELECT job FROM hb ORDER BY job")
        jobs = [str(r[0]) for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT job_name FROM raw.ingestion_runs WHERE started_at > now() - make_interval(days => %s)", (days,))
        seen = {str(r[0]) for r in cur.fetchall()}
    return [j for j in jobs if type_of(j) not in seen]
