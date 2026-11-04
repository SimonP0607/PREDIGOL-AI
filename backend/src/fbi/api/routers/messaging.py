"""The messages to readers (plan UX, A5): the reader's notification preferences, the owner's view of the queue in the
Admin Console, the provider's signed webhook and the one-click leaving of the weekly summary (B8).

The API never sends anything: it queues (fbi.customer.privacy and later phases), shows the queue, previews a message
as it would leave, and records what the provider says came back. The messenger process sends.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

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
    UnsubscribeIn,
    UnsubscribeResult,
)
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App, client_ip, same_site_only
from fbi.auth import recovery, throttle, tokens
from fbi.auth.service import AuthError
from fbi.customer.db import CustomerError, write_connection
from fbi.messaging import outbox, preferences, webhooks
from fbi.messaging import unsubscribe as leaving
from fbi.messaging.templates import CATEGORIES, MANDATORY, TEMPLATES, render

router = APIRouter(prefix="/me", tags=["notifications"], dependencies=[Depends(same_site_only)])
admin_router = APIRouter(prefix="/messages", tags=["admin"])
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])
unsubscribe_router = APIRouter(prefix="/email", tags=["notifications"])
"""Public: the signed link of a commercial e-mail is its authentication (plan UX, B8); a mail client's one-click POST
(RFC 8058) carries no session and no Origin of PrediGol."""
LEAVE_TRIES = throttle.FailureWindow(max_failures=20, window_s=900)
"""Links to leave the summary that did not work one client may present in 15 minutes (as the account's links,
fbi.auth.recovery): a signature of 132 bits cannot be guessed, and a client that keeps trying is cut short anyway."""
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
    """The message as it would leave now: rendered from the queue's parameters and the reader's current name and time
    zone. An e-mail with a one-use link shows a stand-in, never a link (plan UX, A7): the preview makes none."""
    row = conn.execute("""
        SELECT o.template, o.locale, o.params, u.display_name, u.timezone
          FROM customer.messages_outbox o JOIN auth.users u ON u.id = o.user_id WHERE o.id = %s
    """, (message_id,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", "no such message")
    template = TEMPLATES.get(str(row[0]))
    until = (datetime.now(UTC) + tokens.LIFETIME[template.grant]
             if template is not None and template.grant is not None else None)
    try:
        rendered = render(row[0], row[1], dict(row[2]), {"name": str(row[3] or "")}, zone=str(row[4] or "UTC"),
                          until=until)
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


def _leave(conn: psycopg.Connection[Any], token: str, request: Request) -> UnsubscribeResult:
    key = recovery.client_key(client_ip(request))
    if LEAVE_TRIES.blocked(key):
        raise AuthError(429, "too_many_attempts", retry_after=LEAVE_TRIES.retry_after(key))
    user_id = leaving.read(token, datetime.now(UTC))
    row = (None if user_id is None
           else conn.execute("SELECT language FROM auth.users WHERE id = %s", (user_id,)).fetchone())
    conn.rollback()
    if user_id is None or row is None:
        LEAVE_TRIES.fail(key)
        raise ApiError(400, "invalid_link", "this link to leave the summary is not valid")
    locale: Literal["es", "en"] = "en" if row[0] == "en" else "es"
    try:
        left = leaving.leave(user_id, locale=locale)
    except CustomerError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    return UnsubscribeResult(left=left)


@unsubscribe_router.post("/unsubscribe", response_model=UnsubscribeResult)
def unsubscribe(request: Request, conn: Db,
                t: Annotated[str, Query(min_length=26, max_length=60)]) -> UnsubscribeResult:
    """The mail client's one-click button (``List-Unsubscribe-Post: List-Unsubscribe=One-Click``, RFC 8058): leaves the
    weekly summary at once, the consent ``marketing_email`` withdrawn (source ``email``). RFC 8058 leaves no other place
    for the link than the address, so the token is in its query (the API's log keeps only the path, Sentry drops the
    query); the body is not read. Works whatever the switches say, for a year; a second click changes nothing (``left``
    false). A link that is not one of PrediGol's: 400 ``invalid_link``."""
    return _leave(conn, t, request)


@unsubscribe_router.post("/unsubscribe/link", response_model=UnsubscribeResult,
                         dependencies=[Depends(same_site_only)])
def unsubscribe_from_page(body: UnsubscribeIn, request: Request, conn: Db) -> UnsubscribeResult:
    """The same from the page of PrediGol the e-mail's link opens (``/unsubscribe#t=...``): the token travels in the
    body, as every link of the account does (A7) - never in an address an access log would keep."""
    return _leave(conn, body.token, request)
