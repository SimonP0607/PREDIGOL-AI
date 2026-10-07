from __future__ import annotations

import os
from typing import Annotated, Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Query, Response

from fbi.api.contracts.common import RunSummary
from fbi.api.contracts.notify import NotificationRow, NotificationsOverview
from fbi.api.contracts.ops import (
    CheckRun,
    CoverageRow,
    IssueSummaryRow,
    JobHealth,
    Overview,
    ProviderStatus,
    QualityIssue,
    QualityReport,
    RegisteredIssue,
    SystemHealth,
)
from fbi.api.deps import get_db, read_only_connection
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.services import ops

router = APIRouter(tags=["system"])
admin_router = APIRouter(tags=["admin: operations & data quality"])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


@router.get("/health", response_model=SystemHealth)
def get_health(response: Response) -> SystemHealth:
    """Never 5xx because the database is down: it reports it.

    Anyone may ask, so a deployment answers HOW each part is, not WHY (FBI_API_HEALTH_DETAIL=0): the
    reasons name the schema revision, the provider's quota and its last error. The Admin Console reads
    the full picture through /api/v1/admin/overview."""
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
    if os.environ.get("FBI_API_HEALTH_DETAIL", "1").strip().lower() in {"0", "false", "no", "off"}:
        h = h.model_copy(update={part: getattr(h, part).model_copy(update={"detail": "", "data": {}, "vars": {}})
                                 for part in ("app", "database", "worker", "football_provider")})
    return h


@admin_router.get("/health/quality", response_model=Envelope[QualityReport])
def get_quality(conn: Db) -> Envelope[QualityReport]:
    return ops.quality(conn)


@admin_router.get("/overview", response_model=Envelope[Overview])
def get_overview(conn: Db) -> Envelope[Overview]:
    return ops.overview(conn)


@admin_router.get("/ingestion/runs", response_model=Envelope[list[RunSummary]])
def get_runs(
    conn: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    job_type: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z_]+$")] = None,
    status: Literal["running", "completed", "partial", "failed", "aborted", "interrupted", "stale"] | None = None,
) -> Envelope[list[RunSummary]]:
    return ops.runs(conn, limit=limit, job_type=job_type, status=status)


@admin_router.get("/data-quality/coverage", response_model=Envelope[list[CoverageRow]])
def get_coverage(conn: Db) -> Envelope[list[CoverageRow]]:
    return ops.coverage(conn)


@admin_router.get("/data-quality/issues", response_model=Envelope[list[QualityIssue]])
def get_issues(conn: Db) -> Envelope[list[QualityIssue]]:
    return ops.issues(conn)


@admin_router.get("/data-quality/registry", response_model=Envelope[list[RegisteredIssue]])
def get_registered_issues(
    conn: Db,
    code: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    open_only: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Envelope[list[RegisteredIssue]]:
    """audit.data_quality_issues as stored: what we RECORDED, with its provenance.

    /data-quality/issues derives problems from the data on every call. This reads the
    registry, so an issue that was seen, recorded and then resolved is still visible
    with the reason it was closed.
    """
    return ops.registered_issues(conn, code=code, status=status, open_only=open_only, limit=limit)


@admin_router.get("/data-quality/registry/summary", response_model=Envelope[list[IssueSummaryRow]])
def get_issue_summary(conn: Db) -> Envelope[list[IssueSummaryRow]]:
    return ops.issue_summary(conn)


@admin_router.get("/data-quality/checks", response_model=Envelope[list[CheckRun]])
def get_check_runs(conn: Db,
                   limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[list[CheckRun]]:
    """Every check run, with the denominator it ran against."""
    return ops.check_runs(conn, limit=limit)


@admin_router.get("/provider", response_model=Envelope[ProviderStatus])
def get_provider_status(conn: Db) -> Envelope[ProviderStatus]:
    """Quota, raw store and provider catalogue. No credential is exposed or read."""
    return ops.provider_status(conn)


@admin_router.get("/notifications", response_model=Envelope[NotificationsOverview])
def get_notifications(conn: Db, limit: Annotated[int, Query(ge=1, le=200)] = 50) -> Envelope[NotificationsOverview]:
    """What the bot produced and what happened to each message. It informs; it cannot bet."""
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


JOBS_SQL = """
    SELECT job_type,
           count(*) FILTER (WHERE started_at > now() - interval '24 hours') AS runs_24h,
           count(*) FILTER (WHERE started_at > now() - interval '24 hours' AND status = 'failed') AS failed_24h,
           count(*) FILTER (WHERE started_at > now() - interval '24 hours' AND status = 'partial') AS partial_24h,
           COALESCE(sum(api_calls) FILTER (WHERE started_at > now() - interval '24 hours'), 0) AS api_calls_24h,
           (array_agg(status ORDER BY started_at DESC))[1] AS last_status,
           max(started_at) AS last_started_at,
           max(started_at) FILTER (WHERE status IN ('completed', 'partial')) AS last_success_at,
           -- the LAST run's error, not the latest error ever: a job that failed once
           -- a week ago and has run cleanly since must not show that error as current.
           (array_agg(last_error ORDER BY started_at DESC))[1] AS last_error,
           avg(duration_ms) FILTER (WHERE started_at > now() - interval '7 days')::int AS mean_duration_ms
    FROM raw.ingestion_runs WHERE job_type <> 'unspecified'
    GROUP BY job_type ORDER BY max(started_at) DESC
"""


@admin_router.get("/ops/jobs", response_model=Envelope[list[JobHealth]])
def get_jobs(conn: Db) -> Envelope[list[JobHealth]]:
    """Every job type: what ran in the last 24 h, what failed, when it last succeeded, when it runs next."""
    from datetime import datetime

    from fbi.api.repositories import fetch_all, fetch_one

    hb = fetch_one(conn, "SELECT jobs FROM raw.worker_heartbeats ORDER BY last_beat_at DESC LIMIT 1")
    scheduled: dict[str, str] = dict((hb or {}).get("jobs") or {})
    rows = []
    for r in fetch_all(conn, JOBS_SQL):
        nxt = scheduled.get(str(r["job_type"]))  # scheduler job ids are the ledger's job types
        rows.append(JobHealth(**r, next_run_at=datetime.fromisoformat(nxt) if nxt else None))
    if not rows:
        return unavailable(rows, "The job ledger is empty.", status=DataStatus.EMPTY)
    return ok(rows)
