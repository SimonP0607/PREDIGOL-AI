"""RP-1.6 against a real database: the lock lets one launcher in, match hours and a held lock refuse and leave their row, and a real launch
(a harmless command in place of the experiment) is booked opened and closed."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.research import launcher

pytestmark = pytest.mark.integration

AT = datetime(2026, 12, 6, 15, 0, tzinfo=UTC)


@pytest.fixture()
def db(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    conn = psycopg.connect(migrated_database, autocommit=True)
    conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = %s", (launcher.JOB_TYPE,))
    monkeypatch.setitem(launcher.JOBS, "tl_ok", launcher.Job("tl_ok", ("-c", "print('ok')"), memory_mb=512, timeout_s=60))
    monkeypatch.setitem(launcher.JOBS, "tl_bad", launcher.Job("tl_bad", ("-c", "import sys; sys.exit(3)"), memory_mb=512, timeout_s=60))
    try:
        yield (lambda: psycopg.connect(migrated_database)), conn
    finally:
        conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = %s", (launcher.JOB_TYPE,))
        conn.close()


def rows(conn: Any) -> list[tuple[Any, ...]]:
    return conn.execute("SELECT status, finished_at IS NOT NULL, params, notes FROM raw.ingestion_runs WHERE job_type = %s ORDER BY id",
                        (launcher.JOB_TYPE,)).fetchall()


def test_one_launcher_at_a_time(db: Any) -> None:
    connect, _ = db
    first, second = connect(), connect()
    try:
        assert launcher.try_lock(first) is True
        assert launcher.try_lock(second) is False
        first.close()
        assert launcher.try_lock(second) is True, "the lock dies with its connection"
    finally:
        second.close()


def test_a_held_lock_refuses_and_leaves_its_row(db: Any) -> None:
    connect, conn = db
    holder = connect()
    try:
        assert launcher.try_lock(holder)
        out = launcher.launch("tl_ok", connect=connect, at=AT)
    finally:
        holder.close()
    assert out.refused and "lock" in out.reason
    [(status, closed, params, notes)] = rows(conn)
    assert (status, closed) == ("completed", True) and params["skipped"].startswith("another experiment") and "refused" in notes


def test_match_hours_refuse_unless_the_owner_orders_otherwise(db: Any, seed: Any) -> None:
    connect, conn = db
    fid = seed.fixture_id
    original = conn.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (fid,)).fetchone()[0]
    try:
        conn.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (AT - timedelta(minutes=30), fid))
        assert launcher.launch("tl_ok", connect=connect, at=AT).refused
        assert launcher.launch("tl_ok", connect=connect, at=AT, allow_match_hours=True).status == "completed"
        conn.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (AT + timedelta(hours=5), fid))
        assert launcher.launch("tl_ok", connect=connect, at=AT).status == "completed", "a match hours away does not stop it"
    finally:
        conn.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (original, fid))


def test_a_launch_is_booked_opened_and_closed_and_a_failure_says_why(db: Any) -> None:
    connect, conn = db
    ok = launcher.launch("tl_ok", connect=connect, at=AT)
    bad = launcher.launch("tl_bad", connect=connect, at=AT)
    assert (ok.status, ok.run_id is not None) == ("completed", True) and (bad.status, bad.exit_code) == ("failed", 3)
    got = rows(conn)
    assert [(r[0], r[1]) for r in got] == [("completed", True), ("failed", True)]
    assert got[0][2]["job"] == "tl_ok" and got[0][2]["memory_mb"] == 512 and "exit 3" in got[1][3]


def test_a_job_that_is_not_due_is_skipped_with_its_reason_and_force_overrides(db: Any) -> None:
    connect, conn = db
    gate = lambda _c, _at, _j: "same model code, last run under four weeks old"  # noqa: E731
    out = launcher.launch("tl_ok", connect=connect, at=AT, gate=gate)
    assert out.status == "skipped" and out.ok
    forced = launcher.launch("tl_ok", connect=connect, at=AT, gate=gate, force=True)
    assert forced.status == "completed"
    assert next(r[2].get("skipped") for r in rows(conn)).startswith("same model code")


def test_a_dry_run_runs_nothing_and_books_nothing(db: Any) -> None:
    connect, conn = db
    out = launcher.launch("tl_ok", connect=connect, at=AT, dry_run=True)
    assert out.status == "skipped" and "dry run" in out.reason and rows(conn) == []
