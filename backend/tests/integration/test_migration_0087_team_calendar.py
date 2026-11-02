"""Migration 0087 (every team's calendar in every competition, apart from the matches PrediGol follows): additive and reversible.

Deploying must change nothing the system does: it adds two tables and two views, alters nothing that existed, writes no row, and leaves as
it came. Run on a scratch database at revision 0086, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0087"
TABLES = ("core.calendar_matches", "core.calendar_fetches")
VIEWS = ("core.calendar_matches_latest", "core.team_calendar")


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
    """Every column of every table and view the migration must leave alone (all but its own four)."""
    own = {name.split(".")[1] for name in (*TABLES, *VIEWS)}
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'market', 'models', 'intel', 'picks', 'raw') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if not (r[0] == "core" and r[1] in own)]


def test_0087_adds_two_tables_and_two_views_and_nothing_else_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0086")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, name) for name in (*TABLES, *VIEWS))
            before = _shape(c)

        command.upgrade(_cfg(), "0087")
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, name) for name in (*TABLES, *VIEWS))
            assert _shape(c) == before, "nothing that existed was changed"
            for name in TABLES:
                assert c.execute(f"SELECT count(*) FROM {name}").fetchone() == (0,), "the migration writes no row"
            for name in VIEWS:
                assert c.execute(f"SELECT count(*) FROM {name}").fetchone() == (0,)
            indexes = {r[0] for r in c.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'core' AND tablename IN "
                                               "('calendar_matches', 'calendar_fetches')").fetchall()}
            assert {"calendar_matches_pkey", "calendar_matches_home", "calendar_matches_away", "calendar_fetches_pkey",
                    "calendar_fetches_read"} <= indexes
            for name in (*TABLES, *VIEWS):
                assert c.execute("SELECT obj_description(%s::regclass)", (name,)).fetchone() != (None,) or name.endswith("_latest"), \
                    f"{name} says what it is"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0087",)

        command.downgrade(_cfg(), "0086")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, name) for name in (*TABLES, *VIEWS))
            assert _shape(c) == before, "and it leaves as it came"

        command.upgrade(_cfg(), "0087")  # and applies again
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, name) for name in (*TABLES, *VIEWS))
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
