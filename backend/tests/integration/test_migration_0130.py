"""Migration 0130 (UX-081): two BRIN indexes by date, for the admin overview's 24-hour counts - additive, reversible, and nothing else moves.

The upgrade builds ``models.predictions (created_at)`` and ``picks.pick_candidates (evaluated_at)`` as BRIN indexes, valid; the
downgrade drops them and goes up again; running the upgrade's statements twice is harmless (``IF NOT EXISTS`` and the INVALID
index cleanup). Its own scratch database (``<FBI_TEST_DB>_m0130``), so it never collides with the other migration tests."""

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
            if not c.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:  # type: ignore[index]
                pytest.skip("marking an index invalid edits pg_index: it needs a superuser")
            # what an interrupted CREATE INDEX CONCURRENTLY leaves: an index of the name that the planner ignores
            c.execute("CREATE INDEX predictions_created_at_brin ON models.predictions USING BRIN (created_at)")
            c.execute("UPDATE pg_index SET indisvalid = false WHERE indexrelid = 'models.predictions_created_at_brin'::regclass")
            assert _indexes(c)["predictions_created_at_brin"] == ("brin", False)
        command.upgrade(_cfg(), "0130")
        with psycopg.connect(dsn) as c:
            assert _indexes(c) == dict.fromkeys(NAMES, ("brin", True))


def test_0130_waits_for_a_writer_without_making_other_writers_wait() -> None:
    """The first production try (OPS-003): a plain DROP INDEX asked for an ACCESS EXCLUSIVE lock and every new writer queued behind it.

    A transaction holding a write lock on ``models.predictions`` (the worker's batch) stays open for a few seconds while the revision
    runs over an INVALID leftover; meanwhile a second writer asks for the same write lock with NOWAIT, again and again: it must never be
    refused (a refusal means somebody's request is queued ahead of it), and the revision must finish once the first writer is done."""
    with scratch_at("0129") as dsn:
        with psycopg.connect(dsn, autocommit=True) as c:
            if not c.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()[0]:  # type: ignore[index]
                pytest.skip("marking an index invalid edits pg_index: it needs a superuser")
            c.execute("CREATE INDEX predictions_created_at_brin ON models.predictions USING BRIN (created_at)")
            c.execute("UPDATE pg_index SET indisvalid = false WHERE indexrelid = 'models.predictions_created_at_brin'::regclass")
        outcome: list[BaseException] = []

        def migrate() -> None:
            try:
                command.upgrade(_cfg(), "0130")
            except BaseException as error:
                outcome.append(error)

        refused = 0
        with psycopg.connect(dsn) as batch, psycopg.connect(dsn, autocommit=True) as other:
            batch.execute("LOCK TABLE models.predictions IN ROW EXCLUSIVE MODE")  # the worker's batch, still open
            runner = threading.Thread(target=migrate)
            runner.start()
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                try:
                    with other.transaction():
                        other.execute("LOCK TABLE models.predictions IN ROW EXCLUSIVE MODE NOWAIT")
                except psycopg.errors.LockNotAvailable:
                    refused += 1
                time.sleep(0.1)
            batch.commit()  # the batch ends: the revision may go on
            runner.join(timeout=60)
        assert not runner.is_alive(), "the revision did not finish after the writer ended"
        assert not outcome, outcome
        assert refused == 0, f"{refused} write request(s) were queued behind the revision"
        with psycopg.connect(dsn) as c:
            assert _indexes(c) == dict.fromkeys(NAMES, ("brin", True))


def test_0130_is_the_single_head_on_top_of_0129() -> None:
    script = ScriptDirectory.from_config(_cfg())
    heads = script.get_heads()
    assert len(heads) == 1, heads
    revision = script.get_revision("0130")
    assert revision is not None and revision.down_revision == "0129"
    assert "0130" in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}, heads
