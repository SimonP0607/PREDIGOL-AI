"""Migration 0094 (an index for an address's sign-in streak, plan UX A1): one partial index, no column, no row.

Deploying must change nothing the system stores: 0094 adds ``auth.audit_events_signin_idx`` on (email, at DESC) for
the five actions a streak is made of, so fbi.auth.store.address_streak reads an address's own rows instead of thirty
days of the whole trail. No table or column changes and no row is written; going back drops the index and nothing
else. Run on a scratch database at revision 0093, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0094"


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
                     "'intel', 'picks', 'raw', 'audit') ORDER BY 1, 2, ordinal_position").fetchall()


def _index(c: psycopg.Connection[Any]) -> str | None:
    row = c.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = 'auth' "
                    "AND indexname = 'audit_events_signin_idx'").fetchone()
    return None if row is None else str(row[0])


def test_0094_adds_one_partial_index_and_the_downgrade_drops_only_it(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0093")
        with psycopg.connect(dsn) as c:
            c.execute("INSERT INTO auth.audit_events (action, email, detail) VALUES "
                      "('login.failed', 'someone@example.com', '{}'), ('logout', 'someone@example.com', '{}')")
            c.commit()
            before = _shape(c)
            rows = c.execute("SELECT id, action, email FROM auth.audit_events ORDER BY id").fetchall()
            assert _index(c) is None

        command.upgrade(_cfg(), "0094")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before, "not a column more or less, in any table"
            assert c.execute("SELECT id, action, email FROM auth.audit_events ORDER BY id").fetchall() == rows
            index = _index(c)
            assert index is not None and "(email, at DESC)" in index, index
            for action in ("login.failed", "mfa.failed", "login.succeeded", "user.unlocked", "password.reset"):
                assert action in index, (action, index)
            assert "logout" not in index, "only the actions a streak is made of"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0094",)

        command.downgrade(_cfg(), "0093")
        with psycopg.connect(dsn) as c:
            assert _index(c) is None and _shape(c) == before
            assert c.execute("SELECT id, action, email FROM auth.audit_events ORDER BY id").fetchall() == rows
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0093",)

        command.upgrade(_cfg(), "0094")  # and applies again
        with psycopg.connect(dsn) as c:
            assert _index(c) is not None
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
