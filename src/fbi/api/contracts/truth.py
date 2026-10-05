"""Data truth in the Admin Console: the audit's matrix, live freshness, the tables, the model gate."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

FreshnessState = Literal["FRESH", "STALE", "UNKNOWN", "UNAVAILABLE"]


class TruthRun(Contract):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    requests: int
    seed: float | None
    findings: int
    by_severity: dict[str, int]
    report_dir: str | None


class TruthMatrixRow(Contract):
    dataset: str
    api: str = Field(description="What the provider showed for the audited scope.")
    db: str = Field(description="What the database held for the same scope.")
    difference: str
    checked: int
    matched: int
    findings: int
    worst: str | None
    freshness: str
    freshness_status: FreshnessState | None
    model_safe: str
    role: str = Field(description="REQUIRED, OPTIONAL or NOT_USED: the strongest need any model has for it.")
    api_key: dict[str, Any] = Field(default_factory=dict, description="{key, params}: the api column as a message.")
    db_key: dict[str, Any] = Field(default_factory=dict)
    by_kind: dict[str, int] = Field(default_factory=dict)
    freshness_counts: dict[str, int] = Field(default_factory=dict)
    safe_code: str | None = Field(default=None, description="yes, yes_optional, partial, no or na.")
    safe_reasons: list[str] = Field(default_factory=list)


class FreshnessDataset(Contract):
    dataset: str
    sla: str
    entity: str
    status: FreshnessState
    label: str
    total: int
    counts: dict[str, int]
    by_competition: list[dict[str, Any]]
    examples: dict[str, list[str]]


class FreshnessReport(Contract):
    measured_at: datetime
    datasets: list[FreshnessDataset]


DatasetClass = Literal["FRESH", "STALE", "INCOMPLETE", "INVALID", "UNKNOWN"]
ModelEligibility = Literal["MODEL_READY", "NOT_MODEL_READY", "NOT_USED"]


class DatasetRegisterRow(Contract):
    dataset: str
    klass: DatasetClass = Field(description="FRESH, STALE (the provider has newer data and asking was our job), "
                                            "INCOMPLETE (5%+ never read), INVALID (open critical/high finding at "
                                            "PrediGol's fault), UNKNOWN (nothing to measure now).")
    model: ModelEligibility
    model_reason: str
    role: str = Field(description="The strongest need any model has for it: REQUIRED, OPTIONAL, NOT_USED.")
    endpoints: list[str]
    sla: str
    freshness: str
    coverage: float | None = Field(description="Fresh share of what we are responsible for (provider gaps excluded).")
    provider_gap: float | None = Field(description="Share the provider does not have (coverage flag or its lag).")
    last_capture: datetime | None
    last_write: datetime | None
    rows: int
    errors_24h: int
    failed_runs_24h: int
    open_findings: int
    blockers: list[str]
    notes: list[str]


class DatasetRegister(Contract):
    measured_at: datetime
    dataset_version: str | None
    dataset_version_status: str | None
    rows: list[DatasetRegisterRow]


class GateModel(Contract):
    model: str
    passing: int
    blocked: int
    blocked_by: dict[str, int]
    needs: dict[str, str]


class GateFixture(Contract):
    provider_fixture_id: int
    competition: str
    kickoff_at: datetime
    datasets: dict[str, dict[str, str]]
    models: dict[str, bool]


class GateReport(Contract):
    measured_at: datetime
    horizon_hours: int
    fixtures: int
    models: list[GateModel]
    sample: list[GateFixture]


class TruthSummary(Contract):
    run: TruthRun
    matrix: list[TruthMatrixRow]
    freshness: list[FreshnessDataset]
    gate: dict[str, Any]
    datasets: dict[str, Any]
    failures: list[str]


class TruthFinding(Contract):
    id: int
    dataset: str
    entity: str
    field: str
    kind: str
    severity: str
    api_value: str | None
    db_value: str | None
    note: str


class StandingsAuditRow(Contract):
    competition_id: int
    competition: str
    country: str | None
    provider_league_id: int
    season: int
    status: FreshnessState
    reason_code: str = Field(description="not_covered, no_table, no_match_yet, reflects_last_match, "
                                         "provider_not_updated or not_asked_since.")
    reason: str
    snapshot_at: datetime | None = Field(description="When the newest table content was first seen.")
    checked_at: datetime | None = Field(description="When the provider was last asked for this table.")
    changed_at: datetime | None
    provider_updated_at: datetime | None = Field(description="The provider's own update stamp on the rows.")
    last_finished_at: datetime | None = Field(description="Kick-off of the season's last finished match.")
    rows: int
    rows_skipped: int
    groups: int
    extended: bool = Field(description="Whether the newest snapshot carries home/away and zone descriptions.")


class DataRepair(Contract):
    id: int
    repaired_at: datetime
    rule: str
    entity: str
    entity_id: int
    provider_ref: int | None
    field: str
    before_value: str | None
    after_value: str | None
    reason: str


class CoverageCompetition(Contract):
    competition_id: int
    competition: str
    country: str | None
    season: int
    provider_league_id: int | None
    flag_odds: bool | None = Field(description="The provider's own coverage flag for odds, as last read.")
    fixtures: int = Field(description="Played matches in the window.")
    asked: int = Field(description="Asked for at all: before kick-off (capture) or after it (final prices).")
    priced: int = Field(description="The provider priced it: captured before kick-off or read after it.")
    captured: int = Field(description="Captured before kick-off - the only prices a pick can use.")
    recovered: int = Field(description="Not captured; the provider's final pre-match prices read after the match.")
    priced_two_plus: int
    median_bookmakers: float | None
    provider_share: float
    capture_share: float
    bookmakers: dict[str, int]
    markets: dict[str, int]
    misses: dict[str, int] = Field(description="Never asked for before kick-off, by cause: worker_down, "
                                               "known_too_late, kickoff_moved, missed_while_up.")
    upcoming: dict[str, int] = Field(description="Next 72 h by capture-plan state.")
    state: Literal["NOT_ASKED", "NOT_COVERED", "UNPRICED_BY_PROVIDER", "THIN", "PARTIAL", "COVERED"]
    reason: str


class CoverageBookmaker(Contract):
    provider_bookmaker_id: int
    name: str
    state: Literal["ACTIVE", "DORMANT", "CATALOGUE_ONLY"]
    fixtures: int
    share: float
    competitions: int
    countries: int
    markets: dict[str, int]
    first_seen: datetime | None
    last_seen: datetime | None
    name_missing: bool


class CoverageMarket(Contract):
    market_key: str
    fixtures: int
    share: float
    bookmakers: int
    median_bookmakers: float | None


class CoverageCountry(Contract):
    country: str
    competitions: int
    fixtures: int
    priced: int
    captured: int
    bookmakers: int


class CoverageLocal(Contract):
    brand: str
    domain: str
    company: str
    state: Literal["PRICED_BY_PROVIDER_BRAND", "CATALOGUE_ONLY", "NOT_IN_PROVIDER"]
    provider_names: list[str]
    priced_fixtures: int
    colombian_edition_confirmed: bool
    note: str


class OddsSource(Contract):
    key: str
    name: str
    kind: str
    access: Literal["ACTIVE", "FREE_NEEDS_OWNER", "PAYMENT_REQUIRED", "CLOSED", "REJECTED"]
    bookmakers: str
    colombian_books: list[str]
    closing_line: str
    cost: str
    decision: str
    sources: list[str]


class OddsCoverageReport(Contract):
    measured_at: datetime
    since: datetime
    until: datetime
    days: int
    first_capture: datetime | None
    fixtures: int
    asked: int
    priced: int
    captured: int
    recovered: int
    misses: dict[str, int]
    worker_down_hours: float
    critical: list[str] = Field(description="Our gaps: matches missed while the worker was running, knew "
                                            "about them in time and had their final kick-off.")
    competitions: list[CoverageCompetition]
    bookmakers: list[CoverageBookmaker]
    markets: list[CoverageMarket]
    countries: list[CoverageCountry]
    local: list[CoverageLocal]
    local_source: dict[str, str]
    sources: list[OddsSource]


class CompetitionScoreRow(Contract):
    competition_season_id: int
    competition_id: int
    competition: str
    country: str | None
    season: int
    is_current: bool
    is_tracked: bool
    segment: str = Field(description="club league, cup, continental, national team, women, youth...")
    data_class: Literal["MODEL_READY", "PARTIAL", "PRODUCT_ONLY", "INSUFFICIENT"]
    score: float
    finished: int
    approved: int
    quarantined: int
    components: dict[str, float]
    reasons: list[str]
    computed_at: datetime


class QuarantinedFixture(Contract):
    fixture_id: int
    provider_fixture_id: int
    competition: str
    season: int
    kickoff_at: datetime
    home: str
    away: str
    status_short: str
    failed: list[str]


class ValidationSummary(Contract):
    rule_version: str | None
    computed_at: datetime | None
    fixtures: int
    states: dict[str, int]
    failed: dict[str, int]
    classes: dict[str, int]
    approved_by_segment: dict[str, int]


class TruthV2Run(Contract):
    """One data truth audit V2 command (standings, team stats, player stats, leagues, fixtures, identity,
    fields): when, how many provider requests (each a new raw payload), and its summary."""

    id: int
    kind: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    requests: int
    summary: dict[str, Any]
    report_dir: str | None


class EvidenceEntry(Contract):
    """One E-XXX entry of the evidence ledger: an established discrepancy with its evidence."""

    code: str
    key: str
    area: str
    issue_type: str
    severity: Literal["critical", "high", "medium", "low", "info"]
    at_fault: Literal["provider", "predigol", "none", "undetermined"]
    entity: str | None
    claim: str
    api_evidence: dict[str, Any] | None
    db_evidence: dict[str, Any] | None
    external_evidence: dict[str, Any] | None
    root_cause: str | None
    fix: str | None
    test: str | None
    status: Literal["OPEN", "FIXED", "ACCEPTED", "MONITOR", "CLEARED"]
    first_seen_at: datetime
    last_seen_at: datetime
    times_seen: int


class TruthV2Overview(Contract):
    runs: list[TruthV2Run]
    """The newest run of each kind."""
    ledger: list[EvidenceEntry]
    counts: dict[str, dict[str, int]]
    """status -> severity -> entries, over the whole ledger."""


class EvidenceDecision(Contract):
    status: Literal["OPEN", "FIXED", "ACCEPTED", "MONITOR"]
    note: str | None = Field(default=None, max_length=500)
