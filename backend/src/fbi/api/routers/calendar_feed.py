"""A reader's calendar of the teams they follow over HTTP (Plan Maestro PM, PM-14-06, OP-43; BE-084). Behind ``FBI_CALENDAR_FEED``
(off by default): off, every route here answers 404.

* ``GET /me/calendar-feed`` - whether the reader has a live link, since when and when a calendar last read it (never the secret).
* ``POST /me/calendar-feed`` - a new link (the previous one revoked): its secret URL is in this answer and nowhere else.
* ``DELETE /me/calendar-feed`` - the link revoked: the calendar stops updating at its next reading.
* ``GET /calendar/feed/{token}.ics`` - PUBLIC (a calendar app carries no session): the iCalendar file. The secret in the path is its
  authentication; an unknown, malformed or revoked one is a plain 404, and a client that keeps failing is held back
  (``MISSES``). Read-only, no price, probability or pick (``fbi.api.services.calendar_feed``); ``no-store``, ``noindex``, no referrer.

The token's security review: ``backend/docs/owner/BE_084_REVISION_SEGURIDAD_CALENDARIO.md``.
"""

from __future__ import annotations

import contextlib
from typing import Annotated, Any, Final

import psycopg
from fastapi import APIRouter, Depends, Path, Request, Response

from fbi.api.contracts.calendar_feed import CalendarFeedMade, CalendarFeedStatus
from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.api.security import App, client_ip
from fbi.api.services import calendar_feed as ics
from fbi.api.switches import calendar_feed_on
from fbi.auth.throttle import FailureWindow
from fbi.core.clock import now
from fbi.customer import calendar_feed as feeds
from fbi.customer.db import CustomerError

router = APIRouter(prefix="/me", tags=["calendar"])
public_router = APIRouter(tags=["calendar"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
Token = Annotated[str, Path(min_length=1, max_length=64)]

MISSES = FailureWindow(max_failures=20, window_s=15 * 60)
"""Per client address: 20 wrong secrets in 15 minutes and the next answers are 429 for the rest of the window (a 256-bit secret cannot
be guessed; this only keeps a scanner from costing reads)."""
PATH: Final = "/calendar/feed/"


def _gate() -> None:
    if not calendar_feed_on():
        raise ApiError(404, "not_found", "not found")


def _status(conn: psycopg.Connection[Any], user_id: int) -> CalendarFeedStatus:
    feed = feeds.live(conn, user_id)
    teams = len(ics.followed_teams(conn, user_id))
    if feed is None:
        return CalendarFeedStatus(active=False, teams=teams)
    return CalendarFeedStatus(active=True, created_at=feed.created_at, last_read_at=feed.last_read_at, teams=teams)


@router.get("/calendar-feed", response_model=CalendarFeedStatus)
def get_feed(conn: Db, principal: App) -> CalendarFeedStatus:
    """TU CALENDARIO: whether the reader has a live link (the secret is never shown again)."""
    _gate()
    return _status(conn, principal.user_id)


@router.post("/calendar-feed", response_model=CalendarFeedMade)
def make_feed(conn: Db, principal: App) -> CalendarFeedMade:
    """A new secret link; the previous one stops working. 409 ``calendar_feed_busy`` when two are made at once."""
    _gate()
    try:
        made = feeds.make(principal.user_id, at=now())
    except CustomerError as exc:
        raise ApiError(exc.status, exc.code, str(exc)) from exc
    conn.rollback()  # a fresh snapshot: written by another connection
    return CalendarFeedMade(path=f"/api/v1{PATH}{made.token}.ics", status=_status(conn, principal.user_id))


@router.delete("/calendar-feed", response_model=CalendarFeedStatus)
def revoke_feed(conn: Db, principal: App) -> CalendarFeedStatus:
    """The link revoked (idempotent)."""
    _gate()
    feeds.revoke(principal.user_id, at=now(), why="reader")
    conn.rollback()
    return _status(conn, principal.user_id)


@public_router.get("/calendar/feed/{token}.ics", include_in_schema=False)
def read_feed(token: Token, request: Request, conn: Db) -> Response:
    """The iCalendar file of the link's reader. 404 for anything that is not a live link; 429 for a client that keeps missing."""
    _gate()
    key = client_ip(request) or "unknown"
    if MISSES.blocked(key):
        raise ApiError(429, "too_many_requests", "too many wrong links; try again later")
    feed = feeds.resolve(conn, token)
    if feed is None:
        MISSES.fail(key)
        raise ApiError(404, "not_found", "not found")
    at = now()
    body = ics.calendar_of(conn, feed.user_id, at=at)
    with contextlib.suppress(Exception):  # noting the reading never fails it
        feeds.touch(feed, at=at)
    return Response(content=body.encode("utf-8"), media_type="text/calendar; charset=utf-8",
                    headers={"X-Robots-Tag": "noindex, nofollow", "Content-Disposition": 'inline; filename="predigol.ics"'})


def redact(path: str) -> str:
    """The request's path as the API logs it: a calendar secret never reaches a log line."""
    if path.startswith("/api/v1" + PATH):
        return "/api/v1" + PATH + "<secreto>.ics"
    return path


__all__ = ["MISSES", "public_router", "redact", "router"]
