"""One worker per database, whichever way it was started.

Two workers would each plan the same odds windows before either had written
its capture, so both would ask the provider: the persistent quota keeps them
under the daily budget, but every duplicated window is a request the budget
cannot spend elsewhere. Host mode (scripts/dev-up) and compose mode
(docker compose --profile stack) are alternatives; this lock is what makes
running both at once harmless instead of merely documented.

The lock is a PostgreSQL session advisory lock held on a dedicated
connection for the life of the process. PostgreSQL releases it the moment
that connection ends - a crashed or killed worker never leaves it behind,
and there is no lock file to clean up.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import datetime

import psycopg

LOCK_KEY = 0x4642_4957
"""'FBIW'. Fits in 32 bits, so pg_locks shows it as classid 0, objid LOCK_KEY."""


def application_name() -> str:
    return f"fbi-worker@{socket.gethostname()}:{os.getpid()}"[:63]


@dataclass(frozen=True, slots=True)
class LockHolder:
    application_name: str | None
    client_addr: str | None
    backend_start: datetime | None


class WorkerLock:
    """The held lock. ``still_held`` is checked on every tick."""

    def __init__(self, dsn: str, conn: psycopg.Connection) -> None:
        self._dsn = dsn
        self._conn = conn

    @classmethod
    def acquire(cls, dsn: str) -> WorkerLock | None:
        """The lock, or None when another worker holds it."""
        conn = _try(dsn)
        return cls(dsn, conn) if conn is not None else None

    @property
    def backend_pid(self) -> int:
        """The PostgreSQL backend holding the lock (what pg_locks shows)."""
        return int(self._conn.info.backend_pid)

    def still_held(self) -> bool | None:
        """True while held. After a lost connection (a database restart) it
        tries to take the lock again: False means another worker got there
        first and this one must stop; None means the database cannot be
        reached at all, which is not a reason to stop - the tick will fail
        and be recorded on its own."""
        try:
            self._conn.execute("SELECT 1")
            return True
        except psycopg.Error:
            pass
        try:
            conn = _try(self._dsn)
        except psycopg.OperationalError:
            return None
        if conn is None:
            return False
        self._conn.close()
        self._conn = conn
        return True

    def release(self) -> None:
        self._conn.close()


def _try(dsn: str) -> psycopg.Connection | None:
    conn = psycopg.connect(dsn, connect_timeout=5, autocommit=True, application_name=application_name())
    row = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()
    if row is not None and row[0]:
        return conn
    conn.close()
    return None


def holder(conn: psycopg.Connection) -> LockHolder | None:
    """Who holds the lock, for the message a refused worker prints."""
    row = conn.execute(
        """
        SELECT a.application_name, a.client_addr::text, a.backend_start
        FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid
        WHERE l.locktype = 'advisory' AND l.classid = 0 AND l.objid = %s AND l.objsubid = 1 AND l.granted
        """,
        (LOCK_KEY,),
    ).fetchone()
    if row is None:
        return None
    return LockHolder(row[0] or None, row[1], row[2])
