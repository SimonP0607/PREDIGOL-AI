"""Migration 0130 (UX-081, corrected by BE-025): two BRIN indexes by date, for the admin overview's 24-hour counts - additive, reversible, and nothing else moves.

The upgrade builds ``models.predictions (created_at)`` and ``picks.pick_candidates (evaluated_at)`` as BRIN indexes, valid; the
downgrade drops them and goes up again; running the upgrade's statements twice is harmless (``IF NOT EXISTS`` and the INVALID
index cleanup); and it waits for the worker's long write transactions instead of giving up (BE-025). Its own scratch database (``<FBI_TEST_DB>_m0130``), so it never collides with the other migration tests."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory

from tests.integration.conftest import ADMIN_URL, TEST_DB, _dsn
from tests.integration.test_migration_0111 import _cfg

pytestmark = pytest.mark.integration

SCRATCH = f"{TEST_DB}_m0130"
NAMES = ("predictions_created_at_brin", "pick_candidates_evaluated_at_brin")
HOLD = 12  # seconds a writer keeps the table: longer than the 10 s the first production attempt allowed itself


def _drop(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                      (name,))
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


@contextmanager
def scratch_at(revision: str) -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop(SCRATCH)
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), revision)
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop(SCRATCH)


@contextmanager
def writer_inside(dsn: str, seconds: float = HOLD) -> Iterator[None]:
    """A transaction that holds a write lock on ``models.predictions`` for ``seconds`` - what the worker does all day. Yields once the
    lock is held; leaving the block waits for the transaction to end."""
    held = threading.Event()
    errors: list[BaseException] = []

    def hold() -> None:
        try:
            with psycopg.connect(dsn) as c:
                c.execute("LOCK TABLE models.predictions IN ROW EXCLUSIVE MODE")
                held.set()
                time.sleep(seconds)
        except BaseException as exc:
            errors.append(exc)
            held.set()

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert held.wait(30), "the writer never took its lock"
        yield
    finally:
        thread.join()
    if errors:
        raise errors[0]


def _indexes(c: psycopg.Connection) -> dict[str, tuple[str, bool]]:
    """name -> (access method, valid) of the two indexes, for those that exist."""
    rows = c.execute("SELECT c.relname, am.amname, i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                     "JOIN pg_am am ON am.oid = c.relam WHERE c.relname = ANY(%s)", (list(NAMES),)).fetchall()
    return {name: (method, bool(valid)) for name, method, valid in rows}


def test_0130_builds_two_valid_brin_indexes_and_goes_down_and_up_again() -> None:
    with scratch_at("0129") as dsn:
        with psycopg.connect(dsn) as c:
            assert _indexes(c) == {}
        command.upgrade(_cfg(), "0130")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0130",)
            assert _indexes(c) == dict.fromkeys(NAMES, ("brin", True))
            comment = c.execute("SELECT obj_description('models.predictions_created_at_brin'::regclass, 'pg_class')").fetchone()
            assert comment is not None and "0130" in comment[0]
        command.downgrade(_cfg(), "0129")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0129",)
            assert _indexes(c) == {}
        command.upgrade(_cfg(), "0130")
        with psycopg.connect(dsn) as c:
            assert _indexes(c) == dict.fromkeys(NAMES, ("brin", True))


def test_0130_replaces_an_index_left_invalid_by_an_interrupted_build() -> None:
    with scratch_at("0129") as dsn:
        with psycopg.connect(dsn, autocommit=True) as c:
            if not _leave_an_invalid_index(c):
                pytest.skip("marking an index invalid edits pg_index: it needs a superuser")
            assert _indexes(c)["predictions_created_at_brin"] == ("brin", False)
        command.upgrade(_cfg(), "0130")
        with psycopg.connect(dsn) as c:
            assert _indexes(c) == dict.fromkeys(NAMES, ("brin", True))


def _leave_an_invalid_index(c: psycopg.Connection) -> bool:
    """What an interrupted CREATE INDEX CONCURRENTLY leaves: an index of the name that the planner ignores. False when marking one
    invalid (an edit of pg_index) needs a superuser the test does not have."""
    if not c.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:  # type: ignore[index]
        return False
    c.execute("CREATE INDEX predictions_created_at_brin ON models.predictions USING BRIN (created_at)")
    c.execute("UPDATE pg_index SET indisvalid = false WHERE indexrelid = 'models.predictions_created_at_brin'::regclass")
    return True


def test_0130_waits_for_a_writer_that_stays_in_the_table_longer_than_ten_seconds() -> None:
    """The first production attempt (2026-11-09) cancelled itself after 10 s: CONCURRENTLY waits for the transactions already writing to
    the table, and the worker's last tens of seconds. Here a writer holds the table for 12 s while the upgrade runs."""
    with scratch_at("0129") as dsn:
        with writer_inside(dsn):
            started = time.monotonic()
            command.upgrade(_cfg(), "0130")
            waited = time.monotonic() - started
        assert waited >= HOLD - 3, f"it did not wait for the writer ({waited:.1f} s)"
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0130",)
            assert _indexes(c) == dict.fromkeys(NAMES, ("brin", True))


def test_0130_replaces_an_invalid_index_without_asking_for_the_table_exclusively() -> None:
    """The second production attempt failed in the cleanup: a plain DROP INDEX asks for an ACCESS EXCLUSIVE lock on the table, behind the
    worker's writers, and gave up after 10 s. The cleanup now waits the way the build does."""
    with scratch_at("0129") as dsn:
        with psycopg.connect(dsn, autocommit=True) as c:
            if not _leave_an_invalid_index(c):
                pytest.skip("marking an index invalid edits pg_index: it needs a superuser")
            assert _indexes(c)["predictions_created_at_brin"] == ("brin", False)
        with writer_inside(dsn):
            command.upgrade(_cfg(), "0130")
        with psycopg.connect(dsn) as c:
            assert _indexes(c) == dict.fromkeys(NAMES, ("brin", True))


def test_0130_is_the_single_head_on_top_of_0129() -> None:
    script = ScriptDirectory.from_config(_cfg())
    heads = script.get_heads()
    assert len(heads) == 1, heads
    revision = script.get_revision("0130")
    assert revision is not None and revision.down_revision == "0129"
    assert "0130" in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}, heads
