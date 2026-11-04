"""Migration 0097 (product analytics, plan UX A6): two new tables, nothing else.

Deploying must change nothing the system already stores: 0097 adds ``customer.product_events`` and
``customer.activity_daily``; every other table keeps its columns and its rows. Going back drops them only while they
are empty. Run on a scratch database at revision 0096, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0097"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('auth', 'core', 'market', 'models', "
                     "'intel', 'picks', 'raw', 'audit', 'customer') AND table_name NOT IN "
                     "('product_events', 'activity_daily') ORDER BY 1, 2, ordinal_position").fetchall()


def _tables(c: psycopg.Connection[Any]) -> set[str]:
    return {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables "
                                    "WHERE table_schema = 'customer'").fetchall()}


def test_0097_adds_the_two_tables_and_goes_back_only_while_they_are_empty(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0096")
        with psycopg.connect(dsn) as c:
            before = _shape(c)
            tables = _tables(c)
            assert "product_events" not in tables
        command.upgrade(_cfg(), "0097")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there"
            assert _tables(c) == tables | {"product_events", "activity_daily"}
            for bad in ("INSERT INTO customer.product_events (subject, name) VALUES ('7', 'match_opened')",
                        "INSERT INTO customer.product_events (subject, name) VALUES ('" + "a" * 20 + "', 'Match Opened')",
                        "INSERT INTO customer.product_events (subject, name, props) VALUES ('" + "a" * 20 +
                        "', 'match_opened', '[1]')"):
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute(bad)
                c.rollback()
            c.execute("INSERT INTO customer.product_events (subject, name) VALUES (%s, 'match_opened')", ("a" * 20,))
            c.commit()
        with pytest.raises(Exception, match="hold rows"):
            command.downgrade(_cfg(), "0096")
        with psycopg.connect(dsn) as c:
            c.execute("DELETE FROM customer.product_events")
            c.commit()
        command.downgrade(_cfg(), "0096")
        with psycopg.connect(dsn) as c:
            assert _tables(c) == tables and _shape(c) == before
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0096",)
        command.upgrade(_cfg(), "0097")
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
