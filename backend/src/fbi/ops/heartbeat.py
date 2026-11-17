"""Worker liveness, written on every tick whether or not the tick had work.

The job ledger records what the worker DID. On a quiet day - no fixture in a
capture window - a healthy worker does nothing for hours and the ledger stays
silent, which is indistinguishable from a dead worker. This table is what
tells them apart.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import psycopg
import structlog
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.core.clock import now

log = structlog.get_logger(__name__)

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


PULSE_SECONDS = 60
"""How often the pulse beats (``LivenessPulse``): well inside the liveness window of two ticks plus a grace."""

LOOP_STALL_SECONDS = 600
"""How long the scheduler's event loop may go without running anything before the pulse stops beating for it.

The pulse exists so that a job that holds the loop for a while - a lock wait, a slow capture - is not mistaken for a
dead worker (OPS-006: seven restarts from 13 to 15 Nov 2026, each inside a fixtures sync). A loop that runs nothing for
ten minutes is not a slow job any more: the pulse goes quiet, the liveness window runs out, and the server's check
restarts the worker as it always did."""


class LivenessPulse:
    """The worker's heartbeat on a thread of its own (OPS-006).

    The tick beat (``HeartbeatWriter.beat``) runs on the scheduler's event loop, after the tick: anything that held the
    loop - on the server, the in-play capture waiting half an hour on the fixtures sync's locks - stopped the beat, and
    the server's check restarted a worker that was alive. This thread moves ``last_beat_at`` every ``PULSE_SECONDS``
    on a connection of its own, whatever the loop is doing, as long as the process is alive, the loop has run
    something in the last ``LOOP_STALL_SECONDS`` (it is asked to, each pulse) and ``healthy()`` says yes (the
    scheduler is running). It writes nothing else: the tick, its outcome, its duration and the count of ticks stay the
    tick's own, so a tick that stopped still shows as one.

    A worker that announced its stop is never brought back by a late pulse (``stopped_at IS NULL``).
    """

    def __init__(
        self,
        connect: Callable[[], psycopg.Connection],
        *,
        worker_id: str,
        loop: asyncio.AbstractEventLoop | None = None,
        healthy: Callable[[], bool] = lambda: True,
        every_s: float = PULSE_SECONDS,
        stall_s: float = LOOP_STALL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._connect = connect
        self._worker_id = worker_id
        self._loop = loop
        self._healthy = healthy
        self._every_s = every_s
        self._stall_s = stall_s
        self._clock = clock
        self._loop_seen = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: psycopg.Connection | None = None
        self.beats = 0
        """Pulses written since start (for tests and the log)."""

    def _seen(self) -> None:
        self._loop_seen = self._clock()

    def loop_lag_s(self) -> float:
        """Seconds since the loop last ran the pulse's probe."""
        return self._clock() - self._loop_seen

    def pulse_once(self) -> bool:
        """One pulse: True when it beat. Never raises: a failed write is logged and the next pulse reconnects."""
        if self._loop is not None:
            try:
                self._loop.call_soon_threadsafe(self._seen)
            except RuntimeError:  # the loop is closed: nothing to vouch for
                return False
            lag = self.loop_lag_s()
            if lag > self._stall_s:
                log.error("worker.loop_stalled", seconds=int(lag), action="pulse withheld; the liveness check decides")
                return False
        if not self._healthy():
            log.error("worker.unhealthy", action="pulse withheld; the liveness check decides")
            return False
        try:
            if self._conn is None or self._conn.closed:
                self._conn = self._connect()
                self._conn.autocommit = True
            with self._conn.cursor() as cur:
                cur.execute("SELECT set_config('lock_timeout', '5s', false), "
                            "set_config('statement_timeout', '15s', false)")
                cur.execute("UPDATE raw.worker_heartbeats SET last_beat_at = %s "
                            "WHERE worker_id = %s AND stopped_at IS NULL", (now(), self._worker_id))
        except psycopg.Error as exc:
            log.error("heartbeat.pulse_failed", error=exc.__class__.__name__)
            self._close()
            return False
        self.beats += 1
        return True

    def _run(self) -> None:
        while not self._stop.wait(self._every_s):
            self.pulse_once()

    def start(self) -> None:
        self._loop_seen = self._clock()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="liveness-pulse", daemon=True)
        self._thread.start()

    def stop(self, timeout_s: float = 20.0) -> None:
        """Stop pulsing, and wait for a pulse in flight: after this returns, nothing beats for this worker."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout_s)
            self._thread = None
        self._close()

    def _close(self) -> None:
        if self._conn is not None:
            with contextlib.suppress(psycopg.Error):
                self._conn.close()
            self._conn = None


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
