"""Migration 0105 (the weekly summary by e-mail, plan UX B8): two lists the database checks learn a word each, nothing else.

Deploying must change nothing the system already stores: every table keeps its columns and every row; the queue accepts
the category ``marketing`` and the consents the source ``email`` - and still refuses every other word. Going back puts both
lists back while no queued e-mail is commercial and no decision came from an e-mail, and is refused once one exists. Run on
a scratch database at revision 0104, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0105"
SHA = "a" * 64
CONSENT = ("INSERT INTO customer.consents (user_id, kind, granted, document, version, sha256, locale, statement, source) "
           "VALUES (%s, %s, %s, 'privacy', '2026-10-27-draft2', %s, 'es', 'Quiero el resumen', %s)")
MESSAGE = ("INSERT INTO customer.messages_outbox (user_id, category, template, locale, params, dedup_key) "
           "VALUES (%s, %s, 'weekly_digest', 'es', '{}', %s)")


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


def _one(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> Any:
    row = c.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


def test_0105_lets_the_queue_hold_commercial_mail_and_a_decision_come_from_an_email_and_goes_back_while_none_does(
        migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0104")
        with psycopg.connect(dsn, autocommit=True) as c:
            u = _one(c, "INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                        "('digest@test.local', 'Digest', '$argon2id$x', 'USER') RETURNING id")
            c.execute(CONSENT, (u, "privacy", True, SHA, "gate"))
            _refused(c, MESSAGE, (u, "marketing", "weekly:before"))  # 0104 does not know commercial mail
            _refused(c, CONSENT, (u, "marketing_email", False, SHA, "email"))  # nor a decision from an e-mail
            before = _shape(c)
            rows = _one(c, "SELECT count(*) FROM customer.consents")
        command.upgrade(_cfg(), "0105")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less anywhere"
            assert _one(c, "SELECT count(*) FROM customer.consents") == rows
            assert _one(c, "SELECT version_num FROM alembic_version") == "0105"
            for word in ("account", "security", "membership", "support", "privacy", "legal", "marketing"):
                c.execute(MESSAGE, (u, word, f"key:{word}:0105"))
            _refused(c, MESSAGE, (u, "promotion", "key:promotion:0105"))  # still a closed list
            c.execute(CONSENT, (u, "marketing_email", True, SHA, "profile"))
            c.execute(CONSENT, (u, "marketing_email", False, SHA, "email"))
            _refused(c, CONSENT, (u, "marketing_email", False, SHA, "link"))
        # commercial mail queued and a decision from an e-mail: going back is refused
        with pytest.raises(Exception, match=r"commercial e-mails or customer\.consents decisions"):
            command.downgrade(_cfg(), "0104")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _one(c, "SELECT version_num FROM alembic_version") == "0105"
            with c.transaction():
                c.execute("SET LOCAL fbi.customer_maintenance = 'on'")
                c.execute("DELETE FROM customer.messages_outbox WHERE category = 'marketing'")
        with pytest.raises(Exception, match=r"commercial e-mails or customer\.consents decisions"):
            command.downgrade(_cfg(), "0104")  # the decision from an e-mail is still there
        with psycopg.connect(dsn, autocommit=True) as c, c.transaction():
            c.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            c.execute("DELETE FROM customer.consents WHERE source = 'email'")
        command.downgrade(_cfg(), "0104")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _one(c, "SELECT version_num FROM alembic_version") == "0104"
            _refused(c, MESSAGE, (u, "marketing", "key:marketing:after"))
            _refused(c, CONSENT, (u, "marketing_email", False, SHA, "email"))
            assert _shape(c) == before
        command.upgrade(_cfg(), "0105")
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
