"""The messages to readers (plan UX, A5): the reader's notification preferences, the owner's view of the queue in the
Admin Console, and the provider's signed webhook.

The API never sends anything: it queues (fbi.customer.privacy and later phases), shows the queue, previews a message
as it would leave, and records what the provider says came back. The messenger process sends.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from psycopg.rows import dict_row

from fbi.api.contracts.messaging import (
    EmailCategory,
    MessageStatus,
    NotificationPreferences,
    NotificationPreferencesIn,
    OutboxMessage,
    OutboxPreview,
    OutboxSummary,
)
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App, same_site_only
from fbi.customer.db import CustomerError, write_connection
from fbi.messaging import outbox, preferences, webhooks
from fbi.messaging.templates import CATEGORIES, MANDATORY, render

router = APIRouter(prefix="/me", tags=["notifications"], dependencies=[Depends(same_site_only)])
admin_router = APIRouter(prefix="/messages", tags=["admin"])
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
STATUSES: tuple[MessageStatus, ...] = ("queued", "sent", "failed", "bounced", "complained", "suppressed")


def _preferences(p: preferences.Preferences) -> NotificationPreferences:
    return NotificationPreferences(
        email=[EmailCategory(category=c, on=p.email_on(c), locked=c in MANDATORY) for c in CATEGORIES],
        email_status=p.email_status,  # type: ignore[arg-type]
        email_status_at=p.email_status_at)


@router.get("/preferences", response_model=NotificationPreferences)
def my_notification_preferences(conn: Db, principal: App) -> NotificationPreferences:
    """Which e-mails the reader receives, by category, and whether their address can receive them."""
    return _preferences(preferences.read(conn, principal.user_id))


@router.patch("/preferences", response_model=NotificationPreferences)
def update_notification_preferences(body: NotificationPreferencesIn, principal: App) -> NotificationPreferences:
    """Switch the optional categories (membership, support) on or off. A mandatory one cannot be switched off (422
    ``mandatory_category``)."""
    try:
        return _preferences(preferences.update(principal.user_id, email={str(k): v for k, v in body.email.items()}))
    except CustomerError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc


# ── the owner (Admin Console) ─────────────────────────────────────────────────────────

def provider_configured() -> bool:
    return bool(os.environ.get("FBI_RESEND_API_KEY") and os.environ.get("FBI_EMAIL_FROM"))


@admin_router.get("", response_model=OutboxSummary)
def message_queue(conn: Db, status: Annotated[MessageStatus | None, Query()] = None,
                  limit: Annotated[int, Query(ge=1, le=200)] = 100) -> OutboxSummary:
    """The queue: is sending on, how many today, the last 7 days by status, and the latest messages (never a body)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT status, count(*) AS n FROM customer.messages_outbox "
                    "WHERE created_at > now() - interval '7 days' GROUP BY status")
        counts = dict.fromkeys(STATUSES, 0) | {r["status"]: int(r["n"]) for r in cur.fetchall()}
        cur.execute("""
            SELECT o.id, o.user_id, u.email AS user_email, o.category, o.template, o.locale, o.status, o.attempts,
                   o.created_at, CASE WHEN o.status = 'queued' THEN o.next_attempt_at END AS next_attempt_at,
                   o.sent_at, o.last_error
              FROM customer.messages_outbox o JOIN auth.users u ON u.id = o.user_id
             WHERE %(status)s::text IS NULL OR o.status = %(status)s
             ORDER BY o.id DESC LIMIT %(limit)s
        """, {"status": status, "limit": limit})
        rows = cur.fetchall()
    return OutboxSummary(sending=outbox.sending_enabled(), provider=provider_configured(), daily_cap=outbox.daily_cap(),
                         sent_today=outbox.sent_today(conn, datetime.now(UTC)), counts=counts,
                         messages=[OutboxMessage.model_validate(r) for r in rows])


@admin_router.get("/{message_id}/preview", response_model=OutboxPreview)
def message_preview(conn: Db, message_id: Annotated[int, Path(ge=1)]) -> OutboxPreview:
    """The message as it would leave now: rendered from the queue's parameters and the reader's current name."""
    row = conn.execute("""
        SELECT o.template, o.locale, o.params, u.display_name
          FROM customer.messages_outbox o JOIN auth.users u ON u.id = o.user_id WHERE o.id = %s
    """, (message_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "no such message")
    try:
        rendered = render(row[0], row[1], dict(row[2]), {"name": str(row[3] or "")})
    except ValueError as exc:
        raise ApiError(409, "preview_unavailable", f"this message does not render: {exc}"[:200]) from exc
    return OutboxPreview(subject=rendered.subject, text=rendered.text, html=rendered.html, link=rendered.link)


# ── the provider ──────────────────────────────────────────────────────────────────────

def _record(event: dict[str, Any]) -> webhooks.Outcome:
    with write_connection() as conn:
        return webhooks.apply_event(conn, event)


@webhook_router.post("/resend", status_code=204, include_in_schema=False)
async def resend_webhook(request: Request) -> Response:
    """Resend's events, signed (Svix). Without FBI_RESEND_WEBHOOK_SECRET the endpoint does not exist (404)."""
    secret = os.environ.get("FBI_RESEND_WEBHOOK_SECRET", "")
    if not secret:
        raise ApiError(404, "not_found", "no such route")
    body = await request.body()
    try:
        webhooks.verify(secret, request.headers, body, now=time.time())
    except webhooks.WebhookError as exc:
        raise ApiError(401, "bad_signature", str(exc)) from exc
    try:
        event = json.loads(body)
    except ValueError:
        raise ApiError(400, "bad_event", "the body is not JSON") from None
    if not isinstance(event, dict):
        raise ApiError(400, "bad_event", "the body is not an event")
    await run_in_threadpool(_record, event)
    return Response(status_code=204)

