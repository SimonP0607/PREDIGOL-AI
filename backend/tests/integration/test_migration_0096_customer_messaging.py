"""Migration 0096 (the messages to readers, plan UX A5): two new tables and six more notification kinds, nothing else.

Deploying must change nothing the system already stores: 0096 adds ``customer.messages_outbox`` and
``customer.preferences`` and widens the CHECK of ``audit.notifications.kind``; every other table keeps its columns and
its rows. Going back drops the two tables only while they are empty (a sent message is a record), and the notices of
the new kinds already written stay (the older CHECK comes back NOT VALID). Run on a scratch database at revision
0095, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0096"
HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaGhhc2hoYXNoaGFzaA"  # gitleaks:allow - not a password's


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
                     "'intel', 'picks', 'raw', 'audit') OR (table_schema = 'customer' AND table_name IN "
                     "('consents', 'support_tickets', 'ticket_messages')) ORDER BY 1, 2, ordinal_position").fetchall()


def _tables(c: psycopg.Connection[Any]) -> set[str]:
    return {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables "
                                    "WHERE table_schema = 'customer'").fetchall()}


def test_0096_adds_the_queue_and_the_preferences_and_goes_back_only_while_they_are_empty(
        migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0095")
        with psycopg.connect(dsn) as c:
            c.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES ('r@example.org', 'R', %s)",
                      (HASH,))
            c.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body) "
                      "VALUES ('ai_budget', 'ai_budget:2026-10:50', 't', 'b')")
            c.commit()
            before = _shape(c)
            notes = c.execute("SELECT id, kind, dedup_key FROM audit.notifications ORDER BY id").fetchall()
            assert _tables(c) == {"consents", "support_tickets", "ticket_messages"}

        command.upgrade(_cfg(), "0096")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there"
            assert c.execute("SELECT id, kind, dedup_key FROM audit.notifications ORDER BY id").fetchall() == notes
            assert _tables(c) == {"consents", "support_tickets", "ticket_messages", "messages_outbox", "preferences"}
            for kind in ("outbox_failing", "membership_due", "ticket_new", "privacy_due", "synthetic_failed",
                         "ai_user_budget"):
                c.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body) VALUES (%s, %s, 't', 'b')",
                          (kind, f"{kind}:m0096"))
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body) "
                          "VALUES ('reader_email', 'x:m0096', 't', 'b')")
            c.rollback()
            c.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body) "
                      "VALUES ('ticket_new', 'ticket_new:1', 't', 'b')")
            c.execute("""
                INSERT INTO customer.messages_outbox (user_id, category, template, locale, params, dedup_key)
                SELECT id, 'privacy', 'privacy_request_answered', 'es', '{"request": "privacy_query", "ticket": "1"}',
                       'privacy_request_answered:1' FROM auth.users
            """)
            c.commit()
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0096",)

        with pytest.raises(Exception, match="hold rows"):
            command.downgrade(_cfg(), "0095")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0096",)
            assert c.execute("SELECT count(*) FROM customer.messages_outbox").fetchone() == (1,)
            c.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            c.execute("DELETE FROM customer.messages_outbox")
            c.commit()

        command.downgrade(_cfg(), "0095")
        with psycopg.connect(dsn) as c:
            assert _tables(c) == {"consents", "support_tickets", "ticket_messages"} and _shape(c) == before
            assert c.execute("SELECT count(*) FROM audit.notifications WHERE kind = 'ticket_new'").fetchone() == (1,)
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body) "
                          "VALUES ('ticket_new', 'ticket_new:2', 't', 'b')")
            c.rollback()
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0095",)
        command.upgrade(_cfg(), "0096")  # and forward again: the step is repeatable
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
