"""Two workers on one database cannot both run.

Host mode and compose mode are alternatives. The advisory lock makes starting
both a refused start instead of doubled provider requests, and survives the
two ways a lock goes wrong: a worker that dies (PostgreSQL releases it with
the connection) and a database restart (the first worker back takes it).
"""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg
import pytest

from fbi.ops.worker_lock import WorkerLock, holder
from tests.integration.conftest import ADMIN_URL, REPO_ROOT

pytestmark = pytest.mark.integration


def _kill(pid: int) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))


def test_a_second_worker_is_refused_and_told_who_holds_it(migrated_database: str) -> None:
    first = WorkerLock.acquire(migrated_database)
    assert first is not None
    try:
        assert WorkerLock.acquire(migrated_database) is None
        with psycopg.connect(migrated_database) as conn:
            who = holder(conn)
        assert who is not None and who.application_name is not None
        assert who.application_name.startswith("fbi-worker@")
        assert who.backend_start is not None
    finally:
        first.release()
    again = WorkerLock.acquire(migrated_database)
    assert again is not None, "a released lock is free again"
    again.release()


def test_a_killed_worker_leaves_no_lock_behind(migrated_database: str) -> None:
    first = WorkerLock.acquire(migrated_database)
    assert first is not None
    _kill(first.backend_pid)
    second = WorkerLock.acquire(migrated_database)
    assert second is not None, "the lock went with the connection"
    second.release()
    first.release()


def test_after_a_database_restart_the_first_worker_back_keeps_it(migrated_database: str) -> None:
    lock = WorkerLock.acquire(migrated_database)
    assert lock is not None
    assert lock.still_held() is True
    _kill(lock.backend_pid)  # what a restart does to every connection
    assert lock.still_held() is True, "nobody else wanted it: taken again"
    assert WorkerLock.acquire(migrated_database) is None
    lock.release()


def test_after_a_restart_a_worker_that_lost_the_race_stops(migrated_database: str) -> None:
    lock = WorkerLock.acquire(migrated_database)
    assert lock is not None
    _kill(lock.backend_pid)
    rival = WorkerLock.acquire(migrated_database)
    assert rival is not None
    try:
        assert lock.still_held() is False
    finally:
        rival.release()
        lock.release()


def test_an_unreachable_database_is_not_a_reason_to_stop(migrated_database: str) -> None:
    conn = psycopg.connect(migrated_database)
    conn.close()
    lock = WorkerLock("postgresql://nobody@127.0.0.1:1/none", conn)
    assert lock.still_held() is None


def test_the_worker_process_refuses_to_start_beside_another(migrated_database: str) -> None:
    """The real entry point, not just the class: exit 75 before any job exists.
    The provider URL points nowhere, so even a broken lock could not spend a request."""
    lock = WorkerLock.acquire(migrated_database)
    assert lock is not None
    env = {**os.environ,
           "FBI_DATABASE_URL": migrated_database.replace("postgresql://", "postgresql+psycopg://"),
           "FBI_APIFOOTBALL_BASE_URL": "http://127.0.0.1:9", "FBI_APIFOOTBALL_KEY": "not-a-key"}
    try:
        proc = subprocess.run([sys.executable, "-m", "apps.worker.scheduler"], cwd=REPO_ROOT, env=env,
                              capture_output=True, text=True, timeout=60, check=False)
    finally:
        lock.release()
    assert proc.returncode == 75, proc.stdout[-2000:] + proc.stderr[-2000:]
    out = proc.stdout + proc.stderr
    assert "worker.already_running" in out
    assert "fbi-worker@" in out, "the refusal names who holds the lock"
    assert "worker.started" not in out
