"""Migration 0125 (the ground for a reader who registers by themselves and asks for access, tramo 1 of the user's flow,
UX-027): additive, and strict about what it adds.

Deploying must change nothing the system already stores: the accounts keep their data, repeated nicknames are made distinct
(the oldest keeps its own), the accounts that were invited are told from those the owner made, and the older writes keep
working. What it adds is checked in the database itself, not in the code: a self-registered account carries its personal
fields, a nickname is unique ignoring case among the accounts not deleted, a request for access is one open per reader,
cannot be edited once decided (only the payer's name and the note may be blanked) and is never deleted. Going back is
refused while any of it is in use. Run on a scratch database at revision 0124, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0125"
HASH = "$argon2id$x"
SHA = "a" * 64


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _refused(c: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> None:
    with pytest.raises((psycopg.errors.IntegrityError, psycopg.errors.CheckViolation)), c.transaction():
        c.execute(sql, params)


def _user(c: psycopg.Connection[Any], email: str, name: str, **extra: Any) -> int:
    cols = {"email": email, "display_name": name, "password_hash": HASH, **extra}
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    row = c.execute(f"INSERT INTO auth.users ({names}) VALUES ({marks}) RETURNING id", tuple(cols.values())).fetchone()
    assert row
    return int(row[0])


SIGNUP = {"origin": "signup", "first_name": "Ana", "last_name": "Pérez", "phone_e164": "+573001234567"}

REQUEST = ("INSERT INTO customer.payment_requests (user_id, expected_amount, currency, declared_amount, declared_paid_on, "
           "method, reference_last4, reference_hmac, payer_name, note, terms_version, terms_sha256, accepted_at) "
           "VALUES (%s, 150000, 'COP', 150000, '2026-11-07', 'nequi', '1234', %s, 'Ana P.', 'desde mi Nequi', "
           "'2026-11-01draft1', %s, now()) RETURNING id")


def test_0125_is_additive_strict_and_goes_back_only_while_unused(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0124")
        with psycopg.connect(dsn, autocommit=True) as c:
            owner = _user(c, "owner@test.local", "Dueño", role="SUPER_ADMIN")
            first = _user(c, "uno@test.local", "Carlos")
            second = _user(c, "dos@test.local", "  carlos ")  # the same nickname, ignoring case and spaces
            gone = _user(c, "gone@test.local", "Carlos", status="deleted")  # deleted accounts do not count
            c.execute("INSERT INTO auth.account_tokens (user_id, purpose, nonce) VALUES (%s, 'invite', %s)",
                      (first, b"\x00" * 32))
        command.upgrade(_cfg(), "0125")
        with psycopg.connect(dsn, autocommit=True) as c:
            names = dict(c.execute("SELECT id, display_name FROM auth.users").fetchall())
            assert names[first] == "Carlos", "the oldest account keeps its nickname"
            assert names[second] == f"carlos-{second}", "the repeated one is made distinct, not lost"
            assert names[gone] == "Carlos" and names[owner] == "Dueño"
            origins = dict(c.execute("SELECT id, origin FROM auth.users").fetchall())
            assert origins[first] == "invite" and origins[second] == "admin" and origins[owner] == "admin"
            assert c.execute("SELECT count(*) FROM auth.users WHERE email_verified_at IS NOT NULL").fetchone() == (0,)

            # The nickname: unique ignoring case among the accounts that are not deleted.
            _refused(c, "INSERT INTO auth.users (email, display_name, password_hash) VALUES ('x@test.local', 'CARLOS', %s)",
                     (HASH,))
            _user(c, "free@test.local", "Carlos-Free")
            c.execute("UPDATE auth.users SET display_name = 'Libre' WHERE id = %s", (first,))
            _user(c, "again@test.local", "carlos")  # the name was released

            # A self-registered account carries its data; a pending one is always one.
            _refused(c, "INSERT INTO auth.users (email, display_name, password_hash, origin) "
                        "VALUES ('s1@test.local', 'S1', %s, 'signup')", (HASH,))
            _refused(c, "INSERT INTO auth.users (email, display_name, password_hash, status) "
                        "VALUES ('s2@test.local', 'S2', %s, 'pending')", (HASH,))
            _refused(c, "INSERT INTO auth.users (email, display_name, password_hash, origin, first_name, last_name, "
                        "phone_e164) VALUES ('s3@test.local', 'S3', %s, 'signup', 'Ana', 'P', '3001234567')", (HASH,))
            _refused(c, "INSERT INTO auth.users (email, display_name, password_hash, origin) "
                        "VALUES ('s4@test.local', 'S4', %s, 'elsewhere')", (HASH,))
            reader = _user(c, "ana@test.local", "AnaP", status="pending", **SIGNUP)
            c.execute("UPDATE auth.users SET status = 'active', email_verified_at = now() WHERE id = %s", (reader,))
            # An anonymised self-registered account has no personal fields and is still valid.
            c.execute("UPDATE auth.users SET status = 'deleted', first_name = NULL, last_name = NULL, phone_e164 = NULL "
                      "WHERE id = %s", (reader,))
            c.execute("UPDATE auth.users SET status = 'pending', first_name = 'Ana', last_name = 'P', "
                      "phone_e164 = '+573001234567' WHERE id = %s", (reader,))

            # The token and the consent source it learns.
            c.execute("INSERT INTO auth.account_tokens (user_id, purpose, nonce) VALUES (%s, 'verify', %s)",
                      (reader, b"\x01" * 32))
            c.execute("INSERT INTO customer.consents (user_id, kind, granted, document, version, sha256, locale, "
                      "statement, source) VALUES (%s, 'terms', true, 'terms', '2026-11-01draft1', %s, 'es', 'x', 'signup')",
                      (reader, SHA))

            # The request: one open per reader, bounded, never edited once decided, never deleted.
            req = c.execute(REQUEST, (reader, SHA, SHA)).fetchone()
            assert req
            _refused(c, REQUEST, (reader, SHA, SHA))  # a second open one
            _refused(c, "UPDATE customer.payment_requests SET declared_amount = 1 WHERE id = %s", (req[0],))
            _refused(c, "UPDATE customer.payment_requests SET payer_name = 'Otra' WHERE id = %s", (req[0],))
            _refused(c, "UPDATE customer.payment_requests SET status = 'rejected', decided_at = now() WHERE id = %s",
                     (req[0],))  # needs who and why
            _refused(c, "UPDATE customer.payment_requests SET status = 'approved', decided_at = now(), decided_by = %s "
                        "WHERE id = %s", (owner, req[0]))  # needs its payment
            _refused(c, "DELETE FROM customer.payment_requests WHERE id = %s", (req[0],))
            c.execute("UPDATE customer.payment_requests SET status = 'rejected', decided_at = now(), decided_by = %s, "
                      "decision_code = 'not_received', decision_note = 'no llegó' WHERE id = %s", (owner, req[0]))
            _refused(c, "UPDATE customer.payment_requests SET status = 'submitted', decided_at = NULL WHERE id = %s",
                     (req[0],))
            _refused(c, "UPDATE customer.payment_requests SET decision_note = 'otra cosa' WHERE id = %s", (req[0],))
            c.execute("UPDATE customer.payment_requests SET payer_name = NULL, note = NULL WHERE id = %s", (req[0],))
            second_try = c.execute(REQUEST, (reader, SHA, SHA)).fetchone()  # the first is decided, so another may open
            assert second_try
            c.execute("UPDATE customer.payment_requests SET status = 'cancelled', decided_at = now() WHERE id = %s",
                      (second_try[0],))
            # Bounds: a reference of its last four characters, an amount above zero, a closed method.
            _refused(c, REQUEST.replace("'1234'", "'12345'"), (reader, SHA, SHA))
            _refused(c, REQUEST.replace("150000, 'COP', 150000", "0, 'COP', 150000"), (reader, SHA, SHA))
            _refused(c, REQUEST.replace("'nequi'", "'bitcoin'"), (reader, SHA, SHA))
            _refused(c, REQUEST.replace("'1234', %s", "'1234', NULL"), (reader, SHA))  # last four without its HMAC

            # The closed lists that learned the flow.
            c.execute("INSERT INTO customer.membership_events (user_id, kind) VALUES (%s, 'payment_requested')", (reader,))
            c.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body) VALUES "
                      "('payment_request_new', 'pr-1', 'Solicitud de pago', 'una nueva')")
            c.execute("INSERT INTO customer.lifecycle_snapshots (user_id, day, state, reasons) VALUES "
                      "(%s, '2026-11-07', 'payment_pending', ARRAY['account_invited'])", (reader,))

        with pytest.raises(Exception, match="the code goes back"):
            command.downgrade(_cfg(), "0124")

        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("SET fbi.customer_maintenance = 'on'")
            for table in ("customer.lifecycle_snapshots", "customer.membership_events", "customer.consents",
                          "customer.payment_requests"):
                c.execute(f"DELETE FROM {table}")
            c.execute("DELETE FROM audit.notifications WHERE kind = 'payment_request_new'")
            c.execute("DELETE FROM auth.account_tokens WHERE purpose = 'verify'")
            c.execute("DELETE FROM auth.users WHERE origin = 'signup'")
        command.downgrade(_cfg(), "0124")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert not c.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = 'auth' "
                                 "AND table_name = 'users' AND column_name IN ('origin', 'phone_e164')").fetchall()
            assert c.execute("SELECT to_regclass('customer.payment_requests')").fetchone() == (None,)
            _refused(c, "INSERT INTO auth.users (email, display_name, password_hash, status) "
                        "VALUES ('p@test.local', 'P', %s, 'pending')", (HASH,))
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
