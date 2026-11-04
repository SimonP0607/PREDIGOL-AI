"""Migration 0106 (each customer's state of the day, plan UX B11): one new table in ``customer`` and one more kind of
notice, nothing else.

Deploying must change nothing the system already stores: 0106 adds ``customer.lifecycle_snapshots``; every other table
keeps its columns. The table refuses a state that is not one of the seven, a reason that is not a code, an empty list of
reasons, a second row for the same reader and day, and an account deleted from under it. Its own trigger refuses an edit or
a delete. ``audit.notifications`` learns ``lifecycle_daily`` and nothing else. Going back drops the table while it is empty
and is refused once it holds history. Run on a scratch database at revision 0105, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0106"


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
                     "FROM information_schema.columns WHERE table_schema IN ('ai', 'auth', 'core', 'market', 'models', "
                     "'intel', 'picks', 'raw', 'audit', 'customer') AND NOT (table_schema = 'customer' "
                     "AND table_name = 'lifecycle_snapshots') ORDER BY 1, 2, ordinal_position").fetchall()


def _refused(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> None:
    with pytest.raises(psycopg.errors.IntegrityError), c.transaction():
        c.execute(sql, params)


ROW = "INSERT INTO customer.lifecycle_snapshots (user_id, day, state, reasons) VALUES (%s, %s, %s, %s)"
NOTICE = "INSERT INTO audit.notifications (kind, dedup_key, title, body, payload) VALUES (%s, %s, 't', 'b', '{}'::jsonb)"


def test_0106_adds_the_snapshots_and_goes_back_only_while_empty(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0105")
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
            _refused(c, NOTICE, ("lifecycle_daily", "k0"))  # not yet a kind
        command.upgrade(_cfg(), "0106")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there"
            c.execute(NOTICE, ("lifecycle_daily", "k1"))
            _refused(c, NOTICE, ("campaign", "k2"))  # the list stays closed
            user = c.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                             "('lc@test.local', 'Lc', '$argon2id$x', 'USER') RETURNING id").fetchone()
            assert user
            u = user[0]
            c.execute(ROW, (u, "2026-11-03", "at_risk", ["silent_7d", "low_survey"]))
            c.execute(ROW, (u, "2026-11-04", "expired", ["membership_expired"]))
            _refused(c, ROW, (u, "2026-11-03", "habitual", ["used_3_of_7_days"]))  # one row per reader and day
            _refused(c, ROW, (u, "2026-11-05", "vip", ["x"]))  # a state outside the seven
            _refused(c, ROW, (u, "2026-11-05", "habitual", []))  # no reasons
            _refused(c, ROW, (u, "2026-11-05", "habitual", ["Escribió Juan"]))  # not a code
            _refused(c, ROW, (u, "2026-11-05", "habitual", ["a@b.co"]))  # nor an address
            _refused(c, ROW, (u, "2026-11-05", "habitual", [f"r{i}" for i in range(9)]))  # too many
            with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
                c.execute("UPDATE customer.lifecycle_snapshots SET state = 'habitual'")
            with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
                c.execute("DELETE FROM customer.lifecycle_snapshots")
            with pytest.raises(psycopg.errors.ForeignKeyViolation), c.transaction():
                c.execute("DELETE FROM auth.users WHERE id = %s", (u,))
            assert c.execute("SELECT count(*) FROM customer.lifecycle_snapshots").fetchone() == (2,)
        with pytest.raises(Exception, match="history"):
            command.downgrade(_cfg(), "0105")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM customer.lifecycle_snapshots").fetchone() == (2,), "kept"
            with c.transaction():
                c.execute("SET LOCAL fbi.customer_maintenance = 'on'")
                c.execute("DELETE FROM customer.lifecycle_snapshots")
            c.execute("DELETE FROM audit.notifications WHERE kind = 'lifecycle_daily'")
        command.downgrade(_cfg(), "0105")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT to_regclass('customer.lifecycle_snapshots')").fetchone() == (None,)
            assert _shape(c) == before
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
