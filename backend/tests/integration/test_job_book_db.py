"""RP-1.1 against a real database: every pass of a booked job leaves one row in the ledger, opened before and closed after - also when the
job logs its failure, raises, is cut, or has nothing to do - and the ledger never stops a job. The rows are the test's own (job types
``tjb_*``) and are deleted at the end: the ledger commits."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
import structlog

from fbi.core.logging import configure
from fbi.ops import job_book

pytestmark = pytest.mark.integration

log = structlog.get_logger(__name__)


@pytest.fixture()
def rows(migrated_database: str) -> Iterator[Any]:
    configure("INFO")
    conn = psycopg.connect(migrated_database, autocommit=True)

    def fetch(job: str) -> list[tuple[Any, ...]]:
        return conn.execute("SELECT status, finished_at IS NOT NULL, last_error, params, errors, notes, rows_written "
                            "FROM raw.ingestion_runs WHERE job_type = %s ORDER BY id", (job,)).fetchall()

    try:
        yield fetch, (lambda: psycopg.connect(migrated_database)), conn
    finally:
        conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type LIKE 'tjb\\_%'")
        conn.close()


def test_a_pass_that_works_leaves_one_closed_completed_row(rows: Any) -> None:
    fetch, connect, _ = rows
    with job_book.booked("tjb_ok", connect) as p:
        assert p.run_id is not None
        job_book.count(3)
    [(status, closed, last_error, _params, errors, _notes, written)] = fetch("tjb_ok")
    assert (status, closed, last_error, errors, written) == ("completed", True, None, 0, 3)


def test_an_error_the_job_caught_and_logged_makes_the_pass_failed(rows: Any) -> None:
    fetch, connect, _ = rows
    with job_book.booked("tjb_logged", connect):
        log.error("tjb.failed", error="ValueError: the model said no")
    [(status, closed, last_error, _p, errors, _n, _w)] = fetch("tjb_logged")
    assert (status, closed, errors) == ("failed", True, 1)
    assert last_error is not None and "tjb.failed" in last_error and "the model said no" in last_error


def test_an_error_with_rows_written_is_partial(rows: Any) -> None:
    fetch, connect, _ = rows
    with job_book.booked("tjb_partial", connect):
        job_book.count(2)
        log.error("tjb.step_failed", error="one step failed")
    assert fetch("tjb_partial")[0][0] == "partial"


def test_an_exception_closes_the_row_and_goes_on(rows: Any) -> None:
    fetch, connect, _ = rows
    with pytest.raises(RuntimeError, match="boom"), job_book.booked("tjb_raises", connect):
        raise RuntimeError("boom")
    [(status, closed, last_error, *_rest)] = fetch("tjb_raises")
    assert (status, closed) == ("failed", True) and "boom" in (last_error or "")


def test_a_pass_that_is_cut_is_interrupted_not_failed(rows: Any) -> None:
    fetch, connect, _ = rows
    with pytest.raises(KeyboardInterrupt), job_book.booked("tjb_cut", connect):
        raise KeyboardInterrupt
    assert fetch("tjb_cut")[0][0] == "interrupted"


def test_a_pass_that_does_nothing_on_purpose_says_why(rows: Any) -> None:
    fetch, connect, _ = rows
    with job_book.booked("tjb_skip", connect):
        job_book.skip()
    [(status, closed, _le, params, errors, notes, _w)] = fetch("tjb_skip")
    assert (status, closed, errors) == ("completed", True, 0)
    assert params["skipped"] == job_book.SKIPPED_SWITCH_OFF and "omitida" in notes


def test_an_error_outside_a_booked_pass_is_nobodys(rows: Any) -> None:
    fetch, _connect, _ = rows
    log.error("tjb.unbooked", error="nobody is listening")
    assert job_book.current() is None and fetch("tjb_unbooked") == []


def test_the_ledger_never_stops_the_job(rows: Any) -> None:
    def broken() -> psycopg.Connection:
        raise psycopg.OperationalError("the database is down")

    ran: list[int] = []
    with job_book.booked("tjb_down", broken) as p:
        ran.append(1)
        log.error("tjb.failed", error="still counted in memory")
    assert ran == [1] and p.run_id is None and len(p.errors) == 1


def test_the_decorator_books_each_call_with_its_arguments(rows: Any) -> None:
    fetch, connect, _ = rows

    @job_book.booked_job("tjb_deco", lambda: connect)
    def work(x: int, *, y: int = 0) -> int:
        job_book.count(x + y)
        return x + y

    assert work(2, y=3) == 5 and work(1) == 1
    assert [r[0] for r in fetch("tjb_deco")] == ["completed", "completed"] and [r[6] for r in fetch("tjb_deco")] == [5, 1]


def test_a_job_of_the_heartbeat_without_a_row_is_reported_outside_the_book(rows: Any, migrated_database: str) -> None:
    _fetch, _connect, conn = rows
    conn.execute("DELETE FROM raw.worker_heartbeats WHERE worker_id = 'tjb-worker'")
    conn.execute("INSERT INTO raw.worker_heartbeats (worker_id, hostname, pid, code_version, started_at, last_beat_at, tick_interval_s, jobs) "
                 "VALUES ('tjb-worker', 'h', 1, 'x', now(), now(), 60, %s::jsonb)",
                 ('{"tjb_with_row": "2026-01-01T00:00:00+00:00", "tjb_without_row": "2026-01-01T00:00:00+00:00", '
                  '"tjb_alias": "2026-01-01T00:00:00+00:00"}',))
    conn.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) VALUES "
                 "('tjb_with_row', 'tjb_with_row', 'completed', now()), ('tjb_type_of_alias', 'tjb_type_of_alias', 'completed', now())")
    try:
        with psycopg.connect(migrated_database) as c:
            out = job_book.outside_the_book(c, type_of=lambda j: {"tjb_alias": "tjb_type_of_alias"}.get(j, j))
        assert "tjb_without_row" in out and "tjb_with_row" not in out
        assert "tjb_alias" not in out, "an id that is not its type counts as its type"
    finally:
        conn.execute("DELETE FROM raw.worker_heartbeats WHERE worker_id = 'tjb-worker'")


def test_a_real_job_of_the_scheduler_with_its_switch_off_leaves_an_omitted_row(rows: Any, migrated_database: str,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """The scheduler's own function, not the module: the wrapper is on it, the switch is off, the pass is booked as omitted with its reason."""
    from apps.worker import scheduler

    fetch, _connect, conn = rows
    monkeypatch.setattr(scheduler, "_connect", lambda: psycopg.connect(migrated_database))
    monkeypatch.setenv("FBI_DECISION_V2", "off")
    before = len(fetch("decision_v2_shadow"))
    try:
        scheduler._decision_v2_shadow_now()
        rows_now = fetch("decision_v2_shadow")
        assert len(rows_now) == before + 1
        status, closed, _le, params, errors, _notes, _w = rows_now[-1]
        assert (status, closed, errors) == ("completed", True, 0) and params["skipped"] == job_book.SKIPPED_SWITCH_OFF
    finally:
        conn.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'decision_v2_shadow'")
