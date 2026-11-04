"""What a reader chooses to receive (plan UX, A5 and F12): e-mail by category - push joins in B7 - and whether their
address can receive it.

The account, its security, the reader's own privacy requests and a material change of the legal texts are always
sent (``templates.MANDATORY``); membership reminders and answers to support questions can be switched off. A hard
bounce or a complaint (the provider's webhook) shows here, so the reader knows why nothing arrives.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from fbi.customer.db import CustomerError, write_connection
from fbi.messaging.templates import CATEGORIES, MANDATORY, OPTIONAL, Category


@dataclass(frozen=True, slots=True)
class Preferences:
    email_off: frozenset[str]
    email_status: str
    email_status_at: datetime | None

    def email_on(self, category: Category) -> bool:
        return category in MANDATORY or category not in self.email_off


DEFAULTS = Preferences(email_off=frozenset(), email_status="ok", email_status_at=None)


def read(conn: psycopg.Connection[Any], user_id: int) -> Preferences:
    row = conn.execute("SELECT email_off, email_status, email_status_at FROM customer.preferences WHERE user_id = %s",
                       (user_id,)).fetchone()
    if row is None:
        return DEFAULTS
    return Preferences(email_off=frozenset(row[0] or ()), email_status=str(row[1]), email_status_at=row[2])


def update(user_id: int, *, email: Mapping[str, bool]) -> Preferences:
    """Switch e-mail categories on or off. A mandatory category cannot be switched off (422 mandatory_category)."""
    unknown = sorted(set(email) - set(CATEGORIES))
    if unknown:
        raise CustomerError(422, "unknown_category", f"no category {unknown[0]!r}")
    refused = sorted(c for c, on in email.items() if c in MANDATORY and not on)
    if refused:
        raise CustomerError(422, "mandatory_category", f"{refused[0]} messages are always sent")
    with write_connection() as conn:
        current = read(conn, user_id)
        off = set(current.email_off)
        for category, on in email.items():
            if category in OPTIONAL:
                (off.discard if on else off.add)(category)
        conn.execute("""
            INSERT INTO customer.preferences (user_id, email_off) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET email_off = EXCLUDED.email_off, updated_at = now()
        """, (user_id, sorted(off)))
        return read(conn, user_id)
