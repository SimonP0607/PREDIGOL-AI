"""No ledger run stays 'running' for ever.

A run is 'running' from ``RunLedger.open`` until ``RunLedger.close``. A process that dies in between - a worker
restarted for a deploy, a crash, a CLI script killed by hand - leaves the row open. On 5 Oct 2026 three did (two
odds captures open across worker restarts, one RAW replay killed by hand), and the System page showed DEGRADED
for hours. The boot-time rule (``fbi.ops.reaper``) only closes runs older than the machine's boot.

Every run now records its owner (host, pid, the process's start time), a heartbeat and a deadline (migration
0062). ``recover_runs`` - at worker start and every five minutes - decides on evidence only:

* the owner process on this host is gone (no such pid, or the pid now belongs to a process that started at
  another time) ................................................................ 'interrupted';
* a worker job's run that started before the current worker process (the worker lock guarantees a single
  worker: the previous one is gone) ............................................ 'interrupted';
* started before this machine booted ........................................... 'interrupted';
* past its deadline ............................................................ 'stale';
* no owner recorded (a run opened before 0062) and open for over LEGACY_MAX_AGE  'stale'.

A 'stale' run whose job later closes gets its real outcome from the close (the ledger keeps a note). Nothing
a run wrote is touched: only status, finished_at and a reason appended to last_error.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import structlog

log = structlog.get_logger(__name__)

PROC = Path("/proc")
LEGACY_MAX_AGE = timedelta(hours=12)
DEFAULT_TIMEOUT = timedelta(hours=6)

JOB_TIMEOUTS: dict[str, timedelta] = {
    "live_odds_capture": timedelta(minutes=10),
    "live_match_capture": timedelta(minutes=10),
    "prematch_lineups": timedelta(minutes=10),
    "odds_capture": timedelta(minutes=45),
    "final_prematch": timedelta(minutes=45),
    "context_due": timedelta(minutes=45),
    "results_repair": timedelta(minutes=45),
    "post_match_detail": timedelta(minutes=45),
    "pick_pipeline": timedelta(minutes=45),
    "pick_settlement": timedelta(minutes=15),
    "catalogue_refresh": timedelta(minutes=45),
    "reference_refresh": timedelta(hours=1),
    "results_sync": timedelta(hours=1),
    "fixtures_sync": timedelta(hours=2),
    "context_refresh": timedelta(hours=2),
    "quality_sweep": timedelta(hours=2),
    "elo_refresh": timedelta(hours=2),
    "historical_validation": timedelta(hours=2),
    "historical_backfill": timedelta(hours=3),
    "research_monitor": timedelta(hours=3),
}
"""How long a run of each job may stay open. Generous: three to ten times the longest run observed in the ledger
(4-5 Oct 2026). Prefix rules below cover the families of CLI jobs."""

PREFIX_TIMEOUTS: tuple[tuple[str, timedelta], ...] = (
    ("truth_", timedelta(hours=4)),
    ("raw_", timedelta(hours=12)),
    ("research", timedelta(hours=8)),
    ("feature", timedelta(hours=8)),
    ("backtest", timedelta(hours=8)),
)


def timeout_for(job_type: str) -> timedelta:
    if job_type in JOB_TIMEOUTS:
        return JOB_TIMEOUTS[job_type]
    for prefix, limit in PREFIX_TIMEOUTS:
        if job_type.startswith(prefix):
            return limit
    return DEFAULT_TIMEOUT


@dataclass(frozen=True, slots=True)
class Owner:
    host: str
    pid: int
    started: int | None
    """Process start time in clock ticks since boot (/proc/<pid>/stat field 22); None where /proc is absent."""


def process_start(pid: int, proc: Path = PROC) -> int | None:
    """The start time of ``pid`` from /proc, or None when the process does not exist (or /proc cannot say)."""
    try:
        text = (proc / str(pid) / "stat").read_text()
    except OSError:
        return None
    # comm (field 2) is in parentheses and may contain spaces: split after the last ')'.
    rest = text.rsplit(")", 1)[-1].split()
    try:
        return int(rest[19])  # field 22 overall: state is field 3 = rest[0]
    except (IndexError, ValueError):
        return None


def process_identity(pid: int | None = None, proc: Path = PROC) -> Owner:
    pid = pid or os.getpid()
    return Owner(host=socket.gethostname(), pid=pid, started=process_start(pid, proc))


def owner_alive(pid: int | None, started: int | None, proc: Path = PROC) -> bool:
    """Is the process that opened a run still the process with that pid on this host?"""
    if pid is None:
        return False
    current = process_start(pid, proc)
    if current is None:
        if not proc.exists():  # no /proc to ask: fall back to "a process with this pid exists"
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
            return True
        return False
    return started is None or current == started


@dataclass(frozen=True, slots=True)
class Recovered:
    run_id: int
    job_type: str
    status: str
    reason: str


OPEN_SQL = """
SELECT id, job_type, started_at, owner_host, owner_pid, owner_started, heartbeat_at, deadline_at
  FROM raw.ingestion_runs WHERE status = 'running' ORDER BY id
"""

CLOSE_SQL = """
UPDATE raw.ingestion_runs
   SET status = %(status)s, finished_at = COALESCE(finished_at, %(at)s),
       last_error = COALESCE(last_error || ' | ', '') || %(reason)s
 WHERE id = %(id)s AND status = 'running'
"""


def _ago(at: datetime, then: datetime | None) -> str:
    if then is None:
        return "never"
    minutes = int((at - then).total_seconds() // 60)
    return f"{minutes} min ago" if minutes < 120 else f"{minutes // 60} h ago"


def judge(row: dict[str, Any], *, at: datetime, host: str, worker_started_at: datetime | None,
          worker_job_types: Iterable[str], booted_at: datetime | None, proc: Path = PROC) -> tuple[str, str] | None:
    """(status, reason) for an open run that cannot be open any more, or None to leave it."""
    started: datetime = row["started_at"]
    beat = row.get("heartbeat_at")
    if booted_at is not None and started < booted_at:
        return "interrupted", (f"interrupted: started before this machine booted ({booted_at:%Y-%m-%d %H:%M} UTC); "
                               "recovered by the run watchdog")
    if row.get("owner_pid") is not None:
        if row.get("owner_host") == host and not owner_alive(row["owner_pid"], row.get("owner_started"), proc):
            return "interrupted", (f"interrupted: its process (pid {row['owner_pid']}) is gone - a restart, a crash or "
                                   f"a kill; last heartbeat {_ago(at, beat)}; recovered by the run watchdog")
    elif worker_started_at is not None and row["job_type"] in set(worker_job_types) and started < worker_started_at:
        # A run opened before 0062 has no owner: a worker job's run older than the current worker cannot be
        # the current worker's, and the worker lock means the previous worker is gone.
        return "interrupted", (f"interrupted: opened by a previous worker process (this one started "
                               f"{worker_started_at:%Y-%m-%d %H:%M} UTC and holds the worker lock); "
                               "recovered by the run watchdog")
    deadline = row.get("deadline_at")
    if deadline is not None and at > deadline:
        return "stale", (f"stale: still open past its deadline ({deadline:%Y-%m-%d %H:%M} UTC, "
                         f"{timeout_for(row['job_type'])} after its start); last heartbeat {_ago(at, beat)}; "
                         "closed by the run watchdog")
    if deadline is None and row.get("owner_pid") is None and at - started > LEGACY_MAX_AGE:
        return "stale", (f"stale: no owner recorded and open for {_ago(at, started).replace(' ago', '')}; "
                         "closed by the run watchdog")
    return None


LINKED_SQL = (
    """UPDATE audit.truth_runs t SET status = 'interrupted', finished_at = COALESCE(t.finished_at, %(at)s)
         FROM raw.ingestion_runs r
        WHERE t.ingestion_run_id = r.id AND t.status = 'running' AND r.status <> 'running' RETURNING t.id""",
    """UPDATE audit.truth_v2_runs t SET status = 'failed', finished_at = COALESCE(t.finished_at, %(at)s)
         FROM raw.ingestion_runs r
        WHERE t.ingestion_run_id = r.id AND t.status = 'running' AND r.status <> 'running' RETURNING t.id""",
)
"""An audit run whose ledger run is closed cannot be running: 5 Oct 2026, a truth audit that crashed while storing
its findings left audit.truth_runs 3 'running' after its ledger run had ended."""


def recover_runs(conn: psycopg.Connection[Any], *, at: datetime, worker_started_at: datetime | None = None,
                 worker_job_types: Iterable[str] = (), booted_at: datetime | None = None,
                 proc: Path = PROC) -> list[Recovered]:
    """Close every open run that cannot be open any more. Idempotent; commits."""
    from psycopg.rows import dict_row

    host = socket.gethostname()
    types = frozenset(worker_job_types)
    out: list[Recovered] = []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(OPEN_SQL)
        rows = cur.fetchall()
    with conn.cursor() as cur:
        for row in rows:
            verdict = judge(row, at=at, host=host, worker_started_at=worker_started_at, worker_job_types=types,
                            booted_at=booted_at, proc=proc)
            if verdict is None:
                continue
            status, reason = verdict
            cur.execute(CLOSE_SQL, {"status": status, "at": at, "reason": reason, "id": row["id"]})
            if cur.rowcount:
                out.append(Recovered(int(row["id"]), str(row["job_type"]), status, reason))
        linked = []
        for sql in LINKED_SQL:
            cur.execute(sql, {"at": at})
            linked += [int(r[0]) for r in cur.fetchall()]
    conn.commit()
    if out:
        log.warning("runs.recovered", runs=[(r.run_id, r.job_type, r.status) for r in out])
    if linked:
        log.warning("runs.recovered_audit_rows", audit_runs=linked)
    return out
