"""Worker liveness, written on every tick whether or not the tick had work.

The job ledger records what the worker DID. On a quiet day - no fixture in a
capture window - a healthy worker does nothing for hours and the ledger stays
silent, which is indistinguishable from a dead worker. This table is what
tells them apart.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.core.clock import now

TickOutcome = Literal["nothing_scheduled", "nothing_due", "captured", "plan_rejected", "failed"]

LIVENESS_GRACE = timedelta(minutes=5)
"""Beyond two tick intervals plus this, the worker is considered not running."""


def default_worker_id() -> str:
    """Stable per host: a restart reuses the row instead of piling up new ones."""
    return f"{socket.gethostname()}:worker"


@dataclass(frozen=True, slots=True)
class Heartbeat:
    worker_id: str
    hostname: str
    pid: int
    code_version: str
    started_at: datetime
    last_beat_at: datetime
    last_tick_at: datetime | None
    last_tick_outcome: str | None
    last_tick_duration_ms: int | None
    scheduler_lag_ms: int | None
    ticks: int
    tick_interval_s: int
    jobs: dict[str, Any]
    stopped_at: datetime | None

    def is_alive(self, at: datetime | None = None) -> bool:
        """Beat recently enough, and did not announce a clean stop after it."""
        moment = at or now()
        if self.stopped_at is not None and self.stopped_at >= self.last_beat_at:
            return False
        return moment - self.last_beat_at <= 2 * timedelta(seconds=self.tick_interval_s) + LIVENESS_GRACE

    def as_dict(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "hostname": self.hostname,
            "pid": self.pid,
            "code_version": self.code_version,
            "started_at": self.started_at.isoformat(),
            "last_beat_at": self.last_beat_at.isoformat(),
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "last_tick_outcome": self.last_tick_outcome,
            "last_tick_duration_ms": self.last_tick_duration_ms,
            "scheduler_lag_ms": self.scheduler_lag_ms,
            "ticks": self.ticks,
            "tick_interval_s": self.tick_interval_s,
            "jobs": self.jobs,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
        }


class HeartbeatWriter:
    def __init__(self, conn: psycopg.Connection, *, worker_id: str, tick_interval_s: int, code_version: str) -> None:
        self._conn = conn
        self._worker_id = worker_id
        self._tick_interval_s = tick_interval_s
        self._code_version = code_version

    def started(self, *, jobs: dict[str, Any] | None = None) -> None:
        moment = now()
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO raw.worker_heartbeats
                  (worker_id, hostname, pid, code_version, started_at, last_beat_at,
                   ticks, tick_interval_s, jobs, stopped_at)
                VALUES (%s,%s,%s,%s,%s,%s,0,%s,%s,NULL)
                ON CONFLICT (worker_id) DO UPDATE SET
                  hostname = EXCLUDED.hostname, pid = EXCLUDED.pid, code_version = EXCLUDED.code_version,
                  started_at = EXCLUDED.started_at, last_beat_at = EXCLUDED.last_beat_at,
                  last_tick_at = NULL, last_tick_outcome = NULL, last_tick_duration_ms = NULL,
                  scheduler_lag_ms = NULL, ticks = 0, tick_interval_s = EXCLUDED.tick_interval_s,
                  jobs = EXCLUDED.jobs, stopped_at = NULL
                """,
                (self._worker_id, socket.gethostname(), os.getpid(), self._code_version, moment, moment,
                 self._tick_interval_s, Json(jobs or {})),
            )
        self._conn.commit()

    def beat(
        self,
        *,
        outcome: TickOutcome,
        duration_ms: int,
        lag_ms: int | None,
        jobs: dict[str, Any] | None = None,
    ) -> None:
        moment = now()
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE raw.worker_heartbeats SET last_beat_at = %s, last_tick_at = %s, "
                "last_tick_outcome = %s, last_tick_duration_ms = %s, scheduler_lag_ms = %s, "
                "ticks = ticks + 1, jobs = %s WHERE worker_id = %s",
                (moment, moment, outcome, max(duration_ms, 0), lag_ms, Json(jobs or {}), self._worker_id),
            )
        self._conn.commit()

    def stopped(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute("UPDATE raw.worker_heartbeats SET stopped_at = %s WHERE worker_id = %s",
                        (now(), self._worker_id))
        self._conn.commit()


def latest_heartbeat(conn: psycopg.Connection) -> Heartbeat | None:
    """The most recently beating worker, if any has ever beaten."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT worker_id, hostname, pid, code_version, started_at, last_beat_at, last_tick_at, "
            "last_tick_outcome, last_tick_duration_ms, scheduler_lag_ms, ticks, tick_interval_s, jobs, stopped_at "
            "FROM raw.worker_heartbeats ORDER BY last_beat_at DESC LIMIT 1"
        )
        r = cur.fetchone()
    if r is None:
        return None
    return Heartbeat(
        worker_id=str(r[0]), hostname=str(r[1]), pid=int(r[2]), code_version=str(r[3]),
        started_at=r[4], last_beat_at=r[5], last_tick_at=r[6], last_tick_outcome=r[7],
        last_tick_duration_ms=r[8], scheduler_lag_ms=r[9], ticks=int(r[10]),
        tick_interval_s=int(r[11]), jobs=dict(r[12] or {}), stopped_at=r[13],
    )


def next_run_after(last_success: datetime | None, interval: timedelta, at: datetime) -> datetime:
    """When a periodic job should next run, anchored on the LEDGER, not on
    process start.

    A worker that restarts every few minutes must not re-run a 12-hourly sync
    each time (that is quota), and a worker that was down for 12 hours must not
    wait another 12 before catching up (that is data the free plan stops
    serving a day later). The job is due ``interval`` after it last succeeded,
    or now if that moment has already passed.
    """
    if last_success is None:
        return at
    due = last_success + interval
    return due if due > at else at


def last_success(conn: psycopg.Connection, job_type: str) -> datetime | None:
    """When a job last finished with something durable to show."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT max(started_at) FROM raw.ingestion_runs "
            "WHERE job_type = %s AND status IN ('completed','partial')",
            (job_type,),
        )
        r = cur.fetchone()
    return r[0] if r and r[0] is not None else None
