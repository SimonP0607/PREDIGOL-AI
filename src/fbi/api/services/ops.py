"""System health, Overview, data quality and the job ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from fbi.api.contracts.common import RunSummary
from fbi.api.contracts.ops import (
    CheckRun,
    ComponentHealth,
    CoverageRow,
    DatabaseStats,
    FixtureCounts,
    Freshness,
    IssueSummaryRow,
    Overview,
    ProviderState,
    ProviderStatus,
    QualityIssue,
    QualityReport,
    QuotaDay,
    RegisteredIssue,
    SystemHealth,
    WorkerState,
)
from fbi.api.envelope import DataStatus, Envelope, Section, listing, ok, section
from fbi.api.repositories import Conn, fetch_all
from fbi.api.repositories import fixtures as fixtures_repo
from fbi.api.repositories import ops as repo
from fbi.api.services.matches import summary
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.ops.heartbeat import latest_heartbeat
from fbi.quality.health import Health, health
from fbi.quality.metrics import QualitySnapshot, data_quality_snapshot

VERSION = "0.2.0"
QUALITY_HORIZON_HOURS = 96


def system_health(conn: psycopg.Connection[Any] | None) -> SystemHealth:
    h: Health = health(conn, version=VERSION, daily_budget=settings.provider_plan.effective_budget)
    d = h.as_dict()
    return SystemHealth(
        status=d["status"], checked_at=h.checked_at,
        app=ComponentHealth(**d["app"]), database=ComponentHealth(**d["database"]),
        worker=ComponentHealth(**d["worker"]), football_provider=ComponentHealth(**d["football_provider"]),
    )


def runs(conn: Conn, *, limit: int, job_type: str | None = None, status: str | None = None) -> Envelope[list[RunSummary]]:
    rows = repo.recent_runs(conn, limit=limit, job_type=job_type, status=status)
    return listing([RunSummary(**r) for r in rows], empty_reason="No ingestion run has been recorded yet.",
                   limit=limit)


def overview(conn: Conn) -> Envelope[Overview]:
    moment = now()
    sysh = system_health(conn)
    stats = DatabaseStats(**repo.database_stats(conn))
    beat = latest_heartbeat(conn)
    worker = WorkerState(
        alive=beat.is_alive(moment) if beat else None,
        last_beat_at=beat.last_beat_at if beat else None,
        started_at=beat.started_at if beat else None,
        ticks=beat.ticks if beat else None,
        last_tick_outcome=beat.last_tick_outcome if beat else None,
        scheduler_lag_ms=beat.scheduler_lag_ms if beat else None,
        code_version=beat.code_version if beat else None,
        next_runs={str(k): (str(v) if v else None) for k, v in (beat.jobs if beat else {}).items()},
    )
    prov = sysh.football_provider.data
    plan = settings.provider_plan
    provider = ProviderState(
        provider="api_football", plan=plan.plan,
        requests_today=int(prov.get("requests_today", 0) or 0),
        daily_budget=plan.effective_budget,
        requests_remaining=int(prov.get("remaining", 0) or 0),
        plan_daily_limit=plan.per_day_limit,
        last_error=prov.get("last_error"),
        last_error_at=prov.get("last_error_at"),
    )
    counts = repo.fixture_counts(conn, moment)
    next_id = repo.next_fixture_id(conn, moment)
    next_row = fixtures_repo.get_fixture(conn, next_id) if next_id else None
    fixtures = FixtureCounts(**counts, next_fixture=summary(next_row, moment) if next_row else None)
    fresh = Freshness(**repo.freshness(conn))
    recent = [RunSummary(**r) for r in repo.recent_runs(conn, limit=10)]
    picks = (
        Section[dict[str, int] | None](status=DataStatus.OK, data={"picks": stats.picks}) if stats.picks
        else Section[dict[str, int] | None](
            status=DataStatus.NOT_AVAILABLE, data=None, reason="The pick engine has not produced any pick yet.")
    )
    performance = section(None, status=DataStatus.INSUFFICIENT_DATA,
                          reason="Insufficient sample: no settled pick with a recorded price exists yet.")
    data_as_of = max((t for t in (fresh.last_payload_at, fresh.last_snapshot_at) if t), default=None)
    return ok(Overview(system=sysh, database=stats, worker=worker, provider=provider, fixtures=fixtures,
                       freshness=fresh, recent_runs=recent, picks=picks, performance=performance),
              data_as_of=data_as_of)


def _explain(s: QualitySnapshot) -> dict[str, str]:
    """A sentence for every null - and for the zeros that are easy to misread."""
    e: dict[str, str] = {}
    horizon = f"the next {s.horizon_hours} h"
    if s.fixtures_expected == 0:
        e["fixture_odds_coverage"] = f"No scheduled fixture of a tracked competition in {horizon}: there is nothing to cover."
    if s.bookmakers_active == 0:
        e["bookmaker_coverage"] = "No bookmaker is marked active."
    if s.markets_tracked == 0:
        e["market_coverage"] = "No market is marked tracked."
    if s.windows_expected_24h == 0:
        e["window_coverage_24h"] = "No tracked fixture kicked off in the last 24 h, so no capture window was due."
    if s.last_successful_capture is None:
        e["last_successful_capture"] = "No odds capture run has completed yet."
    if s.snapshots_24h == 0:
        e["snapshots_24h"] = "No snapshot in the last 24 h. Captures happen only inside pre-match windows of tracked fixtures."
    if s.unattributed_requests_today:
        e["unattributed_requests_today"] = (
            "Requests billed today that no closed run claims: ad-hoc calls such as a status check, "
            "a run still in flight, or a run that died.")
    return e


def quality(conn: Conn) -> Envelope[QualityReport]:
    snap = data_quality_snapshot(
        conn, horizon_hours=QUALITY_HORIZON_HOURS,
        prematch_windows=len(settings.odds.prematch_windows),
        daily_budget=settings.provider_plan.effective_budget,
    )
    return ok(QualityReport(snapshot=snap.as_dict(), explanations=_explain(snap)), data_as_of=snap.computed_at)


def coverage(conn: Conn) -> Envelope[list[CoverageRow]]:
    rows = repo.coverage_by_competition(conn, now(), QUALITY_HORIZON_HOURS)
    items = [CoverageRow(**r, odds_coverage=(round(r["fixtures_with_odds"] / r["fixtures_in_horizon"], 4)
                                              if r["fixtures_in_horizon"] else None)) for r in rows]
    return listing(items, empty_reason="No competition is tracked with a current season.")


def issues(conn: Conn) -> Envelope[list[QualityIssue]]:
    """Problems derived from the data itself, now - not a stored list that can go stale."""
    moment = now()
    snap = data_quality_snapshot(conn, horizon_hours=QUALITY_HORIZON_HOURS,
                                 prematch_windows=len(settings.odds.prematch_windows),
                                 daily_budget=settings.provider_plan.effective_budget)
    gaps = repo.lineage_gaps(conn)
    found: list[QualityIssue] = []

    def add(key: str, severity: str, title: str, detail: str, count: int, at: datetime = moment) -> None:
        if count:
            found.append(QualityIssue(key=key, severity=severity,  # type: ignore[arg-type]
                                      title=title, detail=detail, count=count, detected_at=at))

    add("awaiting_result", "high", "Fixtures past kick-off without a result",
        "Recorded as scheduled or live after kick-off. On the free plan a result becomes unreachable "
        "about a day after the match.", snap.fixtures_awaiting_result)
    add("stale_running_jobs", "critical", "Runs stuck in 'running'",
        "Open for over two hours: the process that owned them most likely died.", snap.stale_running_jobs)
    add("failed_jobs_24h", "high", "Failed or aborted runs (24 h)",
        "Runs that finished with errors and nothing durable, or stopped at a cap.", snap.failed_jobs_24h)
    add("partial_jobs_24h", "medium", "Partially successful runs (24 h)",
        "Runs that wrote something AND hit errors.", snap.partial_jobs_24h)
    add("stale_fixtures", "high", "Upcoming fixtures with stale odds",
        "Newest snapshot older than 4 h for a fixture still to be played.", snap.stale_fixtures)
    add("fixtures_without_lineage", "low", "Fixtures without payload lineage",
        "Last written before revision 0015; the payload that wrote them is not linked. "
        "The next sync or a raw replay records it.", int(gaps["fixtures_without_lineage"]))
    add("results_without_lineage", "low", "Results without payload lineage",
        "Written before revision 0015.", int(gaps["results_without_lineage"]))
    if snap.requests_remaining_today == 0:
        add("budget_exhausted", "critical", "Daily request budget exhausted",
            "No provider request will be issued until the UTC day rolls over.", 1)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    found.sort(key=lambda i: (order[i.severity], i.key))
    return listing(found, empty_reason="No data-quality issue detected.")


# ── the registry, as stored ──────────────────────────────────────────────────

QUOTA_PROVIDER = "api_football"


def registered_issues(conn: Conn, *, code: str | None = None, status: str | None = None,
                      open_only: bool = True, limit: int = 100) -> Envelope[list[RegisteredIssue]]:
    """audit.data_quality_issues as it is stored.

    Distinct from ``issues`` above, which derives problems from the data on every
    call. Both are useful and they answer different questions: that one says what is
    wrong NOW, this one says what we have RECORDED, with the payload each was read
    from and how many times it has been seen. Nothing here has been repaired.
    """
    rows = fetch_all(conn, repo.REGISTERED_ISSUES,
                     {"code": code, "status": status, "open_only": open_only, "limit": limit})
    return listing(
        [RegisteredIssue(**row) for row in rows],
        empty_reason="No data-quality issue has been recorded yet. Run scripts.quality_sweep.",
    )


def issue_summary(conn: Conn) -> Envelope[list[IssueSummaryRow]]:
    """Issues and occurrences counted separately: fifteen line-ups seen three times
    each are fifteen problems, not forty-five. ``is_provider_fact`` separates a fact
    about the provider's data, which we record and do not fix, from a fault of ours.
    """
    rows = fetch_all(conn, repo.ISSUE_SUMMARY, {})
    return listing([IssueSummaryRow(**row) for row in rows],
                   empty_reason="No open data-quality issues.")


def check_runs(conn: Conn, *, limit: int = 50) -> Envelope[list[CheckRun]]:
    """Each run records the population it ran against. Where a check spans more than
    one population it reports null rather than picking one, and the ratio is null as
    well: a figure over the wrong denominator is worse than no figure.
    """
    rows = fetch_all(conn, repo.CHECK_RUNS, {"limit": limit})
    return listing([CheckRun(**row) for row in rows],
                   empty_reason="No data-quality check has run yet.")


def provider_status(conn: Conn) -> Envelope[ProviderStatus]:
    """Provider posture, read-only. No credential is exposed, and none is read."""
    quota_rows = fetch_all(conn, repo.QUOTA_TODAY, {"provider": QUOTA_PROVIDER})
    facts = fetch_all(conn, repo.PROVIDER_FACTS, {"provider": QUOTA_PROVIDER})[0]
    today = QuotaDay(**quota_rows[0]) if quota_rows else None
    return ok(ProviderStatus(
        provider=QUOTA_PROVIDER,
        daily_guard=settings.provider_plan.effective_budget,
        today=today,
        **facts,
    ))
