from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract, RunSummary
from fbi.api.contracts.matches import MatchSummary
from fbi.api.envelope import Section

ComponentStatus = Literal["ok", "degraded", "down", "unknown"]


class ComponentHealth(Contract):
    status: ComponentStatus
    detail: str
    data: dict[str, Any]
    code: str = Field(default="", description="Stable name of the reason (worker_alive, provider_ok...): the page "
                      "says it in the reader's language and falls back to detail.")
    vars: dict[str, Any] = Field(default_factory=dict, description="The values the reason names.")


class SystemHealth(Contract):
    status: ComponentStatus
    checked_at: datetime
    app: ComponentHealth
    database: ComponentHealth
    worker: ComponentHealth
    football_provider: ComponentHealth


class DatabaseStats(Contract):
    revision: str
    competitions_known: int
    competitions_tracked: int
    teams: int
    fixtures: int
    fixtures_with_result: int
    odds_snapshots: int
    near_close_snapshots: int
    bookmakers: int
    markets_tracked: int
    raw_payloads: int
    predictions: int
    picks: int


class WorkerState(Contract):
    alive: bool | None = Field(description="null when no heartbeat has ever been written.")
    last_beat_at: datetime | None
    started_at: datetime | None
    ticks: int | None
    last_tick_outcome: str | None
    scheduler_lag_ms: int | None
    code_version: str | None
    next_runs: dict[str, str | None]


class ProviderState(Contract):
    provider: str
    plan: str
    requests_today: int
    daily_budget: int
    requests_remaining: int
    plan_daily_limit: int
    last_error: str | None
    last_error_at: datetime | None


class FixtureCounts(Contract):
    upcoming_24h: int
    upcoming_7d: int
    awaiting_result: int
    finished: int
    finished_with_result: int
    next_fixture: MatchSummary | None


class Freshness(Contract):
    last_payload_at: datetime | None
    last_fixtures_sync_at: datetime | None
    last_results_sync_at: datetime | None
    last_odds_capture_at: datetime | None
    last_snapshot_at: datetime | None


class Overview(Contract):
    system: SystemHealth
    database: DatabaseStats
    worker: WorkerState
    provider: ProviderState
    fixtures: FixtureCounts
    freshness: Freshness
    recent_runs: list[RunSummary]
    picks: Section[dict[str, int] | None]
    performance: Section[None]


class QualityReport(Contract):
    """The data-quality snapshot, plus a sentence for every null.

    A null ratio is not 0%. ``explanations`` says, per field, why a value is
    null - the UI puts it in the tooltip where the number would have been.
    """

    snapshot: dict[str, Any]
    explanations: dict[str, str]


class CoverageRow(Contract):
    competition_id: int
    competition: str
    season: int
    fixtures_in_horizon: int
    fixtures_with_odds: int
    odds_coverage: float | None
    bookmakers_seen_24h: int
    markets_seen_24h: int
    last_capture_at: datetime | None
    fixtures_awaiting_result: int


class QualityIssue(Contract):
    key: str
    severity: Literal["critical", "high", "medium", "low"]
    title: str
    detail: str
    count: int
    detected_at: datetime


class JobHealth(Contract):
    """One scheduled or manual job type, as the ledger and the heartbeat see it."""

    job_type: str
    runs_24h: int
    failed_24h: int
    partial_24h: int
    api_calls_24h: int
    last_status: str | None
    last_started_at: datetime | None
    last_success_at: datetime | None
    last_error: str | None
    mean_duration_ms: int | None
    next_run_at: datetime | None = Field(description="From the worker's last heartbeat; null for manual jobs.")


class RegisteredIssue(Contract):
    """One row of audit.data_quality_issues - the registry, not a derived summary.

    Read-only and secret-free by construction: the fields are ids, a field name, an
    observed value and a sentence. `payload_hash` is a hash, and the params of the
    request it names are sanitised at the source.
    """

    id: int
    code: str
    severity: Literal["info", "warning", "error", "critical"]
    entity_type: str
    entity_id: int | None
    provider: str
    provider_entity_id: int | None
    field_name: str | None
    observed: str | None
    expected: str | None
    detail: str | None
    payload_hash: str | None
    occurrences: int
    status: str
    detected_at: datetime
    last_seen_at: datetime


class IssueSummaryRow(Contract):
    """Issues and occurrences counted separately: fifteen line-ups seen three times
    each are fifteen problems, not forty-five."""

    code: str
    code_name: str
    is_provider_fact: bool
    severity: str
    entity_type: str
    issues: int
    occurrences: int
    first_detected_at: datetime
    last_seen_at: datetime


class CheckRun(Contract):
    """One execution of one data-quality check, WITH the denominator it ran against.

    `population` is null when the check spans more than one population - two of the
    seven do - and `ratio` is then null as well rather than an invented figure.
    """

    id: int
    check_name: str
    scope: str
    severity: str
    passed: bool
    population: int | None
    offenders: int | None
    issues_opened: int
    ratio: float | None
    checked_at: datetime


class QuotaDay(Contract):
    """What we spent against the provider on one day, and the guard we set."""

    quota_date: date
    spent: int
    budget: int
    remaining: int
    used_fraction: float | None
    updated_at: datetime


class ProviderStatus(Contract):
    """Read-only provider posture. No credential is exposed, and none is read."""

    provider: str
    daily_guard: int
    """Our own budget, below the plan's limit. The guard is data about the posture,
    not metadata about the response."""
    today: QuotaDay | None
    last_7_days_spent: int
    payloads_stored: int
    newest_payload_at: datetime | None
    endpoints_seen: int
    provider_markets_known: int
    provider_markets_mapped: int
    provider_markets_observed_only: int
    """Bets that turned up in a payload and were never in the catalogue: the signal
    that the provider's own list moved."""
