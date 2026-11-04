"""Migration 0098 (account and access, plan UX A7): one new table and two more states of an account, nothing else.

Deploying must change nothing the system already stores: 0098 adds ``auth.account_tokens`` and lets
``auth.users.status`` be ``invited`` or ``deleted``; every other table keeps its columns and its rows, and every
account keeps its state. The table has no room for a link, an IP or a device. Going back is refused while an account
is invited or deleted (the previous code knows only active and disabled). Run on a scratch database at revision 0097,
the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0098"
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
                     "'intel', 'picks', 'raw', 'audit', 'customer') AND table_name <> 'account_tokens' "
                     "ORDER BY 1, 2, ordinal_position").fetchall()


def _accounts(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return c.execute("SELECT id, email, status, role, password_hash FROM auth.users ORDER BY id").fetchall()


def test_0098_adds_the_links_and_the_two_states_and_goes_back_only_without_them(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0097")
        with psycopg.connect(dsn) as c:
            for email, status in (("a@predigol.test", "active"), ("d@predigol.test", "disabled")):
                c.execute("INSERT INTO auth.users (email, display_name, password_hash, status) VALUES (%s, 'x', %s, %s)",
                          (email, HASH, status))
            c.commit()
            before, accounts = _shape(c), _accounts(c)
        command.upgrade(_cfg(), "0098")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there"
            assert _accounts(c) == accounts, "every account keeps its state"
            columns = [r[0] for r in c.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = 'auth' "
                "AND table_name = 'account_tokens' ORDER BY ordinal_position").fetchall()]
            assert columns == ["id", "user_id", "purpose", "nonce", "token_hash", "created_at", "sent_at",
                               "expires_at", "used_at", "revoked_at", "revoked_reason"]
            row = c.execute("SELECT id FROM auth.users WHERE email = 'a@predigol.test'").fetchone()
            assert row is not None
            uid = row[0]
            nonce = b"n" * 32
            refused = (
                ("INSERT INTO auth.account_tokens (user_id, purpose, nonce) VALUES (%s, 'login', %s)", (uid, nonce)),
                ("INSERT INTO auth.account_tokens (user_id, purpose, nonce) VALUES (%s, 'reset', %s)", (uid, b"n")),
                # a hash without the moment it was sent, a link sent without its expiry, a raw token for a hash
                ("INSERT INTO auth.account_tokens (user_id, purpose, nonce, token_hash) VALUES (%s, 'reset', %s, %s)",
                 (uid, nonce, "a" * 64)),
                ("INSERT INTO auth.account_tokens (user_id, purpose, nonce, token_hash, sent_at) "
                 "VALUES (%s, 'reset', %s, %s, now())", (uid, nonce, "a" * 64)),
                ("INSERT INTO auth.account_tokens (user_id, purpose, nonce, token_hash, sent_at, expires_at) "
                 "VALUES (%s, 'reset', %s, %s, now(), now() + interval '1 hour')", (uid, nonce, "x" * 43)),
                # used and revoked at once; revoked without a reason; used before being sent
                ("INSERT INTO auth.account_tokens (user_id, purpose, nonce, token_hash, sent_at, expires_at, used_at, "
                 "revoked_at, revoked_reason) VALUES (%s, 'reset', %s, %s, now(), now() + interval '1 hour', now(), "
                 "now(), 'superseded')", (uid, nonce, "b" * 64)),
                ("INSERT INTO auth.account_tokens (user_id, purpose, nonce, revoked_at) VALUES (%s, 'reset', %s, now())",
                 (uid, nonce)),
                ("INSERT INTO auth.account_tokens (user_id, purpose, nonce, used_at) VALUES (%s, 'reset', %s, now())",
                 (uid, nonce)),
                ("UPDATE auth.users SET status = 'pending' WHERE id = %s", (uid,)),
            )
            for sql, params in refused:
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute(sql, params)
                c.rollback()
            c.execute("INSERT INTO auth.account_tokens (user_id, purpose, nonce) VALUES (%s, 'invite', %s)",
                      (uid, nonce))
            c.execute("INSERT INTO auth.users (email, display_name, password_hash, status) "
                      "VALUES ('i@predigol.test', 'i', %s, 'invited')", (HASH,))
            c.commit()
        with pytest.raises(Exception, match="invited or deleted"):
            command.downgrade(_cfg(), "0097")
        with psycopg.connect(dsn) as c:
            c.execute("DELETE FROM auth.users WHERE status = 'invited'")
            c.commit()
        command.downgrade(_cfg(), "0097")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before
            assert c.execute("SELECT to_regclass('auth.account_tokens')").fetchone() == (None,)
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("UPDATE auth.users SET status = 'invited'")
    finally:
        if previous is not None:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
