from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.envelope import Section


class CalibrationBucket(Contract):
    lower: float
    upper: float
    n: int
    mean_predicted: float | None
    observed_rate: float | None


class ScoreSummary(Contract):
    n: int
    brier: float
    log_loss: float
    ece: float


class MarketComparison(Contract):
    """Model minus market on the fixtures BOTH priced. Negative = the model scored better."""

    baseline_key: str
    market_key: str
    line: Decimal
    n_common: int
    model_logloss: Decimal
    baseline_logloss: Decimal
    logloss_diff: Decimal
    logloss_diff_ci_low: Decimal
    logloss_diff_ci_high: Decimal
    model_brier: Decimal
    baseline_brier: Decimal
    brier_diff: Decimal
    brier_diff_ci_low: Decimal
    brier_diff_ci_high: Decimal
    verdict: Literal["worse", "indistinguishable", "better"] = Field(
        description="'better' only when the whole 95% paired-bootstrap interval of the log-loss difference is below 0.")


class SplitRow(Contract):
    key: str
    label: str
    n: int
    model_logloss: float
    baseline_logloss: float
    logloss_diff: float


class Coverage(Contract):
    targets: int
    predicted: int
    uncovered: dict[str, int]
    fits: int
    failed_fits: int
    no_interval: int


class HypotheticalBetting(Contract):
    hypothetical: Literal[True] = True
    rule: str
    odds_source: str
    fixtures_priced: int
    n_bets: int
    staked_units: Decimal
    profit_units: Decimal
    roi_pct: Decimal | None
    roi_ci_low: Decimal | None
    roi_ci_high: Decimal | None
    max_drawdown_units: Decimal | None
    mean_probability_edge: float | None
    note: str


class BacktestMetrics(Contract):
    run_id: int
    name: str
    protocol: str
    session_id: int | None
    test_from: date
    test_to: date
    n_samples: int
    brier: Decimal
    logloss: Decimal
    ece: Decimal
    accuracy_pct: Decimal = Field(description="Reported because the table has it. Never used to rank a model.")
    coverage: Coverage | None
    primary: MarketComparison | None = Field(description="Against the session's primary baseline, 1X2.")
    vs_market: list[MarketComparison]
    calibration: list[CalibrationBucket]
    over_under_2_5: ScoreSummary | None
    btts: ScoreSummary | None = Field(description="No market baseline exists for BTTS in the historical source.")
    by_competition: list[SplitRow]
    by_month: list[SplitRow]
    betting: HypotheticalBetting | None
    odds_source: str | None
    n_bets: int | None
    roi_pct: Decimal | None = Field(description="Hypothetical backtest ROI, never a record of real bets.")
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
    hyperparameters: dict[str, Any]
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


class BaselineScore(Contract):
    baseline_key: str
    source: str
    bookmaker_code: str
    price_kind: str = Field(description="As the SOURCE labels it ('closing', 'pre_closing'); not our capture.")
    devig_method: str
    market_key: str
    line: Decimal
    n_samples: int
    brier: Decimal
    logloss: Decimal
    ece: Decimal
    mean_overround: Decimal | None
    is_primary: bool


class CompetitionName(Contract):
    id: int
    name: str


class BacktestSessionSummary(Contract):
    id: int
    session_uuid: str
    name: str
    protocol: str
    competitions: list[CompetitionName]
    validation_season: int | None
    test_season: int
    test_from: date
    test_to: date
    n_targets: int
    primary_baseline: str
    dataset_hash: str
    code_version: str
    finished_at: datetime | None
    selection: dict[str, Any] = Field(description="Hyper-parameters chosen on the validation season only.")
    config: dict[str, Any]


class ModelsOverview(Contract):
    market_baseline: Section[MarketBaselineSummary | None] = Field(
        description="Live consensus from OUR captured snapshots.")
    backtest: Section[BacktestSessionSummary | None]
    historical_baselines: Section[list[BaselineScore]] = Field(
        description="How the de-vigged historical market itself scored on the backtest's test fixtures.")
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
