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
