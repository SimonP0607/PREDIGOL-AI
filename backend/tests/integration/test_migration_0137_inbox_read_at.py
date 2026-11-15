"""Migration 0137 (decision 1 of the plan maestro UX/UI 2026, BE-041): ``customer.push_notices.read_at`` and the inbox's
index - and nothing else. A notice already kept stays as it was, unread; going back drops both. Run on a scratch database
at revision 0136, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0137"


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
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('ai', 'auth', 'core', 'market', 'models', "
                     "'intel', 'picks', 'raw', 'audit', 'customer') ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if (r[0], r[1], r[2]) != ("customer", "push_notices", "read_at")]


def test_0137_adds_read_at_leaves_every_notice_unread_and_goes_back_clean(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0136")
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
            user = c.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                             "('inbox137@test.local', 'Inbox', '$argon2id$x', 'USER') RETURNING id").fetchone()
            assert user
            u = user[0]
            c.execute("INSERT INTO customer.push_notices (user_id, category, dedup_key, title, body, url, expires_at) "
                      "VALUES (%s, 'account', 'account:test137', 'T', 'B', '/home', now() + interval '1 hour')", (u,))
        command.upgrade(_cfg(), "0137")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less anywhere else"
            assert c.execute("SELECT title, status, read_at FROM customer.push_notices WHERE user_id = %s",
                             (u,)).fetchone() == ("T", "queued", None), "kept as it was, unread"
            assert c.execute("SELECT 1 FROM pg_indexes WHERE schemaname = 'customer' AND indexname = 'push_notices_inbox'"
                             ).fetchone() == (1,)
            c.execute("UPDATE customer.push_notices SET read_at = now() WHERE user_id = %s", (u,))
        command.downgrade(_cfg(), "0136")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before
            assert c.execute("SELECT title FROM customer.push_notices WHERE user_id = %s", (u,)).fetchone() == ("T",)
            assert c.execute("SELECT 1 FROM pg_indexes WHERE schemaname = 'customer' AND indexname = 'push_notices_inbox'"
                             ).fetchone() is None
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
