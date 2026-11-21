"""Migration 0171 (PM-14-06) in a real database: a reader's calendar link keeps only the SHA-256 of its secret, one live link per reader,
a revoked link says why and when, and a link outlives nothing it refers to (an account is anonymised, never deleted)."""

from __future__ import annotations

import hashlib
from typing import Any

import psycopg
import pytest

pytestmark = pytest.mark.integration


def _user(db: psycopg.Connection[Any], n: int) -> int:
    row = db.execute("INSERT INTO auth.users (email, display_name, password_hash, role) VALUES (%s, %s, '$argon2id$x', 'USER') "
                     "RETURNING id", (f"cal{n}@example.test", f"Cal {n}")).fetchone()
    assert row is not None
    return int(row[0])


def _hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def test_one_live_link_per_reader_and_only_a_hash(db: psycopg.Connection[Any]) -> None:
    uid = _user(db, 1)
    db.execute("INSERT INTO customer.calendar_feeds (user_id, token_hash) VALUES (%s, %s)", (uid, _hash("a")))
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction():
        db.execute("INSERT INTO customer.calendar_feeds (user_id, token_hash) VALUES (%s, %s)", (uid, _hash("b")))
    db.execute("UPDATE customer.calendar_feeds SET revoked_at = now(), revoked_why = 'replaced' WHERE user_id = %s", (uid,))
    db.execute("INSERT INTO customer.calendar_feeds (user_id, token_hash) VALUES (%s, %s)", (uid, _hash("b")))
    assert db.execute("SELECT count(*) FROM customer.calendar_feeds WHERE user_id = %s AND revoked_at IS NULL",
                      (uid,)).fetchone() == (1,)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("INSERT INTO customer.calendar_feeds (user_id, token_hash) VALUES (%s, 'not-a-hash')", (_user(db, 2),))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE customer.calendar_feeds SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL", (uid,))
    with pytest.raises(psycopg.errors.UniqueViolation), db.transaction():
        db.execute("INSERT INTO customer.calendar_feeds (user_id, token_hash) VALUES (%s, %s)", (_user(db, 3), _hash("b")))


def test_an_account_with_a_link_is_not_deleted(db: psycopg.Connection[Any]) -> None:
    uid = _user(db, 4)
    db.execute("INSERT INTO customer.calendar_feeds (user_id, token_hash) VALUES (%s, %s)", (uid, _hash("c")))
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction():
        db.execute("DELETE FROM auth.users WHERE id = %s", (uid,))
