from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.envelope import Section


class BacktestMetrics(Contract):
    run_id: int
    name: str
    protocol: str
    test_from: date
    test_to: date
    n_samples: int
    brier: Decimal
    logloss: Decimal
    ece: Decimal
    odds_source: str | None
    n_bets: int | None
    roi_pct: Decimal | None = Field(description="Null unless historical prices were available for every bet.")
    yield_pct: Decimal | None
    near_close_lv_mean: Decimal | None = Field(description="Line value against near-close snapshots, NOT CLV.")
    code_version: str
    finished_at: datetime | None


class ModelVersionSummary(Contract):
    model_id: int
    name: str
    family: str
    description: str
    version_id: int
    version: str
    status: str
    train_from: date
    train_to: date
    n_train: int
    code_version: str
    created_at: datetime
    latest_backtest: BacktestMetrics | None


class MarketBaselineSummary(Contract):
    fixtures_with_consensus: int
    methods: list[str]
    last_as_of: datetime | None


class ModelsOverview(Contract):
    market_baseline: Section[MarketBaselineSummary | None]
    models: Section[list[ModelVersionSummary]]


class PickRow(Contract):
    id: int
    fixture_id: int
    market_key: str
    selection: str
    line: Decimal
    mode: str
    status: str
    model_version_id: int
    decision_rule_version: str
    market_odds: Decimal
    odds_captured_at: datetime
    p_calibrated: Decimal
    p_market_fair: Decimal
    edge: Decimal
    price_edge: Decimal
    ev: Decimal
    stake_units: Decimal
    data_cutoff_ts: datetime
    created_at: datetime
    result_status: str | None
    profit_units: Decimal | None


class PicksOverview(Contract):
    candidates_by_decision: dict[str, int]
    picks_by_mode: dict[str, int]
    picks: Section[list[PickRow]]


class PerformanceSummary(Contract):
    settled: int
    pending: int
    staked_units: Decimal | None
    profit_units: Decimal | None
    roi_pct: Decimal | None
    hit_rate: Decimal | None
    note: str
