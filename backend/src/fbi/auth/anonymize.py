"""Deleting an account as anonymisation (plan UX, A7 and section 23), on a reader's deletion request and only with the
owner's confirmation - the account's address typed again in the console.

What goes: the reader's preferences and favourites (A13), their survey answers and «¿Te sirvió?» (B6), what they saved (picks and parlays), their sessions, their second factor and
recovery codes, and every link of theirs that could still work. The account's row stays - its address masked
(``deleted-<id>@deleted.invalid``, which the e-mail queue never sends to), its name replaced, a random password hash
nobody knows, status ``deleted`` - and so does the address typed in the sign-in trail, masked the same way. What
stays linked to the row, as the law asks: the consents (the proof of what was accepted, and when) and the privacy
requests with their thread (the proof that the request was answered) and the support tickets with theirs (A14: the
open ones are closed - nobody is left to answer). Messages still queued for the reader are not sent. Nothing about an anonymised account changes afterwards; no account of the owner's (SUPER_ADMIN) is anonymised.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from fbi.auth import passwords, store, tokens
from fbi.auth.db import write_connection
from fbi.auth.roles import Role
from fbi.auth.service import AuthError, Principal, _lock_streak_of, normalize_email
from fbi.customer import lifecycle, push

log = structlog.get_logger("auth.anonymize")


@dataclass(frozen=True, slots=True)
class Anonymised:
    user: dict[str, Any]
    picks: int
    parlays: int
    sessions: int
    messages_dropped: int
    trail_rows: int
    tickets_closed: int = 0


def masked_address(user_id: int) -> str:
    return f"deleted-{user_id}@deleted.invalid"


def anonymise(actor: Principal, user_id: int, *, confirm: str, ip: str | None) -> Anonymised:
    """One transaction: everything above, or nothing."""
    with write_connection() as conn:
        found = store.user_by_id(conn, user_id)
        if found is None:
            raise AuthError(404, "user_not_found")
        _lock_streak_of(conn, str(found["email"]))  # a sign-in in flight finishes first (as for an unlock)
        target = store.user_by_id(conn, user_id, for_update=True)
        assert target is not None
        if target["status"] == "deleted":
            raise AuthError(409, "account_deleted")
        if user_id == actor.user_id:
            raise AuthError(409, "cannot_delete_self")
        if target["role"] == Role.SUPER_ADMIN:
            raise AuthError(409, "cannot_delete_admin")
        if normalize_email(confirm) != target["email"]:
            raise AuthError(422, "confirmation_mismatch")
        address, masked = str(target["email"]), masked_address(user_id)
        parlays = conn.execute("DELETE FROM picks.user_parlays WHERE user_id = %s", (user_id,)).rowcount
        picks = conn.execute("DELETE FROM picks.user_picks WHERE user_id = %s", (user_id,)).rowcount
        conn.execute("DELETE FROM customer.guide_progress WHERE user_id = %s", (user_id,))  # the guides seen (UX-027)
        conn.execute("DELETE FROM customer.preferences WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM customer.favorites WHERE user_id = %s", (user_id,))
        conn.execute("DELETE FROM customer.feedback WHERE user_id = %s", (user_id,))  # the survey and «¿Te sirvió?» (B6)
        lifecycle.forget(conn, user_id)  # the states of its days (plan UX, B11)
        push.forget(conn, user_id)  # the devices, the bells and the notices (plan UX, B7)
        # Their support tickets still open (plan UX, A14): nobody is left to answer. The thread stays, as a privacy
        # request's does.
        tickets = conn.execute("UPDATE customer.support_tickets SET status = 'closed', closed_at = now() "
                               "WHERE user_id = %s AND kind = 'support' AND status <> 'closed'", (user_id,)).rowcount
        sessions = conn.execute("DELETE FROM auth.sessions WHERE user_id = %s", (user_id,)).rowcount
        store.clear_totp(conn, user_id)  # the second factor's secret and the recovery codes
        tokens.revoke_open(conn, user_id, tuple(tokens.LIFETIME), "account_closed")
        dropped = conn.execute("""
            UPDATE customer.messages_outbox SET status = 'suppressed', last_error = 'the account was deleted',
                   updated_at = now()
             WHERE user_id = %s AND status = 'queued'
        """, (user_id,)).rowcount
        trail = conn.execute("UPDATE auth.audit_events SET email = %s WHERE email = %s", (masked, address)).rowcount
        conn.execute("""
            UPDATE auth.users
               SET email = %s, display_name = %s, password_hash = %s, status = 'deleted', timezone = 'UTC',
                   must_change_password = false, mfa_required = false, failed_logins = 0, locked_until = NULL,
                   updated_at = now()
             WHERE id = %s
        """, (masked, f"deleted-{user_id}", passwords.unusable_hash(), user_id))
        counts = {"picks": picks, "parlays": parlays, "sessions": sessions, "messages_dropped": dropped,
                  "trail_rows": trail, "tickets_closed": tickets}
        # Never the address: the row says who did it, to which account and what went.
        store.record_event(conn, "user.anonymised", actor_user_id=actor.user_id, target_user_id=user_id, ip=ip,
                           detail=counts)
        row = store.user_by_id(conn, user_id)
        assert row is not None
    log.info("auth.anonymised", user_id=user_id, **counts)
    return Anonymised(user=row, **counts)
