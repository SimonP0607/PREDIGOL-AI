"""The queue of messages to readers (plan UX, A5): ``customer.messages_outbox``.

* ``enqueue`` - in the caller's transaction (a privacy request and its receipt are one commit): the template, the
  reader's language, the template's parameters (``templates.check_params`` refuses anything else) and a
  deduplication key; a second message with the same key is not a second message.
* ``dispatch`` - the messenger's part: one message per transaction (``FOR UPDATE SKIP LOCKED``), the reader's address
  and name read at that moment, their choices applied (an optional category they switched off, an address that
  bounced or complained), rendered, sent with an idempotency key, and the provider's answer recorded. Retries after
  1 min, 5 min, 30 min, 2 h and 12 h, then 'failed'; a daily cap under the provider's quota; the most urgent first
  (security and account, then privacy, support, membership and the legal notices, which go to everyone at once).

Nothing is sent while ``FBI_EMAIL_SEND`` is off: the messenger does not call ``dispatch`` and the queue waits.

An e-mail with a one-use link (plan UX, A7) gets its link in the transaction that sends it (``fbi.auth.tokens.arm``):
a link that must no longer leave (used, replaced, the account changed) suppresses its message, and so does a message
past its moment (``Template.stale_after``). Without the server's key the link cannot be made: the message waits.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.auth import crypto, tokens
from fbi.messaging.provider import Outgoing, Provider, ProviderError
from fbi.messaging.templates import (
    MANDATORY,
    OPTIONAL,
    TEMPLATES,
    TemplateError,
    check_params,
    render,
)

log = structlog.get_logger(__name__)

RETRY_DELAYS: tuple[timedelta, ...] = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30),
                                       timedelta(hours=2), timedelta(hours=12))
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
DEFAULT_DAILY_CAP = 90
"""Messages a day (UTC) the messenger hands to the provider: Resend Free allows 100, received e-mails included."""
PRIORITY_SQL = ("CASE o.category WHEN 'security' THEN 0 WHEN 'account' THEN 0 WHEN 'privacy' THEN 1 "
                "WHEN 'support' THEN 2 WHEN 'membership' THEN 3 ELSE 4 END")


def sending_enabled() -> bool:
    """FBI_EMAIL_SEND, born off (plan UX, section 41): off, the queue fills and nothing leaves."""
    return os.environ.get("FBI_EMAIL_SEND", "0").strip().lower() in ("1", "true", "yes", "on")


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("FBI_EMAIL_DAILY_CAP", str(DEFAULT_DAILY_CAP))))
    except ValueError:
        return DEFAULT_DAILY_CAP


# ── enqueue ───────────────────────────────────────────────────────────────────────────

def enqueue(conn: psycopg.Connection[Any], *, user_id: int, template: str, params: Mapping[str, str],
            dedup_key: str) -> int | None:
    """Queue one message in the caller's transaction. Its id, or None when the key was queued before."""
    t = check_params(template, params)
    if not 8 <= len(dedup_key) <= 200:
        raise TemplateError(f"a deduplication key of 8 to 200 characters, not {dedup_key!r}")
    row = conn.execute("""
        INSERT INTO customer.messages_outbox (user_id, category, template, locale, params, dedup_key)
        SELECT u.id, %s, %s, u.language, %s, %s FROM auth.users u WHERE u.id = %s
        ON CONFLICT (dedup_key) DO NOTHING
        RETURNING id
    """, (t.category, t.name, Json(dict(params)), dedup_key, user_id)).fetchone()
    if row is None:
        return None
    log.info("outbox.queued", message_id=row[0], template=t.name, category=t.category)
    return int(row[0])


# ── dispatch ──────────────────────────────────────────────────────────────────────────

@dataclass
class DispatchReport:
    sent: int = 0
    retried: int = 0
    failed: int = 0
    suppressed: int = 0
    deferred: int = 0
    """Not attempted: the provider's daily or monthly quota (no attempt spent)."""
    capped: bool = False
    stopped: str | None = None
    """Why the pass ended before the queue was empty: the cap, a quota, the provider's configuration."""
    last_error: str | None = None


CLAIM_SQL = f"""
SELECT o.id, o.user_id, o.category, o.template, o.locale, o.params, o.dedup_key, o.attempts, o.created_at,
       u.email, u.display_name, u.timezone, p.email_off, p.email_status
  FROM customer.messages_outbox o
  JOIN auth.users u ON u.id = o.user_id
  LEFT JOIN customer.preferences p ON p.user_id = o.user_id
 WHERE o.status = 'queued' AND o.next_attempt_at <= %s
 ORDER BY {PRIORITY_SQL}, o.next_attempt_at, o.id
 LIMIT 1
   FOR UPDATE OF o SKIP LOCKED
"""


def sent_today(conn: psycopg.Connection[Any], at: datetime) -> int:
    midnight = at.replace(hour=0, minute=0, second=0, microsecond=0)
    row = conn.execute("SELECT count(*) FROM customer.messages_outbox WHERE sent_at >= %s", (midnight,)).fetchone()
    return int(row[0]) if row else 0


def suppression(row: Mapping[str, Any], at: datetime | None = None) -> str | None:
    """Why this message must not leave, or None. The reader's choices, their address's deliverability and - from A7 -
    whether its moment has passed."""
    email = str(row["email"] or "")
    if not email or email.endswith(".invalid"):
        return "no address"
    if at is not None:
        template = TEMPLATES.get(str(row.get("template") or ""))
        if template is not None and template.stale_after is not None and row["created_at"] < at - template.stale_after:
            return "too late: its moment has passed"
    status = row["email_status"] or "ok"
    if status == "bounced":
        return "address bounced"
    if status == "complained" and row["category"] not in MANDATORY:
        return "address complained"
    if row["category"] in OPTIONAL and row["category"] in (row["email_off"] or []):
        return "switched off by the reader"
    return None


def idempotency_key(dedup_key: str, created_at: datetime) -> str:
    """The same message, the same key, whichever attempt and whichever messenger: the provider sends it once."""
    return f"{dedup_key}@{int(created_at.timestamp())}"[:256]


def _finish(conn: psycopg.Connection[Any], message_id: int, sql: str, params: tuple[Any, ...]) -> None:
    conn.execute(f"UPDATE customer.messages_outbox SET {sql}, updated_at = now() WHERE id = %s", (*params, message_id))
    conn.commit()


def dispatch(conn: psycopg.Connection[Any], provider: Provider, *, at: datetime, limit: int = 20,
             cap: int | None = None) -> DispatchReport:
    """Send what is due, at most ``limit`` messages. Commits after each message."""
    report = DispatchReport()
    cap = daily_cap() if cap is None else cap
    used = sent_today(conn, at)
    conn.commit()
    for _ in range(limit):
        if used >= cap:
            report.capped, report.stopped = True, f"daily cap of {cap} reached"
            break
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(CLAIM_SQL, (at,))
            row = cur.fetchone()
        if row is None:
            conn.commit()
            break
        mid = int(row["id"])
        reason = suppression(row, at)
        armed: tokens.Armed | None = None
        template = TEMPLATES.get(str(row["template"]))
        if reason is None and template is not None and template.grant is not None:
            grant = str(dict(row["params"]).get("grant", ""))
            try:
                armed = tokens.arm(conn, int(grant), user_id=int(row["user_id"]), purpose=template.grant,
                                   at=at) if grant.isdigit() else None
            except crypto.KeyUnavailableError:
                # Every link would fail the same way: the message waits, no attempt spent, and the pass stops.
                _finish(conn, mid, "next_attempt_at = %s, last_error = %s",
                        (at + timedelta(minutes=30), "the server's key is missing: no link can be made"))
                report.deferred += 1
                report.stopped = report.last_error = "auth key unavailable"
                log.error("outbox.no_key", message_id=mid, template=row["template"])
                break
            if armed is None:
                reason = "its link no longer works (used, replaced or the account changed)"
        if reason is not None:
            _finish(conn, mid, "status = 'suppressed', last_error = %s", (reason,))
            report.suppressed += 1
            log.info("outbox.suppressed", message_id=mid, template=row["template"], reason=reason)
            continue
        try:
            rendered = render(row["template"], row["locale"], dict(row["params"]),
                              {"name": str(row["display_name"] or "")}, zone=str(row["timezone"] or "UTC"),
                              link=armed.link if armed else None, until=armed.expires_at if armed else None)
        except ValueError as exc:  # TemplateError, or a legal text the register does not know
            # A bug, never the reader's: recorded, the owner is told (outbox_failing), the queue goes on.
            _finish(conn, mid, "status = 'failed', attempts = attempts + 1, last_error = %s",
                    (f"template: {exc}"[:200],))
            report.failed += 1
            report.last_error = "template error"
            log.error("outbox.template_failed", message_id=mid, template=row["template"], error=str(exc)[:200])
            continue
        message = Outgoing(to=str(row["email"]), subject=rendered.subject, text=rendered.text, html=rendered.html,
                           idempotency_key=idempotency_key(row["dedup_key"], row["created_at"]),
                           tags={"category": row["category"], "template": row["template"]})
        try:
            provider_id = provider.send(message)
        except ProviderError as exc:
            report.last_error = exc.code
            attempt = int(row["attempts"]) + 1
            if exc.kind in ("quota_day", "quota_month"):
                if exc.kind == "quota_day":
                    later = at.replace(hour=0, minute=5, second=0, microsecond=0) + timedelta(days=1)
                else:
                    later = at + timedelta(hours=12)
                _finish(conn, mid, "next_attempt_at = %s, last_error = %s", (later, exc.code))
                report.deferred += 1
                report.stopped = exc.code
                log.warning("outbox.quota", message_id=mid, code=exc.code, next_attempt_at=later.isoformat())
                break
            if exc.kind == "permanent" or attempt >= MAX_ATTEMPTS:
                _finish(conn, mid, "status = 'failed', attempts = %s, last_error = %s", (attempt, exc.code))
                report.failed += 1
                log.error("outbox.failed", message_id=mid, template=row["template"], code=exc.code, attempts=attempt)
            else:
                delay = RETRY_DELAYS[attempt - 1]
                if exc.retry_after_s is not None:
                    delay = max(delay, timedelta(seconds=exc.retry_after_s))
                _finish(conn, mid, "attempts = %s, next_attempt_at = %s, last_error = %s",
                        (attempt, at + delay, exc.code))
                report.retried += 1
                log.warning("outbox.retry", message_id=mid, template=row["template"], code=exc.code,
                            attempts=attempt, next_attempt_at=(at + delay).isoformat())
            if exc.kind == "config":
                report.stopped = exc.code  # every other message would fail the same way: wait for the owner
                break
            continue
        except BaseException:
            conn.rollback()  # the row goes back to the queue untouched; the idempotency key prevents a double send
            raise
        _finish(conn, mid, "status = 'sent', attempts = attempts + 1, sent_at = %s, provider_id = %s, last_error = NULL",
                (at, provider_id))
        report.sent += 1
        used += 1
        log.info("outbox.sent", message_id=mid, template=row["template"], category=row["category"])
    return report
