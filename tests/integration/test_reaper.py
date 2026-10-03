"""Runs left 'running' by a dead process are closed; live ones are not touched."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from fbi.ops.reaper import boot_time, reap_interrupted_runs


def _run(conn: psycopg.Connection, started_at: datetime, status: str = "running") -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.ingestion_runs (job_name, job_type, status, started_at) "
            "VALUES ('t', 'fixtures_sync', %s, %s) RETURNING id",
            (status, started_at),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def _cleanup(conn: psycopg.Connection, ids: list[int]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM raw.ingestion_runs WHERE id = ANY(%s)", (ids,))
    conn.commit()


def _status(conn: psycopg.Connection, run_id: int) -> tuple[str, str | None, datetime | None]:
    with conn.cursor() as cur:
        cur.execute("SELECT status, last_error, finished_at FROM raw.ingestion_runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
        assert row is not None
        return row[0], row[1], row[2]


def test_runs_from_before_the_boot_are_interrupted_and_newer_ones_are_left(migrated_database: str) -> None:
    booted = datetime.now(UTC) - timedelta(hours=1)
    with psycopg.connect(migrated_database) as conn:
        dead = _run(conn, booted - timedelta(days=2))
        alive = _run(conn, booted + timedelta(minutes=5))
        done = _run(conn, booted - timedelta(days=3), status="completed")
        conn.commit()

        reaped = reap_interrupted_runs(conn, booted)

        assert dead in reaped and alive not in reaped and done not in reaped
        status, error, finished = _status(conn, dead)
        assert status == "interrupted" and error is not None and "interrupted" in error and finished is not None
        assert _status(conn, alive)[0] == "running"
        assert _status(conn, done)[0] == "completed"
        # idempotent
        assert dead not in reap_interrupted_runs(conn, booted)
        _cleanup(conn, [dead, alive, done])


def test_unknown_boot_time_closes_nothing(migrated_database: str) -> None:
    with psycopg.connect(migrated_database) as conn:
        run = _run(conn, datetime.now(UTC) - timedelta(days=30))
        conn.commit()
        assert reap_interrupted_runs(conn, None) == []
        assert _status(conn, run)[0] == "running"
        _cleanup(conn, [run])


def test_boot_time_reads_btime(tmp_path: Path) -> None:
    stat = tmp_path / "stat"
    stat.write_text("cpu 1 2 3\nbtime 1790000000\nprocesses 5\n")
    assert boot_time(stat) == datetime.fromtimestamp(1790000000, tz=UTC)
    assert boot_time(tmp_path / "missing") is None
