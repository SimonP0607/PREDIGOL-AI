"""The owner's communiqués (closing plan 4.3): the console's routes and what readers see.

The console writes a draft, asks for the preview (which gives a code), and publishes with that code and the typed word.
The Telegram post is made after the publication has been committed and never decides it: if the channel fails, the
banner, Novedades and e-mail stand and the record says why. Readers get one public, read-only route.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Path, Request, Response

from fbi.api.contracts.announcements import (
    ActiveAnnouncements,
    Announcement,
    AnnouncementIn,
    AnnouncementList,
    AnnouncementLogLine,
    AnnouncementPreview,
    AnnouncementPublished,
    PublicNotice,
    PublicUpdate,
    PublishIn,
)
from fbi.api.errors import ApiError
from fbi.api.security import UsersAdmin
from fbi.customer import announcements as svc
from fbi.customer.db import CustomerError, write_connection

router = APIRouter(tags=["announcements"])
admin_router = APIRouter(prefix="/announcements", tags=["admin: announcements"])
AnnouncementId = Annotated[int, Path(ge=1)]
TELEGRAM_TRANSPORT: httpx.BaseTransport | None = None
"""Tests put a fake Telegram here; in production it stays None (the real API)."""


def _refused(exc: CustomerError) -> ApiError:
    return ApiError(exc.status, exc.code, str(exc))


def _content(body: AnnouncementIn) -> svc.Content:
    return svc.Content(**body.model_dump())


def _view(row: dict[str, Any]) -> Announcement:
    return Announcement.model_validate(row)


@admin_router.get("", response_model=AnnouncementList)
def list_announcements(_: UsersAdmin) -> AnnouncementList:
    with write_connection() as conn:
        rows = svc.listing(conn)
        today = svc.published_today(conn)
    return AnnouncementList(telegram_configured=svc.telegram_configured(), daily_cap=svc.daily_cap(),
                            published_today=today, items=[_view(r) for r in rows])


@admin_router.post("", response_model=Announcement, status_code=201)
def create_announcement(body: AnnouncementIn, actor: UsersAdmin) -> Announcement:
    try:
        with write_connection() as conn:
            new_id = svc.create(conn, actor.user_id, _content(body))
            return _view(svc.get(conn, new_id))
    except CustomerError as exc:
        raise _refused(exc) from exc


@admin_router.put("/{announcement_id}", response_model=Announcement)
def edit_announcement(body: AnnouncementIn, actor: UsersAdmin, announcement_id: AnnouncementId) -> Announcement:
    try:
        with write_connection() as conn:
            svc.edit(conn, actor.user_id, announcement_id, _content(body))
            return _view(svc.get(conn, announcement_id))
    except CustomerError as exc:
        raise _refused(exc) from exc


@admin_router.get("/{announcement_id}/log", response_model=list[AnnouncementLogLine])
def announcement_log(_: UsersAdmin, announcement_id: AnnouncementId) -> list[AnnouncementLogLine]:
    with write_connection() as conn:
        try:
            svc.get(conn, announcement_id)
        except CustomerError as exc:
            raise _refused(exc) from exc
        return [AnnouncementLogLine.model_validate(r) for r in svc.log_of(conn, announcement_id)]


@admin_router.post("/{announcement_id}/preview", response_model=AnnouncementPreview)
def preview_announcement(actor: UsersAdmin, announcement_id: AnnouncementId) -> AnnouncementPreview:
    """Step one of publishing: exactly what each destination will say, and the code step two needs."""
    try:
        with write_connection() as conn:
            code, expires, shown = svc.ask_to_publish(conn, actor.user_id, announcement_id)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return AnnouncementPreview(id=announcement_id, code=code, expires_at=expires, destinations=shown["destinations"],
                               published_today=shown["published_today"], daily_cap=shown["daily_cap"])


@admin_router.post("/{announcement_id}/publish", response_model=AnnouncementPublished)
def publish_announcement(body: PublishIn, actor: UsersAdmin, announcement_id: AnnouncementId) -> AnnouncementPublished:
    """Step two: the preview's code and the word PUBLICAR. The cap of the day is checked in the same transaction."""
    try:
        with write_connection() as conn:
            done = svc.publish(conn, actor.user_id, announcement_id, code=body.code, phrase=body.phrase)
            row = svc.get(conn, announcement_id)
    except CustomerError as exc:
        raise _refused(exc) from exc
    telegram = "not_requested"
    if done.telegram:
        sent, reason = svc.post_to_channel(row, transport=TELEGRAM_TRANSPORT)
        telegram = "sent" if sent else ("not_configured" if reason == "not_configured" else "failed")
        with write_connection() as conn:
            svc.record_telegram(conn, announcement_id, actor.user_id, sent=sent, reason=reason)
    return AnnouncementPublished(id=done.id, emails_queued=done.emails_queued,
                                 telegram=telegram)  # type: ignore[arg-type]


@admin_router.post("/{announcement_id}/retract", status_code=204)
def retract_announcement(actor: UsersAdmin, announcement_id: AnnouncementId) -> Response:
    try:
        with write_connection() as conn:
            svc.retract(conn, actor.user_id, announcement_id)
    except CustomerError as exc:
        raise _refused(exc) from exc
    return Response(status_code=204)


@router.get("/announcements/active", response_model=ActiveAnnouncements)
def active_announcements(response: Response) -> ActiveAnnouncements:
    """What the owner has published and is in force now: the banners (the most urgent first) and the entries of Novedades.
    Public and read-only: they are his own words, and a maintenance notice must reach someone who cannot sign in."""
    response.headers["cache-control"] = "public, max-age=60"
    with write_connection() as conn:
        banners = svc.active_banners(conn)
        updates = svc.published_updates(conn)
    return ActiveAnnouncements(banners=[PublicNotice.model_validate(b) for b in banners],
                               updates=[PublicUpdate.model_validate(u) for u in updates])


bot_router = APIRouter(tags=["announcements"])
"""Public: Telegram's own call. The secret in the path is its authentication (it carries no session and no Origin)."""


@bot_router.post("/telegram/webhook/{secret}", status_code=204)
async def telegram_webhook(secret: Annotated[str, Path(max_length=128)], request: Request) -> Response:
    """The bot says hello and gives the links when someone presses /start. It holds no conversation: anything else is
    ignored, and nothing the sender writes is read beyond that word or stored."""
    if not svc.webhook_secret_ok(secret):
        raise ApiError(404, "not_found", "no such route")
    try:
        update = await request.json()
    except ValueError:
        return Response(status_code=204)
    reply = svc.bot_welcome(update) if isinstance(update, dict) else None
    if reply is not None:
        svc.send_welcome(*reply, transport=TELEGRAM_TRANSPORT)
    return Response(status_code=204)
