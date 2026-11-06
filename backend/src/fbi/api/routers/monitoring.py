"""The browser's errors, forwarded to Sentry through this API, and the owner's test error (plan UX, A2).

The web reports its errors here (a Sentry "tunnel"), never to Sentry itself: the reader's address never reaches a
third party, the page's security policy needs no new origin, and every event takes the server's filter again
(fbi.core.sentry.scrub_event) before it leaves. The tunnel is not an open relay: it forwards only to this platform's
web project (FBI_SENTRY_WEB_DSN, which never leaves the server: the browser names a stand-in, fbi.core.sentry.
BROWSER_DSN), only error events (never attachments, replays, sessions or feedback text), an envelope is at most
100 KB, and a client and the whole process have their own limits - the free plan's month (5,000 errors) cannot be
spent from outside, through the tunnel or around it.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx
import structlog
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from fbi.api.contracts.monitoring import EnvelopeForwarded, MonitoringClient
from fbi.api.errors import ApiError
from fbi.api.limits import SlidingWindow
from fbi.api.security import client_ip
from fbi.core import sentry

log = structlog.get_logger("api.monitoring")

router = APIRouter(tags=["monitoring"])
admin_router = APIRouter(tags=["admin: monitoring"])

TUNNEL = "/api/v1/monitoring/envelope"
ENVELOPE_MAX_BYTES = 100 * 1024
MAX_ITEMS = 20
FORWARDED_TYPES = frozenset({"event"})
"""Only errors. Never "attachment", "replay_event", "replay_recording", "session", "feedback", "transaction"..."""
HEADER_FIELDS = ("event_id", "sent_at", "sdk")
"""The browser's envelope header fields that are kept; its "dsn" is replaced by the real one, "trace" dropped."""
PER_CLIENT = SlidingWindow(per_window=int(os.environ.get("FBI_MONITORING_RATE_LIMIT", "20")), window_s=60.0)
PER_PROCESS = SlidingWindow(per_window=int(os.environ.get("FBI_MONITORING_HOURLY_CAP", "10")), window_s=3600.0)
PER_DAY = SlidingWindow(per_window=int(os.environ.get("FBI_MONITORING_DAILY_CAP", "20")), window_s=86400.0)
"""Forwarded envelopes per API process (two on the server): at most ~1,200 web errors a month, the web's share of the
free plan's 5,000 (review of A2: the DSN is public, so anyone could spend the month from outside; the backend has
its own budget, fbi.core.sentry.EventBudget). Charged only for an envelope that is forwarded, so junk cannot use it."""
VITALS_PER_PROCESS = SlidingWindow(per_window=int(os.environ.get("FBI_MONITORING_VITALS_HOURLY_CAP", "2")), window_s=3600.0)
VITALS_PER_DAY = SlidingWindow(per_window=int(os.environ.get("FBI_MONITORING_VITALS_DAILY_CAP", "6")), window_s=86400.0)
"""Load times (LCP, INP, CLS; closing plan 5.3) have their own, much smaller share, per API process: at most ~360 a
month on the server's two processes. Past it a reading is dropped without an error (the browser must not retry) and the
errors' share above is never touched."""
TIMEOUT_S = 3.0
VITAL_MESSAGE = "web-vitals"
VITAL_NUMBER = re.compile(r"\d{1,6}(\.\d{1,3})?")
VITAL_ROUTE = re.compile(r"/[A-Za-z0-9/_.$-]{0,99}")
VITAL_RATINGS = frozenset({"good", "needs-improvement", "poor"})
VITAL_CHECKS: dict[str, Callable[[str], bool]] = {
    **dict.fromkeys(("lcp", "cls", "inp", "viewport"), lambda v: VITAL_NUMBER.fullmatch(v) is not None),
    "route": lambda v: VITAL_ROUTE.fullmatch(v) is not None,
    "rating": lambda v: v in VITAL_RATINGS,
    "display": lambda v: v in ("app", "browser"),
}


def is_vital(event: dict[str, Any]) -> bool:
    tags = event.get("tags")
    return event.get("message") == VITAL_MESSAGE and isinstance(tags, dict) and tags.get("kind") == "web_vital"


def clean_vital(event: dict[str, Any]) -> dict[str, Any] | None:
    """A load-time reading as it may leave: built again from the few fields it needs - the numbers, the screen's path,
    the rating, the device's width and kind - and nothing else (no user, no breadcrumbs, no contexts, no extra)."""
    tags = event.get("tags")
    if not isinstance(tags, dict):
        return None
    kept: dict[str, str] = {"kind": "web_vital"}
    for key, valid in VITAL_CHECKS.items():
        value = tags.get(key)
        if isinstance(value, str) and valid(value):
            kept[key] = value
    if not {"lcp", "cls", "inp"} & kept.keys():
        return None
    keys = ("event_id", "timestamp", "platform", "release", "environment", "sdk")
    out: dict[str, Any] = {k: event[k] for k in keys if k in event}
    return {**out, "level": "info", "message": VITAL_MESSAGE, "tags": kept}


class EnvelopeError(ValueError):
    """Not a Sentry envelope this tunnel can read."""


@router.get("/monitoring/client", response_model=MonitoringClient)
def get_client() -> MonitoringClient:
    dsn = sentry.web_dsn()
    return MonitoringClient(enabled=dsn is not None, dsn=sentry.BROWSER_DSN if dsn else None,
                            environment=sentry.environment(), tunnel=TUNNEL)


def parse_envelope(body: bytes) -> tuple[dict[str, Any], list[tuple[str, bytes]]]:
    """The envelope's header and its items (type, payload), by the format Sentry documents: a JSON header line, then
    for each item a JSON header line and its payload - ``length`` bytes when the item header gives a length, else
    up to the next newline."""
    first, _, rest = body.partition(b"\n")
    try:
        header = json.loads(first)
    except (ValueError, RecursionError) as exc:
        raise EnvelopeError("the header is not JSON") from exc
    if not isinstance(header, dict):
        raise EnvelopeError("the header is not an object")
    items: list[tuple[str, bytes]] = []
    while rest.strip():
        line, _, rest = rest.partition(b"\n")
        try:
            item = json.loads(line)
        except (ValueError, RecursionError) as exc:
            raise EnvelopeError("an item header is not JSON") from exc
        if not isinstance(item, dict):
            raise EnvelopeError("an item header is not an object")
        length = item.get("length")
        if isinstance(length, int) and not isinstance(length, bool) and length >= 0:
            if length > len(rest):
                raise EnvelopeError("an item is shorter than its length")
            payload, rest = rest[:length], rest[length:]
            rest = rest[1:] if rest.startswith(b"\n") else rest
        else:
            payload, _, rest = rest.partition(b"\n")
        items.append((str(item.get("type", "")), payload))
        if len(items) > MAX_ITEMS:
            raise EnvelopeError("too many items")
    return header, items


def envelope_url(dsn: str) -> str:
    """https://<key>@<host>/<project> -> https://<host>/api/<project>/envelope/"""
    parts = urlsplit(dsn)
    project = parts.path.strip("/").rsplit("/", 1)[-1]
    host = parts.netloc.rsplit("@", 1)[-1]
    if parts.scheme not in ("https", "http") or not host or not project:
        raise EnvelopeError("the DSN is not usable")
    return f"{parts.scheme}://{host}/api/{project}/envelope/"


def build_envelope(header: dict[str, Any], events: list[dict[str, Any]], dsn: str) -> bytes:
    """The envelope Sentry receives: the browser's header fields that say nothing about the reader, under the web
    project's real DSN (the browser only knew the stand-in), and the filtered events."""
    kept = {"dsn": dsn, **{k: header[k] for k in HEADER_FIELDS if k in header}}
    lines = [json.dumps(kept, separators=(",", ":")).encode()]
    for event in events:
        # ASCII: a lone surrogate (half an emoji cut by a browser) is written as an escape instead of failing
        payload = json.dumps(event, separators=(",", ":")).encode()
        lines.append(json.dumps({"type": "event", "length": len(payload)}, separators=(",", ":")).encode())
        lines.append(payload)
    return b"\n".join(lines) + b"\n"


def forward(dsn: str, envelope: bytes) -> int:
    """POST the filtered envelope to Sentry; its HTTP status (0 when it could not be reached)."""
    try:
        with httpx.Client(timeout=TIMEOUT_S, follow_redirects=False) as client:
            reply = client.post(envelope_url(dsn), content=envelope,
                                headers={"content-type": "application/x-sentry-envelope"})
        return reply.status_code
    except httpx.HTTPError:
        return 0


@router.post("/monitoring/envelope", response_model=EnvelopeForwarded)
async def post_envelope(request: Request) -> EnvelopeForwarded:
    dsn = sentry.web_dsn()
    if dsn is None:
        raise ApiError(404, "not_found", "the web reports no errors on this server")
    if not PER_CLIENT.allow(client_ip(request) or "unknown"):
        raise ApiError(429, "rate_limited", "too many error reports", headers={"retry-after": "60"})
    body = await request.body()
    if len(body) > ENVELOPE_MAX_BYTES:
        raise ApiError(413, "too_large", "an error report is at most 100 KB")
    try:
        header, items = parse_envelope(body)
    except EnvelopeError as exc:
        raise ApiError(400, "bad_envelope", "not an error report this server reads") from exc
    if header.get("dsn") != sentry.BROWSER_DSN:
        raise ApiError(400, "bad_envelope", "not this platform's project")
    events: list[dict[str, Any]] = []
    for kind, payload in items:
        if kind not in FORWARDED_TYPES:
            continue
        try:
            event = json.loads(payload)
        except (ValueError, RecursionError):
            continue
        if isinstance(event, dict):
            cleaned = sentry.scrub_event(event, keep_agent=True)
            if cleaned is not None:
                events.append(cleaned)
    vitals = [v for v in (clean_vital(e) for e in events if is_vital(e)) if v is not None][:1]
    events = [e for e in events if not is_vital(e)]
    if not events and not vitals:
        return EnvelopeForwarded(events=0)
    if events and (not PER_PROCESS.allow("all") or not PER_DAY.allow("all")):
        raise ApiError(429, "rate_limited", "too many error reports", headers={"retry-after": "3600"})
    if vitals and not (VITALS_PER_PROCESS.allow("all") and VITALS_PER_DAY.allow("all")):
        vitals = []  # past the readings' own share: dropped without an error
    events = events + vitals
    if not events:
        return EnvelopeForwarded(events=0)
    status = await run_in_threadpool(forward, dsn, build_envelope(header, events, dsn))
    log.info("monitoring.forwarded", events=len(events), upstream=status)
    if status == 429:
        raise ApiError(429, "rate_limited", "the error service asks to wait", headers={"retry-after": "60"})
    return EnvelopeForwarded(events=len(events))


class MonitoringTestError(RuntimeError):
    """Raised on purpose by the owner, to see an error arrive with the fields it should carry and none it must not."""


@admin_router.post("/monitoring/test-error")
def post_test_error() -> None:
    """An error raised on purpose (plan UX, A2: the intentional test). It answers 500 with its request id, like any
    unexpected error, and reaches Sentry with that id, the release and the owner's pseudonym - only a SUPER_ADMIN
    can raise it."""
    raise MonitoringTestError("PrediGol monitoring test (A2): raised on purpose from the console")
