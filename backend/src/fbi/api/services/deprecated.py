"""Endpoints on their way out (plan Cuotas, BE-033): each call is counted per UTC day in ``audit.deprecated_api_use`` - by kind of
caller and role, nothing that names a reader - so retiring one waits on evidence that survives a restart of the API.

The count is written after the answer has gone (a background task of the request) through its own short connection: the
endpoint answers as before, and a count that cannot be written is logged and dropped, never an error for the reader."""

from __future__ import annotations

from typing import Any, Literal

import psycopg
import structlog

from fbi.userdata.db import write_connection

log = structlog.get_logger(__name__)

Caller = Literal["browser", "e2e", "testclient", "script", "other"]

SUCCESSORS: dict[str, str] = {"/odds/best": "/api/v1/odds/board"}
"""Each endpoint on its way out and the one that replaces it (the ``Link: rel="successor-version"`` header)."""

_COUNT = """
INSERT INTO audit.deprecated_api_use (day, endpoint, caller, role)
VALUES ((now() AT TIME ZONE 'UTC')::date, %s, %s, %s)
ON CONFLICT (day, endpoint, caller, role) DO UPDATE
SET calls = audit.deprecated_api_use.calls + 1, last_at = now()
"""


def caller_kind(user_agent: str | None) -> Caller:
    """The kind of caller a User-Agent names: a test or a script must not keep an endpoint alive for readers."""
    ua = (user_agent or "").lower()
    if not ua:
        return "other"
    if "testclient" in ua:
        return "testclient"
    if "playwright" in ua or "headlesschrome" in ua or "headless" in ua:
        return "e2e"
    if any(s in ua for s in ("curl", "python-httpx", "python-requests", "httpie", "wget", "aiohttp", "go-http-client")):
        return "script"
    if "mozilla" in ua:
        return "browser"
    return "other"


def count_use(conn: psycopg.Connection[Any], endpoint: str, caller: Caller, role: str) -> None:
    """One more call of ``endpoint`` today by this kind of caller and role (the caller's own transaction)."""
    conn.execute(_COUNT, (endpoint, caller, (role or "unknown")[:40]))


def record_use(endpoint: str, caller: Caller, role: str) -> None:
    """``count_use`` on a connection of its own, committed; a failure is logged and dropped."""
    try:
        with write_connection() as conn:
            count_use(conn, endpoint, caller, role)
    except Exception as exc:  # a lost count must never become the reader's error
        log.warning("deprecated.use_not_recorded", endpoint=endpoint, caller=caller, error=exc.__class__.__name__)
