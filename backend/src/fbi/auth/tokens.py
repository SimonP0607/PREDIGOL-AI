"""Tokens.

* A session's: the browser holds the token; the database holds only its SHA-256.
* An account's one-use links (plan UX, A7): an invitation, a password reset, an unlock. The database holds a random
  nonce and - once the e-mail with the link leaves - the link's SHA-256, never the link: the messenger derives it
  (``crypto.account_token``) in the transaction that sends the e-mail, so a link exists only in that e-mail, the same
  one at every retry. A link works once, until it expires (``LIFETIME``, counted from when it left), and only while no
  newer link of its kind replaced it and the account is still in the state the link is for. Whatever the reason a link
  does not work, the answer is the same.

Everything here runs in the caller's transaction and decides nothing about who may ask for a link: that is
``fbi.auth.invitations`` and ``fbi.auth.recovery``.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from fbi.auth import crypto

TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def looks_like_token(value: str | None) -> bool:
    """A cookie that cannot be one of ours is rejected before the database is asked."""
    if not value or not (32 <= len(value) <= 64):
        return False
    return all(c.isalnum() or c in "-_" for c in value)


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ── an account's one-use links ────────────────────────────────────────────────────────

Purpose = Literal["invite", "reset", "unlock"]
LIFETIME: dict[str, timedelta] = {"invite": timedelta(days=7), "reset": timedelta(minutes=30),
                                  "unlock": timedelta(hours=1)}
"""How long a link works, counted from when its e-mail left: an invitation 7 days and an unlock 1 hour (plan UX, A7),
a password reset 30 minutes (R25 of the security plan, stricter than the UX plan's hour: the phase that comes first
meets both)."""
STATUS_FOR: dict[str, str] = {"invite": "invited", "reset": "active", "unlock": "active"}
"""The state the account must be in for a link of each kind to leave and to work."""
PER_HOUR = 3
"""Links of one kind an account may be sent in an hour (plan UX, section 19: «un límite de 3 por hora»)."""
KEEP_DAYS = 30
"""A row is kept this long after it was used, expired or replaced (plan UX, section 17)."""
NONCE_BYTES = 32
"""The random part of a link (256 bits, R25 of the security plan); the server's key makes it a link."""
SWITCH = "FBI_SELF_SERVICE"

PurgeMode = Literal["dry", "on", "off"]


def self_service_enabled() -> bool:
    """FBI_SELF_SERVICE, born off (plan UX, A7): off, the owner creates accounts with a temporary password as before,
    no link is issued or accepted (those already sent simply expire) and no account e-mail is queued."""
    return os.environ.get(SWITCH, "0").strip().lower() in ("1", "true", "yes", "on")


def purge_mode() -> PurgeMode:
    """FBI_TOKENS_PURGE, born ``dry``: the messenger counts the rows past their 30 days and deletes nothing until the
    owner says ``on``."""
    raw = os.environ.get("FBI_TOKENS_PURGE", "dry").strip().lower()
    if raw in ("on", "1", "true", "yes"):
        return "on"
    return "off" if raw in ("off", "0", "false", "no") else "dry"


@dataclass(frozen=True, slots=True)
class Armed:
    link: str
    expires_at: datetime


def _lock_account(conn: psycopg.Connection[Any], user_id: int) -> None:
    """One issue of links at a time per account, until the transaction ends: two requests in two processes would
    each count the last hour before the other's row is written."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('account-tokens:' || %s::text, 7041))", (user_id,))


def sent_last_hour(conn: psycopg.Connection[Any], user_id: int, purpose: str) -> int:
    row = conn.execute("SELECT count(*) FROM auth.account_tokens WHERE user_id = %s AND purpose = %s "
                       "AND created_at > now() - interval '1 hour'", (user_id, purpose)).fetchone()
    return int(row[0]) if row else 0


def issue(conn: psycopg.Connection[Any], user_id: int, purpose: Purpose) -> int | None:
    """A new link of ``purpose`` for an account: its row - a nonce and no hash yet: the link is made when its e-mail
    leaves - or None when the account was sent PER_HOUR links of this kind in the last hour. The earlier links of
    the same kind stop working (replaced)."""
    if purpose not in LIFETIME:
        raise ValueError(f"no link of kind {purpose!r}")
    _lock_account(conn, user_id)
    if sent_last_hour(conn, user_id, purpose) >= PER_HOUR:
        return None
    revoke_open(conn, user_id, (purpose,), "superseded")
    row = conn.execute("INSERT INTO auth.account_tokens (user_id, purpose, nonce) VALUES (%s, %s, %s) RETURNING id",
                       (user_id, purpose, secrets.token_bytes(NONCE_BYTES))).fetchone()
    assert row is not None
    return int(row[0])


def arm(conn: psycopg.Connection[Any], grant: int, *, user_id: int, purpose: str, at: datetime) -> Armed | None:
    """The link of the token ``grant`` while its e-mail leaves (the messenger, in the transaction of the dispatch):
    derived under the server's key, its SHA-256 stored and its expiry set the first time - from ``at``. A retry of the
    same e-mail gets the same link and the same expiry. None when the link must not leave: used, replaced, past its
    expiry, another account's or another kind's, or the account no longer in the state the link is for.
    crypto.KeyUnavailableError without the key."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT t.id, t.user_id, t.purpose, t.nonce, t.sent_at, t.expires_at, t.used_at, t.revoked_at, u.status
              FROM auth.account_tokens t JOIN auth.users u ON u.id = t.user_id
             WHERE t.id = %s
               FOR UPDATE OF t
        """, (grant,))
        row = cur.fetchone()
    if (row is None or int(row["user_id"]) != user_id or row["purpose"] != purpose or row["used_at"] is not None
            or row["revoked_at"] is not None or row["status"] != STATUS_FOR.get(purpose)):
        return None
    if row["expires_at"] is not None and row["expires_at"] <= at:
        return None
    link = crypto.account_token(int(row["id"]), bytes(row["nonce"]))
    if row["sent_at"] is not None:
        return Armed(link, row["expires_at"])
    expires = at + LIFETIME[purpose]
    conn.execute("UPDATE auth.account_tokens SET token_hash = %s, sent_at = %s, expires_at = %s WHERE id = %s",
                 (token_id(link), at, expires, grant))
    return Armed(link, expires)


LINK_COLUMNS = ("t.id AS token_id, t.purpose, t.sent_at, t.expires_at, t.used_at, t.revoked_at, "
                "COALESCE(t.expires_at > now(), false) AS live, u.id AS user_id, u.email, u.display_name, u.status, "
                "u.language, u.timezone, u.role")


def _by_link(conn: psycopg.Connection[Any], link: str | None) -> dict[str, Any] | None:
    if not looks_like_token(link):
        return None
    assert link is not None
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {LINK_COLUMNS} FROM auth.account_tokens t JOIN auth.users u ON u.id = t.user_id "
                    "WHERE t.token_hash = %s FOR UPDATE OF t", (token_id(link),))
        row = cur.fetchone()
    return dict(row) if row is not None else None


def find(conn: psycopg.Connection[Any], link: str | None, purpose: Purpose) -> dict[str, Any] | None:
    """The token of a link that works, with its account, locked until the transaction ends; None otherwise - unknown,
    used, expired, replaced, another kind, or the account no longer in the state the link is for: the same None."""
    row = _by_link(conn, link)
    if (row is None or row["purpose"] != purpose or row["used_at"] is not None or row["revoked_at"] is not None
            or not row["live"] or row["status"] != STATUS_FOR[purpose]):
        return None
    return row


def find_spent_invitation(conn: psycopg.Connection[Any], link: str | None) -> dict[str, Any] | None:
    """The token of an invitation link that no longer works, while its account is still invited: who to send a new
    one to when the reader asks from the page of an expired or replaced link (plan UX, section 19). None for
    anything else."""
    row = _by_link(conn, link)
    if row is None or row["purpose"] != "invite" or row["status"] != "invited" or row["used_at"] is not None:
        return None
    return row


def use(conn: psycopg.Connection[Any], token: int) -> None:
    """The link has done its work: it never works again."""
    cur = conn.execute("UPDATE auth.account_tokens SET used_at = now() WHERE id = %s AND used_at IS NULL "
                       "AND revoked_at IS NULL", (token,))
    if cur.rowcount != 1:
        raise RuntimeError("a link was used twice in one transaction")


def revoke(conn: psycopg.Connection[Any], token: int, reason: str) -> None:
    """One link stops working (a reset link that took too many wrong codes)."""
    conn.execute("UPDATE auth.account_tokens SET revoked_at = now(), revoked_reason = %s "
                 "WHERE id = %s AND used_at IS NULL AND revoked_at IS NULL", (reason, token))


def revoke_open(conn: psycopg.Connection[Any], user_id: int, purposes: tuple[str, ...], reason: str) -> int:
    """Every link of these kinds an account has that could still work stops working."""
    cur = conn.execute("UPDATE auth.account_tokens SET revoked_at = now(), revoked_reason = %s "
                       "WHERE user_id = %s AND purpose = ANY(%s) AND used_at IS NULL AND revoked_at IS NULL",
                       (reason, user_id, list(purposes)))
    return cur.rowcount


PURGE_WHERE = "COALESCE(used_at, revoked_at, expires_at, created_at) < %s"
"""Used, replaced, expired - or never sent - more than KEEP_DAYS ago."""


def purge(conn: psycopg.Connection[Any], *, at: datetime, mode: PurgeMode | None = None) -> tuple[PurgeMode, int]:
    """The rows past their 30 days: counted (``dry``, the default) or deleted (``on``). The caller commits."""
    current = purge_mode() if mode is None else mode
    if current == "off":
        return current, 0
    before = at - timedelta(days=KEEP_DAYS)
    if current == "dry":
        row = conn.execute(f"SELECT count(*) FROM auth.account_tokens WHERE {PURGE_WHERE}", (before,)).fetchone()
        return current, int(row[0]) if row else 0
    return current, max(conn.execute(f"DELETE FROM auth.account_tokens WHERE {PURGE_WHERE}", (before,)).rowcount, 0)
