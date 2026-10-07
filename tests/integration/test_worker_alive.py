"""scripts/worker_alive.py: the container healthcheck of the worker on the server says what the Admin Console says."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import psycopg
import pytest
from scripts import worker_alive

from fbi.core.clock import now
from fbi.core.config import reset_cache
from fbi.ops.heartbeat import default_worker_id
from tests.integration.conftest import Seed


@pytest.fixture()
def beats(migrated_database: str, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> Iterator[psycopg.Connection]:
    monkeypatch.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM raw.worker_heartbeats")
        yield conn
        conn.execute("DELETE FROM raw.worker_heartbeats")
    reset_cache()


def _beat(conn: psycopg.Connection, worker_id: str, *, ago: timedelta, stopped: bool = False) -> None:
    at = now() - ago
    conn.execute(
        "INSERT INTO raw.worker_heartbeats (worker_id, hostname, pid, code_version, started_at, last_beat_at, ticks, "
        "tick_interval_s, jobs, stopped_at) VALUES (%s, 'h', 1, 'v', %s, %s, 3, 600, '{}'::jsonb, %s)",
        (worker_id, at - timedelta(hours=1), at, at + timedelta(seconds=1) if stopped else None))


def test_a_worker_that_beat_recently_is_alive(beats: psycopg.Connection) -> None:
    _beat(beats, default_worker_id(), ago=timedelta(minutes=3))
    assert worker_alive.main([]) == 0


def test_a_silent_or_stopped_worker_is_not(beats: psycopg.Connection) -> None:
    assert worker_alive.main([]) == 1, "never beaten"
    _beat(beats, default_worker_id(), ago=timedelta(minutes=40))
    assert worker_alive.main([]) == 1, "silent for more than two ticks plus the grace"
    beats.execute("DELETE FROM raw.worker_heartbeats")
    _beat(beats, default_worker_id(), ago=timedelta(minutes=1), stopped=True)
    assert worker_alive.main([]) == 1, "announced a clean stop"


def test_another_hosts_worker_counts_only_when_asked(beats: psycopg.Connection) -> None:
    _beat(beats, "elsewhere:worker", ago=timedelta(minutes=2))
    assert worker_alive.main([]) == 1
    assert worker_alive.main(["--any"]) == 0


def test_an_unreachable_database_is_not_alive(beats: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_DATABASE_URL", "postgresql+psycopg://nobody:x@127.0.0.1:1/none")
    reset_cache()
    assert worker_alive.main([]) == 1
