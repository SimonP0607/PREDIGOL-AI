"""The provider's signed webhook (plan UX, A5): bounces and complaints come back and stop the e-mail.

Resend signs every event with Svix: the headers ``svix-id``, ``svix-timestamp`` and ``svix-signature`` (one or more
``v1,<base64>`` separated by spaces), an HMAC-SHA256 of ``<id>.<timestamp>.<raw body>`` with the endpoint's secret
(``whsec_<base64>``, FBI_RESEND_WEBHOOK_SECRET). An event older or newer than five minutes is refused (a replay);
a valid one changes the message's status and, for a hard bounce, a complaint or the provider's suppression, the
reader's deliverability, which stops the next messages (``outbox.suppression``) and shows in their profile.

Nothing of the event is stored: not the address, not the subject, not the provider's text - the message's status
and a short code. Opens and clicks are not tracked (no pixel, no rewritten link) and are ignored if they ever come.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
import structlog

log = structlog.get_logger(__name__)

TOLERANCE_S = 300
SAFE = re.compile(r"[^A-Za-z0-9_ .-]")


class WebhookError(ValueError):
    """A request that is not a valid, signed, fresh event: refused, nothing changes."""


def secret_key(secret: str) -> bytes:
    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (binascii.Error, ValueError):
        raise WebhookError("the webhook secret is not base64") from None
    if len(key) < 16:
        raise WebhookError("the webhook secret is too short")
    return key


def sign(secret: str, msg_id: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret_key(secret), f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify(secret: str, headers: Mapping[str, str], body: bytes, *, now: float) -> None:
    msg_id, timestamp, signatures = (headers.get("svix-id"), headers.get("svix-timestamp"),
                                     headers.get("svix-signature"))
    if not msg_id or not timestamp or not signatures:
        raise WebhookError("missing signature headers")
    if len(msg_id) > 100 or len(signatures) > 2000:
        raise WebhookError("malformed signature headers")
    try:
        sent = int(timestamp)
    except ValueError:
        raise WebhookError("malformed timestamp") from None
    if abs(now - sent) > TOLERANCE_S:
        raise WebhookError("timestamp outside the tolerance")
    expected = sign(secret, msg_id, timestamp, body).encode()
    for part in signatures.split():
        version, _, value = part.partition(",")
        if version == "v1" and hmac.compare_digest(value.encode(), expected):
            return
    raise WebhookError("no valid signature")


@dataclass(frozen=True, slots=True)
class Outcome:
    event: str
    applied: bool
    status: str | None = None


STATUS_OF: dict[str, str] = {
    "email.bounced": "bounced",
    "email.complained": "complained",
    "email.suppressed": "suppressed",
    "email.failed": "failed",
}
DELIVERABILITY_OF: dict[str, str] = {"bounced": "bounced", "complained": "complained", "suppressed": "bounced"}
"""What a status says about the address: the provider suppresses an address after a hard bounce or a complaint."""


def _code(value: Any) -> str:
    return SAFE.sub("", str(value))[:40] if value is not None else ""


def apply_event(conn: psycopg.Connection[Any], event: Mapping[str, Any]) -> Outcome:
    """Record one verified event in the caller's transaction. Idempotent (the provider may deliver it twice)."""
    raw_type, raw_data = event.get("type"), event.get("data")
    kind = raw_type[:60] if isinstance(raw_type, str) else ""
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    status = STATUS_OF.get(kind)
    email_id = data.get("email_id")
    if status is None or not isinstance(email_id, str) or not 0 < len(email_id) <= 100:
        return Outcome(kind, applied=False)
    note = kind.removeprefix("email.")
    if status == "bounced":
        raw_bounce = data.get("bounce")
        bounce: dict[str, Any] = raw_bounce if isinstance(raw_bounce, dict) else {}
        bounce_type = _code(bounce.get("type"))
        if bounce_type and bounce_type.lower() not in ("permanent", "undetermined"):
            # A temporary bounce: the provider keeps trying; the address is not judged by it.
            return Outcome(kind, applied=False)
        sub = _code(bounce.get("subType"))
        note = "bounced" + (f": {bounce_type or 'Permanent'}" + (f"/{sub}" if sub else ""))
    row = conn.execute("""
        UPDATE customer.messages_outbox SET status = %s, last_error = %s, updated_at = now()
         WHERE provider_id = %s AND status <> %s
        RETURNING id, user_id
    """, (status, note[:200], email_id, status)).fetchone()
    if row is None:
        return Outcome(kind, applied=False, status=status)
    deliverability = DELIVERABILITY_OF.get(status)
    if deliverability is not None:
        # The worse of the two stays: a bounce stops everything, a complaint only what the reader can switch off.
        conn.execute("""
            INSERT INTO customer.preferences (user_id, email_status, email_status_at) VALUES (%s, %s, now())
            ON CONFLICT (user_id) DO UPDATE SET
                email_status = CASE WHEN customer.preferences.email_status = 'bounced' THEN 'bounced'
                                    ELSE EXCLUDED.email_status END,
                email_status_at = CASE WHEN customer.preferences.email_status = 'bounced'
                                       THEN customer.preferences.email_status_at ELSE now() END,
                updated_at = now()
        """, (row[1], deliverability))
    log.info("webhook.applied", kind=kind, message_id=row[0], status=status)
    return Outcome(kind, applied=True, status=status)
