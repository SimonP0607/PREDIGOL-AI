from __future__ import annotations

from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query, Response

from fbi.api.contracts.common import RunSummary
from fbi.api.contracts.notify import NotificationRow, NotificationsOverview
from fbi.api.contracts.ops import CoverageRow, Overview, QualityIssue, QualityReport, SystemHealth
from fbi.api.deps import get_db, read_only_connection
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.services import ops

router = APIRouter(tags=["system"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


@router.get("/health", response_model=SystemHealth)
def get_health(response: Response) -> SystemHealth:
    """Never 5xx because the database is down: it reports it."""
    try:
        conn: psycopg.Connection[Any] | None = read_only_connection()
    except psycopg.OperationalError:
        conn = None
    try:
        h = ops.system_health(conn)
    finally:
        if conn is not None:
            conn.close()
    if h.status == "down":
        response.status_code = 503
    return h


@router.get("/health/quality", response_model=Envelope[QualityReport])
def get_quality(conn: Db) -> Envelope[QualityReport]:
    return ops.quality(conn)


@router.get("/overview", response_model=Envelope[Overview])
def get_overview(conn: Db) -> Envelope[Overview]:
    return ops.overview(conn)


@router.get("/ingestion/runs", response_model=Envelope[list[RunSummary]])
def get_runs(
    conn: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    job_type: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z_]+$")] = None,
    status: Literal["running", "completed", "partial", "failed", "aborted"] | None = None,
) -> Envelope[list[RunSummary]]:
    return ops.runs(conn, limit=limit, job_type=job_type, status=status)


@router.get("/data-quality/coverage", response_model=Envelope[list[CoverageRow]])
def get_coverage(conn: Db) -> Envelope[list[CoverageRow]]:
    return ops.coverage(conn)


@router.get("/data-quality/issues", response_model=Envelope[list[QualityIssue]])
def get_issues(conn: Db) -> Envelope[list[QualityIssue]]:
    return ops.issues(conn)


@router.get("/notifications", response_model=Envelope[NotificationsOverview])
def get_notifications(conn: Db, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[NotificationsOverview]:
    """What the bot produced and what happened to each message. It informs; it cannot bet."""
    import os

    from fbi.api.repositories import fetch_all

    rows = fetch_all(conn, "SELECT id, kind, title, body, created_at, channel, status, attempts, sent_at, last_error "
                           "FROM audit.notifications ORDER BY id DESC LIMIT %s", (limit,))
    counts = fetch_all(conn, "SELECT status, count(*) AS n FROM audit.notifications GROUP BY status")
    body = NotificationsOverview(
        channel_configured=bool(os.environ.get("FBI_TELEGRAM_BOT_TOKEN") and os.environ.get("FBI_TELEGRAM_CHAT_ID")),
        by_status={str(r["status"]): int(r["n"]) for r in counts},
        recent=[NotificationRow(**r) for r in rows])
    if not rows:
        return unavailable(body, "The notifier has produced nothing yet: it reacts to shadow picks, settlements, "
                                 "the first capture and failures.", status=DataStatus.EMPTY)
    return ok(body)
