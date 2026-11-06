"""The only reminder to an invitation nobody used (closing plan 4.1: «un solo recordatorio de activación a las 72 h»).

An account the owner invited (status ``invited``) whose invitation left 72 hours ago and has not been used, replaced or
expired gets one ``activation_reminder`` e-mail - the same message that tells the link's own expiry - and nothing more:
the message carries the invitation's own link (the same link, the same expiry: ``fbi.auth.tokens.arm`` derives it again
from the token's row), so it never extends the 7 days and never asks the account for anything it did not choose.

The reminder is once per invitation (the deduplication key is the token's row): an owner who sends a new invitation
starts a new count, and a reader who asks for a new link from the page of an expired one has asked for it. It is never
sent to an address that bounced or complained, and only while the self-service switch is on (FBI_SELF_SERVICE: the
links exist only then). The messenger runs it at the start of every cycle; it is idempotent.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
import structlog

from fbi.auth import tokens
from fbi.messaging import outbox

log = structlog.get_logger(__name__)

AFTER: Final = timedelta(hours=72)
"""How long an invitation waits before its only reminder (counted from when its e-mail left)."""
BATCH: Final = 200
"""The reminders one cycle writes at most; what is left waits for the next (every five minutes)."""

DUE_SQL = """
SELECT t.id, t.user_id
  FROM auth.account_tokens t
  JOIN auth.users u ON u.id = t.user_id
  LEFT JOIN customer.preferences p ON p.user_id = t.user_id
 WHERE t.purpose = 'invite' AND u.status = 'invited' AND u.role = 'USER'
   AND t.sent_at IS NOT NULL AND t.sent_at <= %(before)s
   AND t.used_at IS NULL AND t.revoked_at IS NULL AND t.expires_at > %(at)s
   AND COALESCE(p.email_status, 'ok') = 'ok'
   AND NOT EXISTS (SELECT 1 FROM customer.messages_outbox o
                    WHERE o.dedup_key = 'activation_reminder:' || t.id)
 ORDER BY t.sent_at, t.id
 LIMIT %(limit)s
"""


def queue(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    """Queue the reminders owed at ``at``, in the caller's transaction (it commits). Returns how many were queued."""
    if not tokens.self_service_enabled():
        return 0
    due = conn.execute(DUE_SQL, {"before": at - AFTER, "at": at, "limit": BATCH}).fetchall()
    queued = 0
    for token_id, user_id in due:
        if outbox.enqueue(conn, user_id=int(user_id), template="activation_reminder",
                          params={"grant": str(token_id)}, dedup_key=f"activation_reminder:{token_id}") is not None:
            queued += 1
    conn.commit()
    if queued:
        log.info("reminders.activation_queued", count=queued)
    return queued
