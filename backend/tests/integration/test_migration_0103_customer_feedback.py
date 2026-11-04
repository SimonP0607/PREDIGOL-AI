"""Migration 0103 (what readers think of PrediGol, plan UX B6): one new table in ``customer``, nothing else.

Deploying must change nothing the system already stores: 0103 adds ``customer.feedback``; every other table keeps its
columns. The table refuses what it must never hold - a survey without its score, a comment on anything but a survey, a
vote without what it is about, a second vote on the same thing read, a comment past 1,000 characters, a context that is not
an object - and never lets an account be deleted from under it (an account is anonymised, A7). Going back drops it while it
is empty and is refused once readers answered. Run on a scratch database at revision 0102, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0103"


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
                     "AND table_name = 'feedback') ORDER BY 1, 2, ordinal_position").fetchall()


def _refused(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> None:
    with pytest.raises(psycopg.errors.IntegrityError), c.transaction():
        c.execute(sql, params)


ROW = ("INSERT INTO customer.feedback (user_id, kind, score, comment, subject, subject_id, helpful, context) "
       "VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)")


def test_0103_adds_the_feedback_and_goes_back_only_while_nobody_answered(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0102")
        with psycopg.connect(dsn) as c:
            before = _shape(c)
        command.upgrade(_cfg(), "0103")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there"
            user = c.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                             "('fb@test.local', 'Fb', '$argon2id$x', 'USER') RETURNING id").fetchone()
            assert user
            u = user[0]
            c.execute(ROW, (u, "csat", 4, "Muy útil", None, None, None, '{"trigger": "analysis_opened"}'))
            c.execute(ROW, (u, "csat_skipped", None, None, None, None, None, "{}"))
            c.execute(ROW, (u, "helpful", None, None, "reading", 42, True, "{}"))
            c.execute(ROW, (u, "helpful", None, None, "narrative", 42, False, "{}"))  # another thing read
            _refused(c, ROW, (u, "helpful", None, None, "reading", 42, False, "{}"))  # the same thing read twice
            _refused(c, ROW, (u, "csat", None, None, None, None, None, "{}"))  # a survey without its score
            _refused(c, ROW, (u, "csat", 6, None, None, None, None, "{}"))  # a score past 5
            _refused(c, ROW, (u, "csat_skipped", 3, None, None, None, None, "{}"))  # a skip with a score
            _refused(c, ROW, (u, "csat_skipped", None, "hola", None, None, None, "{}"))  # a comment on a skip
            _refused(c, ROW, (u, "helpful", None, None, "reading", None, True, "{}"))  # a vote without its thing
            _refused(c, ROW, (u, "helpful", None, None, "rumour", 7, True, "{}"))  # another kind of thing
            _refused(c, ROW, (u, "helpful", None, None, "reading", 7, None, "{}"))  # a vote without its answer
            _refused(c, ROW, (u, "csat", 3, "x" * 1001, None, None, None, "{}"))  # a comment past its limit
            _refused(c, ROW, (u, "csat", 3, "", None, None, None, "{}"))  # an empty comment is no comment
            _refused(c, ROW, (u, "csat", 3, None, None, None, None, "[]"))  # a context that is not an object
            _refused(c, ROW, (u, "opinion", 3, None, None, None, None, "{}"))  # another kind
            with pytest.raises(psycopg.errors.ForeignKeyViolation), c.transaction():
                c.execute("DELETE FROM auth.users WHERE id = %s", (u,))  # an account is anonymised, never deleted
            assert c.execute("SELECT count(*) FROM customer.feedback").fetchone() == (4,)
        with pytest.raises(Exception, match="readers' answers"):
            command.downgrade(_cfg(), "0102")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM customer.feedback").fetchone() == (4,), "the answers are kept"
            c.execute("DELETE FROM customer.feedback")
        command.downgrade(_cfg(), "0102")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT to_regclass('customer.feedback')").fetchone() == (None,)
            assert _shape(c) == before
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
