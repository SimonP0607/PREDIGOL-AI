"""Leaving the weekly summary in one click (plan UX, B8; section 33; RFC 8058).

Every commercial e-mail carries a link of its own, made when it leaves (never stored): the account, the day it left and
an HMAC of both under a subkey of FBI_AUTH_SECRET_KEY (``fbi.auth.crypto.unsubscribe_mac``). The mail client's one-click
button (``List-Unsubscribe-Post: List-Unsubscribe=One-Click``) POSTs it to ``/api/v1/email/unsubscribe?t=...`` (RFC 8058
leaves the address as the only place for it); the link in the body opens a page of PrediGol (``/unsubscribe#t=...``, the
fragment never reaches a server) that asks once and POSTs it in the body to ``/api/v1/email/unsubscribe/link`` - a link
scanner that only follows links leaves nobody.

Leaving withdraws the consent ``marketing_email`` at once: a new row of ``customer.consents`` (source ``email``) with the
version, the sha256 and the sentence of the text, as every decision. It works whatever the switches say (a reader can
always leave), for a year after the e-mail left; a second click changes nothing. The link opens nothing else: no
session, no page of the account.
"""

from __future__ import annotations

import hmac
import re
from datetime import datetime, timedelta

from fbi.auth import crypto
from fbi.customer import consents, legal

VALID_FOR = timedelta(days=366)
PURPOSE = "marketing_email"
TOKEN = re.compile(r"^([1-9][0-9]{0,17})x([0-9]{1,6})x([A-Za-z0-9_-]{22})$")
"""The account, the day and the signature, joined by «x»: the whole link is URL-safe base64 characters, as the web reads a
link's token from the address's fragment (web/src/lib/auth/linkToken.ts), and the two numbers come first."""


def _day(at: datetime) -> int:
    return int(at.timestamp()) // 86_400


def make(user_id: int, at: datetime) -> str:
    """The link's token for this account, made when the e-mail leaves. KeyUnavailableError without the server's key."""
    day = _day(at)
    return f"{user_id}x{day}x{crypto.unsubscribe_mac(f'{PURPOSE}:{user_id}:{day}')}"


def read(token: str, at: datetime) -> int | None:
    """The account a token names, or None: malformed, tampered, older than a year, from the future, or the server's key
    missing (nothing can be checked then)."""
    m = TOKEN.match(token or "")
    if m is None:
        return None
    user_id, day = int(m.group(1)), int(m.group(2))
    today = _day(at)
    if day > today + 1 or day < _day(at - VALID_FOR):
        return None
    try:
        expected = crypto.unsubscribe_mac(f"{PURPOSE}:{user_id}:{day}")
    except crypto.KeyUnavailableError:
        return None
    return user_id if hmac.compare_digest(expected, m.group(3)) else None


def leave(user_id: int, *, locale: legal.Locale) -> bool:
    """The consent withdrawn (a decision of source ``email``); True when it changed something, False when the reader had
    already left or never asked for the summary (then nothing is written)."""
    return consents.withdraw_if_granted(user_id, PURPOSE, locale=locale, source="email")
