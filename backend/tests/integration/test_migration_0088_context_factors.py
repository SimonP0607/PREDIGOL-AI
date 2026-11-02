"""Migration 0088 (the registry of context factors): additive, empty and reversible.

Deploying must change nothing the system does: it adds one table and one view, alters nothing that existed, writes no row - so every
factor is DESCRIPTIVE after it, which is where they all start - and leaves as it came. Run on a scratch database at revision 0087, the
way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0088"
TABLE = "intel.context_factors"
VIEW = "intel.context_factors_latest"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _exists(c: psycopg.Connection[Any], name: str) -> bool:
    row = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    """Every column of every table and view the migration must leave alone (all but its own two)."""
    own = {name.split(".")[1] for name in (TABLE, VIEW)}
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'market', 'models', 'intel', 'picks', 'raw') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if not (r[0] == "intel" and r[1] in own)]


def test_0088_adds_one_table_and_one_view_and_nothing_else_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0087")
        with psycopg.connect(dsn) as c:
            assert not _exists(c, TABLE) and not _exists(c, VIEW)
            before = _shape(c)

        command.upgrade(_cfg(), "0088")
        with psycopg.connect(dsn) as c:
            assert _exists(c, TABLE) and _exists(c, VIEW)
            assert _shape(c) == before, "nothing that existed was changed"
            assert c.execute(f"SELECT count(*) FROM {TABLE}").fetchone() == (0,), "the migration writes no row: every factor is DESCRIPTIVE"
            assert c.execute(f"SELECT count(*) FROM {VIEW}").fetchone() == (0,)
            indexes = {r[0] for r in c.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'intel' "
                                               "AND tablename = 'context_factors'").fetchall()}
            assert {"context_factors_pkey", "context_factors_first", "context_factors_next"} <= indexes
            triggers = {r[0] for r in c.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal",
                                                (TABLE,)).fetchall()}
            assert triggers == {"context_factors_append_only"}, "a decision is never edited or deleted afterwards"
            for name in (TABLE, VIEW):
                comment = c.execute("SELECT obj_description(%s::regclass)", (name,)).fetchone()
                assert comment is not None and comment[0], f"{name} says what it is"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0088",)

        command.downgrade(_cfg(), "0087")
        with psycopg.connect(dsn) as c:
            assert not _exists(c, TABLE) and not _exists(c, VIEW)
            assert _shape(c) == before, "and it leaves as it came"

        command.upgrade(_cfg(), "0088")  # and applies again
        with psycopg.connect(dsn) as c:
            assert _exists(c, TABLE) and _exists(c, VIEW)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
