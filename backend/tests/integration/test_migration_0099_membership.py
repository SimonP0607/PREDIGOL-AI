"""Migration 0099 (membership, plan UX A8): three new tables, nothing else.

Deploying must change nothing the system already stores: 0099 adds ``customer.payments``,
``customer.membership_periods`` and ``customer.membership_events``; every other table keeps its columns and its rows.
The tables refuse what they must never hold - an account's or a card's number in a reference, a paid period without
its payment, a courtesy without its reason, a second trial, the same notice twice - and every row stays as it was
written (append-only). Going back is refused while any of them holds a row. Run on a scratch database at revision
0098, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0099"
HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaGhhc2hoYXNoaGFzaA"  # gitleaks:allow - not a password's
NEW = ("payments", "membership_periods", "membership_events")


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
                     "'intel', 'picks', 'raw', 'audit', 'customer') AND NOT (table_schema = 'customer' "
                     "AND table_name = ANY(%s)) ORDER BY 1, 2, ordinal_position", (list(NEW),)).fetchall()


def test_0099_adds_the_membership_tables_that_refuse_what_they_must_never_hold(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0098")
        with psycopg.connect(dsn) as c:
            row = c.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                            "('m@predigol.test', 'm', %s) RETURNING id", (HASH,)).fetchone()
            assert row is not None
            uid = row[0]
            c.commit()
            before = _shape(c)
        command.upgrade(_cfg(), "0099")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before, "not a column more or less in any table that was there"
            pay = ("INSERT INTO customer.payments (user_id, amount, currency, method, reference, idempotency_key) "
                   "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id")
            refused: tuple[tuple[str, tuple[Any, ...]], ...] = (
                (pay, (uid, 50000, "COP", "nequi", "tarjeta 4111 1111 1111 1111", "key-00000001")),
                (pay, (uid, 50000, "COP", "nequi", "cuenta 123-456-7890", "key-00000002")),
                (pay, (uid, 0, "COP", "nequi", "", "key-00000003")),
                (pay, (uid, 50000, "cop", "nequi", "", "key-00000004")),
                (pay, (uid, 50000, "COP", "bitcoin", "", "key-00000005")),
                (pay, (uid, 50000, "COP", "nequi", "", "short")),
                ("INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at) "
                 "VALUES (%s, 'paid', now(), now() + interval '30 days')", (uid,)),
                ("INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at) "
                 "VALUES (%s, 'courtesy', now(), now() + interval '30 days')", (uid,)),
                ("INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at) "
                 "VALUES (%s, 'trial', now(), now() - interval '1 day')", (uid,)),
                ("INSERT INTO customer.membership_events (user_id, kind) VALUES (%s, 'suspended')", (uid,)),
                ("INSERT INTO customer.membership_events (user_id, kind) VALUES (%s, 'notice')", (uid,)),
            )
            for sql, params in refused:
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute(sql, params)
                c.rollback()
            payment = c.execute(pay, (uid, 50000, "COP", "nequi", "Nequi, últimos 4: 1234", "key-00000009")
                                ).fetchone()
            assert payment is not None
            trial = c.execute("INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at) "
                              "VALUES (%s, 'trial', now(), now() + interval '14 days') RETURNING id", (uid,)).fetchone()
            assert trial is not None
            c.execute("INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at, payment_id) "
                      "VALUES (%s, 'paid', now() + interval '14 days', now() + interval '44 days', %s)",
                      (uid, payment[0]))
            c.execute("INSERT INTO customer.membership_events (user_id, kind, period_id, milestone) "
                      "VALUES (%s, 'notice', %s, 'before')", (uid, trial[0]))
            c.commit()
            duplicates: tuple[tuple[str, tuple[Any, ...]], ...] = (
                ("INSERT INTO customer.membership_periods (user_id, kind, starts_at, ends_at) "
                 "VALUES (%s, 'trial', now(), now() + interval '7 days')", (uid,)),
                ("INSERT INTO customer.membership_events (user_id, kind, period_id, milestone) "
                 "VALUES (%s, 'notice', %s, 'before')", (uid, trial[0])),
                (pay, (uid, 10, "COP", "cash", "", "key-00000009")),
            )
            for sql, params in duplicates:
                with pytest.raises(psycopg.errors.UniqueViolation):
                    c.execute(sql, params)
                c.rollback()
            for table in NEW:
                for sql in (f"UPDATE customer.{table} SET user_id = user_id", f"DELETE FROM customer.{table}"):
                    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
                        c.execute(sql)
                    c.rollback()
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                c.execute("DELETE FROM auth.users WHERE id = %s", (uid,))
            c.rollback()
        with pytest.raises(Exception, match="memberships or payments"):
            command.downgrade(_cfg(), "0098")
        with psycopg.connect(dsn) as c:
            c.execute("SET LOCAL fbi.customer_maintenance = 'on'")
            for table in ("membership_events", "membership_periods", "payments"):
                c.execute(f"DELETE FROM customer.{table}")
            c.commit()
        command.downgrade(_cfg(), "0098")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before
            for table in NEW:
                assert c.execute("SELECT to_regclass(%s)", (f"customer.{table}",)).fetchone() == (None,)
    finally:
        if previous is not None:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
