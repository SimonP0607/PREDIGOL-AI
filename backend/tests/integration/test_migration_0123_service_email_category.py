"""Migration 0123 (the e-mail category «servicio», plan de cierre UX 4.1): two CHECK lists widen, nothing else.

Deploying must change nothing the system already stores: 0123 writes no row and adds no column. ``customer.messages_outbox``
accepts ``service`` and ``customer.preferences.email_off`` accepts it as one of the categories a reader may switch off - and
no other: a mandatory category in ``email_off`` and a category that does not exist are still refused. Going back is refused
while the queue holds a service e-mail or a reader switched the category off, and once none does it puts the older lists
back. Run on a scratch database at revision 0122, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0123"

OUTBOX = ("INSERT INTO customer.messages_outbox (user_id, category, template, locale, params, dedup_key) "
          "VALUES (%s, %s, %s, 'es', '{}'::jsonb, %s)")


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
                     "'intel', 'picks', 'raw', 'audit', 'customer') ORDER BY 1, 2, ordinal_position").fetchall()


def _refused(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), c.transaction():
        c.execute(sql, params)


def test_0123_widens_the_two_lists_and_goes_back_only_while_no_service_mail_or_choice_exists(
        migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0122")
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
            user = c.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                             "('svc@test.local', 'Svc', '$argon2id$x', 'USER') RETURNING id").fetchone()
            assert user
            u = user[0]
            c.execute("INSERT INTO customer.preferences (user_id, email_off) VALUES (%s, '{membership}')", (u,))
            c.execute(OUTBOX, (u, "support", "support_ticket_answered", "support:before-0123"))
            _refused(c, OUTBOX, (u, "service", "maintenance_scheduled", "service:before-0123"))
            _refused(c, "UPDATE customer.preferences SET email_off = '{service}' WHERE user_id = %s", (u,))
        command.upgrade(_cfg(), "0123")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less in any table"
            assert c.execute("SELECT email_off FROM customer.preferences WHERE user_id = %s", (u,)).fetchone() == (
                ["membership"],), "what a reader chose before is kept as it was"
            assert c.execute("SELECT category FROM customer.messages_outbox").fetchall() == [("support",)]
            c.execute("UPDATE customer.preferences SET email_off = '{membership,service}' WHERE user_id = %s", (u,))
            c.execute(OUTBOX, (u, "service", "maintenance_scheduled", "service:after-0123"))
            _refused(c, "UPDATE customer.preferences SET email_off = '{privacy}' WHERE user_id = %s", (u,))
            _refused(c, "UPDATE customer.preferences SET email_off = '{service,marketing}' WHERE user_id = %s", (u,))
            _refused(c, OUTBOX, (u, "servicio", "maintenance_scheduled", "service:not-a-category"))
            c.execute(OUTBOX, (u, "marketing", "weekly_digest", "marketing:still-accepted"))
        with pytest.raises(Exception, match="service e-mails"):
            command.downgrade(_cfg(), "0122")
        with psycopg.connect(dsn) as c:
            c.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            c.execute("DELETE FROM customer.messages_outbox WHERE category = 'service'")
        with pytest.raises(Exception, match="switched the category off"):
            command.downgrade(_cfg(), "0122")
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("UPDATE customer.preferences SET email_off = '{membership}' WHERE user_id = %s", (u,))
        command.downgrade(_cfg(), "0122")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before
            assert c.execute("SELECT category FROM customer.messages_outbox ORDER BY id").fetchall() == [
                ("support",), ("marketing",)], "the queue is kept"
            _refused(c, OUTBOX, (u, "service", "maintenance_scheduled", "service:gone-again"))
            _refused(c, "UPDATE customer.preferences SET email_off = '{service}' WHERE user_id = %s", (u,))
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
