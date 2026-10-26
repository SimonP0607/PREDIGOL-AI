"""The reader's account centre in one read (plan UX, B1; section 21 of the plan).

The profile has eight blocks - Cuenta, Fútbol, Idioma y zona, Notificaciones, Privacidad, Seguridad, Membresía and Ayuda.
Folded, each says one line; this module gathers those lines from what phases A4 to A14 already keep, in one read of the
reader's own rows: nothing new is stored and nothing is computed differently from the block's own page part (the counts
below are the same filters those parts apply). Only the reader's account, never another's; never a word of the
intelligence.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from fbi.auth import service as auth_service
from fbi.auth.service import Principal
from fbi.customer import consents, favorites, membership, privacy, support
from fbi.messaging import preferences as mail_preferences
from fbi.messaging.outbox import sending_enabled
from fbi.messaging.templates import CATEGORIES

ACCOUNT_SQL = """
SELECT display_name, email, created_at, last_login_at, password_changed_at, language, timezone
  FROM auth.users WHERE id = %s
"""


@dataclass(frozen=True, slots=True)
class HelpCounts:
    waiting: int
    """Messages waiting for PrediGol's answer (status open)."""
    answered: int
    """Answered and not yet closed by the reader."""


def help_counts(statuses: Iterable[str]) -> HelpCounts:
    """The reader's support messages by what they wait for: the same statuses Ayuda's «Tus mensajes» shows."""
    seen = list(statuses)
    return HelpCounts(waiting=seen.count("open"), answered=seen.count("answered"))


def open_requests(requests: Iterable[tuple[str, date | None]]) -> tuple[int, date | None]:
    """How many privacy requests are still open and the nearest of their legal deadlines (status, deadline pairs)."""
    deadlines = [deadline for status, deadline in requests if status == "open"]
    dated = [d for d in deadlines if d is not None]
    return len(deadlines), (min(dated) if dated else None)


def latest_decision(times: Iterable[datetime]) -> datetime | None:
    """The reader's latest consent decision, or None without one."""
    return max(times, default=None)


def summary(conn: psycopg.Connection[Any], principal: Principal, *, at: datetime | None = None) -> dict[str, Any]:
    """What the profile's eight blocks say while folded, for the signed-in reader (GET /me/account)."""
    moment = at or datetime.now(UTC)
    uid = principal.user_id
    row = conn.execute(ACCOUNT_SQL, (uid,)).fetchone()
    # the session's own fields when its row cannot be read (a test's session without an account): never another's
    display_name, email, created_at, last_login_at, password_changed_at, language, timezone = row or (
        principal.display_name, principal.email, None, None, None, principal.language, principal.timezone)

    chosen = favorites.chosen(conn, uid)
    shown = chosen if chosen is not None else favorites.suggested(conn)
    prefs = mail_preferences.read(conn, uid)
    exempt = consents.exempt(principal.email, super_admin=principal.is_super_admin)
    due = consents.due(conn, uid) if consents.gate_enabled() and not exempt else []
    count, deadline = open_requests((r.status, r.deadline) for r in privacy.requests_of(conn, uid))
    tickets = help_counts(t.status for t in support.tickets_of(conn, uid))
    found = membership.summary(membership.of(conn, uid, email=principal.email,
                                             super_admin=principal.is_super_admin), moment)
    return {
        "account": {"display_name": display_name, "email": email, "created_at": created_at,
                    "admin": principal.is_super_admin},
        "region": {"language": language, "timezone": timezone},
        "football": {"leagues": len(shown.leagues), "teams": len(shown.teams), "suggested": chosen is None},
        "notifications": {"email_on": sum(1 for c in CATEGORIES if prefs.email_on(c)),
                          "email_total": len(CATEGORIES), "email_status": prefs.email_status,
                          "sending": sending_enabled()},
        "privacy": {"consents_due": list(due),
                    "consents_at": latest_decision(c.at for c in consents.history(conn, uid, limit=1)),
                    "open_requests": count, "next_deadline": deadline},
        "security": {"mfa_enabled": principal.mfa_enabled,
                     "sessions": len(auth_service.my_sessions(conn, principal)),
                     "last_sign_in_at": last_login_at, "password_changed_at": password_changed_at},
        "membership": found,
        "help": {"waiting": tickets.waiting, "answered": tickets.answered,
                 "whatsapp": membership.whatsapp() is not None, "support": support.support_on()},
    }
