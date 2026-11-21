"""A reader's secret calendar link (Plan Maestro PM, PM-14-06, OP-43; BE-084): ``customer.calendar_feeds`` (migration 0171).

THE SECRET. 32 random bytes from the operating system (``secrets.token_urlsafe``: 43 URL-safe characters, 256 bits), shown to the reader
ONCE when the link is made and never stored: the row keeps its SHA-256 (``token_id``, the same as ``fbi.auth.tokens``' one-use links). A
secret of that size needs no salt or slow hash - nobody can guess or enumerate it - and the hash makes a stolen copy of the table useless.

THE RULES.
* At most one live link per reader (a partial unique index): making a new one revokes the previous (``replaced``) in the same transaction.
* The reader revokes it at any time (``reader``); the owner may, from the container (``owner``: no console route); anonymising the account deletes every link (A7, ``forget``).
* A link is READ-ONLY: it answers the fixtures of the teams the reader follows and nothing else - no account data, no price, probability or
  pick. It cannot change anything, sign in or reach any other route.
* ``last_read_at`` is written at most once an hour (``TOUCH_EVERY``): enough for the reader to see whether a leaked link is in use, never a
  log of each read.

Only the API writes here (``grants.sql``: INSERT, UPDATE, DELETE); the worker of PrediGol Intelligence never reads ``customer``.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import psycopg

from fbi.customer.db import CustomerError, write_connection

TOKEN_BYTES: Final = 32
TOKEN_PATTERN: Final = re.compile(r"^[A-Za-z0-9_-]{43}$")
"""What ``secrets.token_urlsafe(32)`` gives: anything else is refused before the database is asked."""
TOUCH_EVERY: Final = timedelta(hours=1)

Why = Literal["reader", "replaced", "owner", "account"]


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_id(token: str) -> str:
    """The SHA-256 of the secret, in 64 hex digits: what the row keeps."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def looks_like_token(value: str | None) -> bool:
    return bool(value) and TOKEN_PATTERN.fullmatch(value or "") is not None


@dataclass(frozen=True, slots=True)
class Feed:
    id: int
    user_id: int
    created_at: datetime
    last_read_at: datetime | None


@dataclass(frozen=True, slots=True)
class Made:
    """A link just made: its secret, shown once."""

    feed: Feed
    token: str


LIVE_SQL: Final = ("SELECT id, user_id, created_at, last_read_at FROM customer.calendar_feeds "
                   "WHERE user_id = %(u)s AND revoked_at IS NULL")
BY_HASH_SQL: Final = ("SELECT id, user_id, created_at, last_read_at FROM customer.calendar_feeds "
                      "WHERE link_sha256 = %(h)s AND revoked_at IS NULL")
REVOKE_SQL: Final = ("UPDATE customer.calendar_feeds SET revoked_at = %(at)s, revoked_why = %(why)s "
                     "WHERE user_id = %(u)s AND revoked_at IS NULL")
INSERT_SQL: Final = ("INSERT INTO customer.calendar_feeds (user_id, link_sha256, created_at) VALUES (%(u)s, %(h)s, %(at)s) "
                     "RETURNING id, user_id, created_at, last_read_at")
TOUCH_SQL: Final = ("UPDATE customer.calendar_feeds SET last_read_at = %(at)s "
                    "WHERE id = %(id)s AND revoked_at IS NULL AND (last_read_at IS NULL OR last_read_at < %(before)s)")


def _feed(row: Any) -> Feed:
    return Feed(int(row[0]), int(row[1]), row[2], row[3])


def live(conn: psycopg.Connection[Any], user_id: int) -> Feed | None:
    """The reader's live link, if any (read through the API's own connection)."""
    row = conn.execute(LIVE_SQL, {"u": user_id}).fetchone()
    return _feed(row) if row else None


def resolve(conn: psycopg.Connection[Any], token: str | None) -> Feed | None:
    """The live link a secret opens, or None (malformed, unknown or revoked: the same answer)."""
    if not looks_like_token(token):
        return None
    row = conn.execute(BY_HASH_SQL, {"h": token_id(str(token))}).fetchone()
    return _feed(row) if row else None


def make(user_id: int, *, at: datetime) -> Made:
    """A new link for the reader: the previous one (if any) is revoked as ``replaced`` in the same transaction."""
    token = new_token()
    try:
        with write_connection() as conn:
            conn.execute(REVOKE_SQL, {"u": user_id, "at": at, "why": "replaced"})
            row = conn.execute(INSERT_SQL, {"u": user_id, "h": token_id(token), "at": at}).fetchone()
    except psycopg.errors.UniqueViolation as exc:  # two requests at once: one link stands, the other is told to retry
        raise CustomerError(409, "calendar_feed_busy", "another link was being made at the same time; try again") from exc
    assert row is not None
    return Made(_feed(row), token)


def revoke(user_id: int, *, at: datetime, why: Why = "reader") -> bool:
    """The reader's live link revoked; whether there was one."""
    with write_connection() as conn:
        return conn.execute(REVOKE_SQL, {"u": user_id, "at": at, "why": why}).rowcount > 0


def touch(feed: Feed, *, at: datetime) -> None:
    """Notes that a calendar read the link - at most once per ``TOUCH_EVERY``; never fails the reading."""
    if feed.last_read_at is not None and at - feed.last_read_at < TOUCH_EVERY:
        return
    with write_connection() as conn:
        conn.execute(TOUCH_SQL, {"id": feed.id, "at": at, "before": at - TOUCH_EVERY})


def forget(conn: psycopg.Connection[Any], user_id: int) -> None:
    """The account anonymised (A7): every link of it goes."""
    conn.execute("DELETE FROM customer.calendar_feeds WHERE user_id = %s", (user_id,))


__all__ = ["TOKEN_PATTERN", "TOUCH_EVERY", "Feed", "Made", "forget", "live", "looks_like_token", "make", "new_token", "resolve", "revoke",
           "token_id", "touch"]
