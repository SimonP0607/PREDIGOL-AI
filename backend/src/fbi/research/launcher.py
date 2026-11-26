"""The experiment launcher (plan RP-1.6, finding H30): an experiment or a historical re-run runs in the operations container, one at a time,
with a ceiling of memory and of time, and leaves its row in the book of runs - never inside the worker.

WHY. The worker lives at 2.77 of 3 GB and ``period_backfill`` aborts for lack of margin (finding H30). The weekly research used to run as a child
of the worker (``scripts/research_v2.py --apply``, about five minutes of CPU and a few hundred MB), so its memory counted against the worker's
and its load fell on the same host as the matches. This module is what the operations container runs instead
(``python -m scripts.experiment_run research_v2``; ``deploy/vps/bin/research-run.sh`` and its timer):

    ONE AT A TIME   ``pg_try_advisory_lock`` on a connection kept open for the whole run: a second launcher, from anywhere, refuses at once.
                    The lock dies with the connection, so a crashed launcher never leaves it held.
    MEMORY CEILING  the resident memory of the whole process group is read every ``POLL_S`` seconds; above the ceiling the group is killed
                    (``memory_cap``), so one experiment can never take the host down with it.
    TIME CEILING    the group is killed at ``timeout_s`` (``timeout``).
    BOOK            one ``raw.ingestion_runs`` row (job ``experiment_run``) per launch, opened before and closed after, with the job, its
                    ceilings, its peak memory and why it ended; a refusal (lock, match hours, frozen, not due) is a row too, with its reason.
    LOW LOAD        by default it refuses while a match is on or about to start (``MATCH_WINDOW``): ``allow_match_hours`` is the owner's order.
    ONLY WHAT IS LISTED  ``JOBS`` names what can be launched; nothing arrives from outside as a command.

The launcher writes nothing of its own beyond its row of the book: what the experiment stores (``analytics.experiments`` and its reports) it
stores itself, as it always did. It decides nothing about a model, a forecast, a pick or a threshold."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import psycopg
import structlog
from psycopg.types.json import Json

from fbi.ingestion.ledger import RunCounters, RunLedger

log = structlog.get_logger(__name__)

JOB_TYPE: Final = "experiment_run"
LOCK_KEY: Final = 7_201_126_001
"""The advisory-lock key of the launcher (one experiment at a time, database-wide)."""
POLL_S: Final = 2.0
GRACE_S: Final = 10.0
"""Seconds between the group's SIGTERM and its SIGKILL."""
MATCH_WINDOW: Final = (timedelta(hours=3), timedelta(minutes=45))
"""A match is "on or about to start" from 3 h after its kick-off (it may still be in play) to 45 min before it."""
REPO_ROOT: Final = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class Job:
    """What can be launched: its command and its default ceilings (the caller may lower or raise them)."""

    name: str
    argv: tuple[str, ...]
    memory_mb: int
    timeout_s: int
    gate: str | None = None
    """``research_v2``: the job asks the research loop whether a run is due (and whether research is frozen) before it spends anything.
    ``experiments_due``: the job asks the conditions of the plan's experiments (``fbi.research.exp_conditions``) whether any is due, and writes nothing if none is."""


JOBS: Final[Mapping[str, Job]] = {
    "research_v2": Job("research_v2", ("-m", "scripts.research_v2", "--apply"), memory_mb=2048, timeout_s=7200, gate="research_v2"),
    "experiments_due": Job("experiments_due", ("-m", "scripts.exp_run", "--due"), memory_mb=1536, timeout_s=3600, gate="experiments_due"),
}


@dataclass
class Outcome:
    """How a launch ended, as the CLI reports it."""

    status: str
    reason: str
    exit_code: int | None = None
    peak_mb: int = 0
    seconds: float = 0.0
    run_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return self.status == "refused"

    @property
    def ok(self) -> bool:
        return self.status in ("completed", "skipped")


# -- the guards ------------------------------------------------------------------------------------------------------------------------


def try_lock(conn: psycopg.Connection[Any]) -> bool:
    """Take the launcher's lock on THIS connection (held until it closes). False when another launcher holds it."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
        row = cur.fetchone()
    return bool(row and row[0])


def match_hours(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    """How many matches are on or about to start at ``at`` (kicked off within ``MATCH_WINDOW``): the launcher stays out of those hours."""
    after, before = MATCH_WINDOW
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixtures WHERE kickoff_at > %s AND kickoff_at < %s", (at - after, at + before))
        row = cur.fetchone()
    return int(row[0]) if row else 0


def rss_mb(pgid: int, *, proc: str = "/proc") -> int:
    """Resident memory, in MB, of every process of the group ``pgid`` (Linux ``/proc``; 0 where it cannot be read)."""
    total_kb = 0
    try:
        entries = [e for e in os.listdir(proc) if e.isdigit()]
    except OSError:
        return 0
    for pid in entries:
        try:
            with open(f"{proc}/{pid}/stat", encoding="utf-8") as f:
                stat = f.read()
            # field 5 is the process group; the command (field 2) may hold spaces and parentheses, so cut after its last ")"
            fields = stat[stat.rindex(")") + 2:].split()
            if int(fields[2]) != pgid:
                continue
            with open(f"{proc}/{pid}/status", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        total_kb += int(line.split()[1])
                        break
        except (OSError, ValueError, IndexError):
            continue
    return total_kb // 1024


def _kill_group(pgid: int) -> None:
    for sig, wait in ((signal.SIGTERM, GRACE_S), (signal.SIGKILL, 0.0)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if rss_mb(pgid) == 0:
                return
            time.sleep(0.2)


def supervise(argv: list[str], *, memory_mb: int, timeout_s: float, cwd: Path | None = None, env: Mapping[str, str] | None = None,
              poll_s: float = POLL_S) -> Outcome:
    """Run ``argv`` in a group of its own and keep it under both ceilings. Returns how it ended; never raises for the child's failure."""
    started = time.monotonic()
    proc = subprocess.Popen(argv, cwd=cwd, env=None if env is None else dict(env), start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    pgid = proc.pid
    peak = 0
    why: str | None = None
    tail: list[str] = []

    import threading

    def drain() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            tail.append(line.rstrip("\n"))
            del tail[:-40]

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        while proc.poll() is None:
            now_s = time.monotonic() - started
            used = rss_mb(pgid)
            peak = max(peak, used)
            if used > memory_mb:
                why = f"memory_cap: {used} MB over the ceiling of {memory_mb} MB"
            elif now_s > timeout_s:
                why = f"timeout: {int(now_s)} s over the ceiling of {int(timeout_s)} s"
            if why:
                _kill_group(pgid)
                break
            time.sleep(poll_s)
    except BaseException:
        _kill_group(pgid)
        raise
    finally:
        proc.wait()
        reader.join(timeout=5)
    seconds = time.monotonic() - started
    last = " | ".join(tail[-3:])[-300:]
    if why:
        return Outcome("failed", why, proc.returncode, peak, seconds, extra={"tail": last})
    if proc.returncode == 0:
        return Outcome("completed", "exit 0", 0, peak, seconds, extra={"tail": last})
    return Outcome("failed", f"exit {proc.returncode}", proc.returncode, peak, seconds, extra={"tail": last})


# -- the launch ------------------------------------------------------------------------------------------------------------------------


def _book(conn: psycopg.Connection[Any], job: Job, params: dict[str, Any], outcome: Outcome, opened: int | None) -> None:
    """Close the run row (or write a closed one when it could not be opened first)."""
    try:
        ledger = RunLedger(conn)
        run_id = opened if opened is not None else ledger.open(JOB_TYPE, params=params)
        counters = RunCounters()
        if outcome.status == "failed":
            counters.errors.append(f"{outcome.reason}"[:400])
        notes = f"{outcome.status}: {outcome.reason}"
        if outcome.status in ("refused", "skipped"):
            with conn.cursor() as cur:
                cur.execute("UPDATE raw.ingestion_runs SET params = params || %s::jsonb WHERE id = %s",
                            (Json({"skipped": outcome.reason[:80]}), run_id))
            conn.commit()
        ledger.close(run_id, counters, notes=f"{notes}; peak {outcome.peak_mb} MB; {outcome.seconds:.0f} s"[:400])
        outcome.run_id = run_id
    except Exception as exc:  # the book never hides how the launch ended
        log.warning("launcher.book_failed", job=job.name, error=f"{type(exc).__name__}: {exc}"[:200])


def launch(job_name: str, *, connect: Callable[[], psycopg.Connection[Any]], at: datetime, memory_mb: int | None = None,
           timeout_s: int | None = None, allow_match_hours: bool = False, force: bool = False, dry_run: bool = False,
           gate: Callable[[psycopg.Connection[Any], datetime, Job], str | None] | None = None) -> Outcome:
    """Launch one of ``JOBS`` under the guards. ``gate`` answers, for jobs that have one, why the run is NOT due (None: it is due)."""
    job = JOBS.get(job_name)
    if job is None:
        return Outcome("refused", f"unknown job {job_name!r}: only {sorted(JOBS)} can be launched")
    memory = memory_mb or job.memory_mb
    timeout = timeout_s or job.timeout_s
    params: dict[str, Any] = {"job": job.name, "memory_mb": memory, "timeout_s": timeout, "allow_match_hours": allow_match_hours,
                              "force": force, "dry_run": dry_run}
    conn = connect()
    try:
        conn.autocommit = True
        if not try_lock(conn):
            out = Outcome("refused", "another experiment is running (advisory lock held)")
            _book(conn, job, params, out, None)
            return out
        if not allow_match_hours and (n := match_hours(conn, at=at)):
            out = Outcome("refused", f"{n} match(es) on or about to start: not in match hours without the owner's order")
            _book(conn, job, params, out, None)
            return out
        if not force and gate is not None:
            not_due = gate(conn, at, job)
            if not_due:
                out = Outcome("skipped", not_due)
                _book(conn, job, params, out, None)
                return out
        if dry_run:
            return Outcome("skipped", f"dry run: would run {' '.join(job.argv)} under {memory} MB and {timeout} s")
        ledger = RunLedger(conn)
        run_id = ledger.open(JOB_TYPE, params=params)
        out = Outcome("failed", "interrupted before it ended")
        try:
            out = supervise([sys.executable, *job.argv], memory_mb=memory, timeout_s=timeout, cwd=REPO_ROOT)
        finally:
            _book(conn, job, params, out, run_id)
        log.info("launcher.done", job=job.name, status=out.status, reason=out.reason, peak_mb=out.peak_mb, seconds=round(out.seconds))
        return out
    finally:
        conn.close()


def research_gate(conn: psycopg.Connection[Any], at: datetime, job: Job) -> str | None:
    """Why research V2 is not due (frozen for audit, or the same model code and under four weeks old), or None when it is."""
    from fbi.research.loop import frozen, v2_due

    why = frozen()
    if why:
        return f"research is frozen: {why}"[:200]
    due = v2_due(conn, at=at)
    return None if due else "same model code, last run under four weeks old"


def experiments_gate(conn: psycopg.Connection[Any], at: datetime, job: Job) -> str | None:
    """Why no experiment of the plan is due (frozen for audit, or none has reached its condition), or None when at least one is."""
    from fbi.research import exp_conditions
    from fbi.research.loop import frozen

    why = frozen()
    if why:
        return f"research is frozen: {why}"[:200]
    return None if exp_conditions.due_now(conn, at=at) else "no experiment of the plan is due"


__all__ = ["JOBS", "JOB_TYPE", "LOCK_KEY", "Job", "Outcome", "experiments_gate", "launch", "match_hours", "research_gate", "rss_mb", "supervise", "try_lock"]
