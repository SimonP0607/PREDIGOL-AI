"""Health of the four things that can be down: app, database, worker, provider.

Every check answers with a status and a reason, never with an exception, so
/health can always render. Nothing here exposes a credential, a hostname
with a password in it, or an account email.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

import psycopg
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.ops.heartbeat import latest_heartbeat
from fbi.providers.quota import read_usage

Status = Literal["ok", "degraded", "down", "unknown"]


@dataclass(frozen=True, slots=True)
class Check:
    status: Status
    detail: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Health:
    app: Check
    database: Check
    worker: Check
    football_provider: Check
    checked_at: datetime

    @property
    def status(self) -> Status:
        statuses = [self.app.status, self.database.status, self.worker.status, self.football_provider.status]
        if "down" in statuses:
            return "down"
        if "degraded" in statuses or "unknown" in statuses:
            return "degraded"
        return "ok"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checked_at": self.checked_at.isoformat(),
            "app": asdict(self.app),
            "database": asdict(self.database),
            "worker": asdict(self.worker),
            "football_provider": asdict(self.football_provider),
        }


def check_database(conn: psycopg.Connection) -> Check:
    try:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            row = cur.fetchone()
            revision = str(row[0]) if row else "none"
            cur.execute("SELECT count(*) FROM core.competitions WHERE is_tracked")
            active = int(cur.fetchone()[0])  # type: ignore[index]
        return Check("ok", f"reachable, schema at {revision}", {"revision": revision, "active_competitions": active})
    except psycopg.Error as exc:
        return Check("down", f"{exc.__class__.__name__}", {})


def check_worker(conn: psycopg.Connection) -> Check:
    """Liveness from the heartbeat, outcomes from the ledger.

    Two different questions. Is the process alive? - answered by the heartbeat
    it writes on every tick, busy or not. Did its jobs work? - answered by the
    ledger. The ledger alone cannot tell a quiet worker from a dead one, which
    is how a healthy worker came to be reported as "last run 400 min ago".
    """
    try:
        beat = latest_heartbeat(conn)
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT job_type, status, started_at, finished_at, last_error "
                "FROM raw.ingestion_runs WHERE job_type IN ('odds_capture','fixtures_sync','results_sync') "
                "ORDER BY started_at DESC LIMIT 1"
            )
            last = cur.fetchone()
            # Strictly 'completed'. A partial run is not a successful run, and
            # counting it as one would hide exactly what 'partial' was added
            # to reveal.
            cur.execute(
                "SELECT started_at FROM raw.ingestion_runs WHERE status = 'completed' "
                "ORDER BY started_at DESC LIMIT 1"
            )
            ok = cur.fetchone()
            cur.execute("SELECT count(*) FROM raw.ingestion_runs WHERE status = 'running' AND started_at < %s", (now() - timedelta(hours=2),))
            zombies = int(cur.fetchone()[0])  # type: ignore[index]
            cur.execute(
                "SELECT status, count(*) FROM raw.ingestion_runs WHERE started_at >= %s "
                "GROUP BY status",
                (now() - timedelta(hours=24),),
            )
            by_status = {str(k): int(v) for k, v in cur.fetchall()}
    except psycopg.Error as exc:
        return Check("unknown", f"ledger unreadable: {exc.__class__.__name__}")

    data: dict[str, Any] = {
        "heartbeat": beat.as_dict() if beat else None,
        "alive": beat.is_alive() if beat else None,
        "last_job": last[0] if last else None,
        "last_status": last[1] if last else None,
        "last_started_at": last[2].isoformat() if last else None,
        "last_successful_run": ok[0].isoformat() if ok else None,
        "last_error": last[4] if last else None,
        "stale_running_jobs": zombies,
        "runs_24h_by_status": by_status,
        "partial_runs_24h": by_status.get("partial", 0),
        "failed_runs_24h": by_status.get("failed", 0),
    }
    if beat is None:
        return _judge_from_ledger(last, zombies, data)
    if not beat.is_alive():
        silent = int((now() - beat.last_beat_at).total_seconds() // 60)
        if beat.stopped_at is not None and beat.stopped_at >= beat.last_beat_at:
            return Check("down", f"worker stopped {silent} min ago", data)
        return Check("down", f"no heartbeat for {silent} min: worker is not running", data)
    if zombies:
        return Check("degraded", f"{zombies} run(s) stuck in 'running' for over 2 h", data)
    if beat.last_tick_outcome in ("failed", "plan_rejected"):
        return Check("degraded", f"last tick: {beat.last_tick_outcome}", data)
    if last is not None:
        status = last[1]
        if status == "failed":
            return Check("degraded", f"last {last[0]} failed", data)
        if status == "partial":
            # The state this check used to miss entirely: work was done AND
            # errors happened, which the old two-state rule recorded as
            # 'completed' and read as healthy.
            return Check("degraded", f"last {last[0]} only partly succeeded", data)
        if status == "aborted":
            return Check("degraded", f"last {last[0]} stopped at a cap before finishing", data)
    beat_age = int((now() - beat.last_beat_at).total_seconds() // 60)
    return Check("ok", f"alive, last beat {beat_age} min ago", data)


LEDGER_STALE_AFTER = timedelta(minutes=45)  # 3 ticks of the 15-minute scheduler


def _judge_from_ledger(last: tuple[Any, ...] | None, zombies: int, data: dict[str, Any]) -> Check:
    """The pre-heartbeat rule, kept for a worker that has not yet written one
    (an older build still running). It can only ever say "unknown" or worse
    about liveness, because the ledger cannot tell quiet from dead - every
    detail says so."""
    if last is None:
        return Check("unknown", "no heartbeat and no run recorded yet", data)
    job_type, status, started_at, _finished, _error = last
    age = now() - started_at
    prefix = "no heartbeat (older worker build?); from the ledger: "
    if zombies:
        return Check("degraded", f"{prefix}{zombies} run(s) stuck in 'running' for over 2 h", data)
    if age > LEDGER_STALE_AFTER:
        return Check("degraded", f"{prefix}last run {int(age.total_seconds() // 60)} min ago", data)
    if status == "failed":
        return Check("degraded", f"{prefix}last {job_type} failed", data)
    if status == "partial":
        return Check("degraded", f"{prefix}last {job_type} only partly succeeded", data)
    if status == "aborted":
        return Check("degraded", f"{prefix}last {job_type} stopped at a cap before finishing", data)
    return Check("ok", f"{prefix}last run {int(age.total_seconds() // 60)} min ago", data)


def check_provider(conn: psycopg.Connection, daily_budget: int) -> Check:
    """Our budget, the last provider error, and whether the two counters agree.

    No live call: /health must never spend quota to report on quota. The figure
    shown is raw.provider_quota - the counter the capturer actually bills
    against, incremented before each request - rather than a sum over closed
    runs, which lags behind by a whole run and loses a crashed one entirely.
    """
    try:
        usage = read_usage(conn, budget=daily_budget)
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT last_error, started_at FROM raw.ingestion_runs WHERE errors > 0 "
                "ORDER BY started_at DESC LIMIT 1"
            )
            err = cur.fetchone()
            cur.execute("SELECT max(fetched_at) FROM raw.ingestion_payloads")
            last_payload = cur.fetchone()[0]  # type: ignore[index]
    except psycopg.Error as exc:
        return Check("unknown", f"ledger unreadable: {exc.__class__.__name__}")
    data: dict[str, Any] = {
        **usage.as_dict(),
        "last_error": err[0] if err else None,
        "last_error_at": err[1].isoformat() if err else None,
        "last_payload_at": last_payload.isoformat() if last_payload else None,
    }
    if usage.remaining == 0:
        return Check("degraded", "daily budget exhausted", data)
    # usage.unattributed is reported in `data` but is deliberately NOT a fault:
    # a bare `capture_odds status` opens no run, so it always produces some. The
    # crash it might indicate is caught by stale_running_jobs in check_worker.
    if err and (now() - err[1]) < timedelta(hours=1):
        return Check("degraded", "provider error in the last hour", data)
    return Check("ok", f"{usage.spent}/{usage.budget} requests today", data)


def health(conn: psycopg.Connection | None, *, version: str, daily_budget: int) -> Health:
    app = Check("ok", "running", {"version": version})
    if conn is None:
        down = Check("down", "no database connection")
        return Health(app, down, Check("unknown", "database down"), Check("unknown", "database down"), now())
    return Health(
        app=app,
        database=check_database(conn),
        worker=check_worker(conn),
        football_provider=check_provider(conn, daily_budget),
        checked_at=now(),
    )
