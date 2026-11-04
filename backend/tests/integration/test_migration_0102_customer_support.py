"""Migration 0102 (a support ticket's category, context and effort; a message's channel - plan UX, A14): four columns on
two tables of A4, nothing else.

Deploying must change nothing the system already stores: the privacy requests written before A14 become ``privacy``,
their messages ``web``, every other table keeps its columns, and the code before A14 - which writes a request without a
category - keeps working (a trigger gives it the category). The columns refuse what they must never hold: a privacy
category on a support ticket or the reverse, an unknown category, a context that is not an object or is too long, an effort
out of range, on an open ticket or on a privacy request; and once written the category and the context never change, nor
the effort once given. Going back is refused while a support ticket or a message noted from WhatsApp exists, and otherwise
leaves the tables as 0101 had them. Run on a scratch database at revision 0101, the way production does."""

from __future__ import annotations

import json
import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0102"


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
                     "'intel', 'picks', 'raw', 'audit', 'customer') AND NOT (table_schema = 'customer' AND "
                     "((table_name = 'support_tickets' AND column_name IN ('category', 'context', 'effort')) OR "
                     "(table_name = 'ticket_messages' AND column_name = 'channel'))) ORDER BY 1, 2, ordinal_position"
                     ).fetchall()


def _refused(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> None:
    with pytest.raises(psycopg.errors.IntegrityError), c.transaction():
        c.execute(sql, params)


# What the code before A14 writes (fbi.customer.privacy.open_request of A13): no category.
OLD_REQUEST = ("INSERT INTO customer.support_tickets (user_id, kind, due_on) VALUES (%s, 'privacy_query', "
               "current_date + 14) RETURNING id")
OLD_MESSAGE = "INSERT INTO customer.ticket_messages (ticket_id, author, body) VALUES (%s, 'customer', 'Hola')"
TICKET = ("INSERT INTO customer.support_tickets (user_id, kind, category, context) VALUES (%s, %s, %s, %s) "
          "RETURNING id")


def test_0102_keeps_what_was_there_and_the_code_before_working(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0101")
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
            user = c.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES "
                             "('sup@test.local', 'Sup', '$argon2id$x', 'USER') RETURNING id").fetchone()
            assert user is not None
            u = user[0]
            old = c.execute(OLD_REQUEST, (u,)).fetchone()
            assert old is not None
            c.execute(OLD_MESSAGE, (old[0],))
        command.upgrade(_cfg(), "0102")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there, but the four"
            assert c.execute("SELECT category, context, effort FROM customer.support_tickets").fetchall() == [
                ("privacy", None, None)], "the request written before A14 is a privacy one"
            assert c.execute("SELECT channel FROM customer.ticket_messages").fetchall() == [("web",)]
            # the code before A14 keeps working: its requests get their category from the trigger
            again = c.execute(OLD_REQUEST.replace("privacy_query", "privacy_claim"), (u,)).fetchone()
            assert again is not None
            c.execute(OLD_MESSAGE, (again[0],))
            assert c.execute("SELECT category FROM customer.support_tickets WHERE id = %s", (again[0],)).fetchone() == (
                "privacy",)
            plain = c.execute("INSERT INTO customer.support_tickets (user_id, kind) VALUES (%s, 'support') RETURNING id",
                              (u,)).fetchone()
            assert plain is not None
            assert c.execute("SELECT category FROM customer.support_tickets WHERE id = %s", (plain[0],)).fetchone() == (
                "technical",)
            # what the columns refuse
            ctx = json.dumps({"route": "/matches/1", "device": "phone"})
            _refused(c, TICKET, (u, "support", "privacy", None))  # a privacy category on a support ticket
            _refused(c, "INSERT INTO customer.support_tickets (user_id, kind, category, due_on) VALUES "
                        "(%s, 'privacy_query', 'technical', current_date)", (u,))  # a support category on a request
            _refused(c, TICKET, (u, "support", "billing", None))  # an unknown category
            _refused(c, TICKET, (u, "support", "technical", json.dumps(["a"])))  # a context that is not an object
            _refused(c, TICKET, (u, "support", "technical", json.dumps({"route": "/" + "x" * 2100})))  # too long
            ticket = c.execute(TICKET, (u, "support", "wrong_data", ctx)).fetchone()
            assert ticket is not None
            t = ticket[0]
            _refused(c, "UPDATE customer.support_tickets SET effort = 4 WHERE id = %s", (t,))  # not closed yet
            _refused(c, "UPDATE customer.support_tickets SET category = 'access' WHERE id = %s", (t,))
            _refused(c, "UPDATE customer.support_tickets SET context = '{\"route\": \"/x\"}' WHERE id = %s", (t,))
            c.execute("UPDATE customer.support_tickets SET status = 'closed', closed_at = now(), effort = 4 WHERE id = %s",
                      (t,))
            _refused(c, "UPDATE customer.support_tickets SET effort = 5 WHERE id = %s", (t,))  # given once
            _refused(c, "UPDATE customer.support_tickets SET effort = 9 WHERE id = %s", (plain[0],))
            _refused(c, "UPDATE customer.support_tickets SET status = 'closed', closed_at = now(), effort = 3 "
                        "WHERE id = %s", (old[0],))  # an effort on a privacy request
            _refused(c, "INSERT INTO customer.ticket_messages (ticket_id, author, body, channel) VALUES (%s, 'owner', "
                        "'x', 'sms')", (t,))
            c.execute("INSERT INTO customer.ticket_messages (ticket_id, author, body, channel) VALUES (%s, 'owner', "
                      "'Lo vimos por WhatsApp', 'whatsapp')", (t,))
            _refused(c, "DELETE FROM customer.support_tickets WHERE id = %s", (t,))  # never deleted (0095)
        with pytest.raises(Exception, match="support tickets or messages noted"):
            command.downgrade(_cfg(), "0101")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert c.execute("SELECT count(*) FROM customer.support_tickets WHERE kind = 'support'").fetchone() == (2,), (
                "the support tickets are kept")
            with c.transaction():
                c.execute("SET LOCAL fbi.customer_maintenance = 'on'")
                c.execute("DELETE FROM customer.ticket_messages WHERE ticket_id IN (SELECT id FROM "
                          "customer.support_tickets WHERE kind = 'support')")
                c.execute("DELETE FROM customer.support_tickets WHERE kind = 'support'")
        command.downgrade(_cfg(), "0101")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before
            assert c.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'customer' AND "
                             "table_name IN ('support_tickets', 'ticket_messages') AND "
                             "column_name IN ('category', 'context', 'effort', 'channel')").fetchone() == (0,)
            # the guard of 0095 is back: the status still changes, who and what still do not
            c.execute("UPDATE customer.support_tickets SET status = 'answered' WHERE id = %s", (old[0],))
            _refused(c, "UPDATE customer.support_tickets SET kind = 'privacy_claim' WHERE id = %s", (old[0],))
            assert c.execute("SELECT count(*) FROM pg_trigger WHERE tgname = 'support_tickets_defaults'").fetchone() == (0,)
        command.upgrade(_cfg(), "0102")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT DISTINCT category FROM customer.support_tickets").fetchall() == [("privacy",)]
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
