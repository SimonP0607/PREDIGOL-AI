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


class PickEvent(Contract):
    from_status: str | None
    to_status: str
    at: datetime
    reason: str


class PickRow(Contract):
    """A shadow pick with everything it claims traced to where it came from."""

    id: int
    fixture_id: int
    fixture: str
    competition: str
    kickoff_at: datetime
    market_key: str
    selection: str
    line: Decimal
    status: Literal["shadow", "qualified", "published", "settled"]
    mode: str
    model: str
    model_version: str
    prediction_id: int | None
    data_cutoff_ts: datetime
    feature_set_hash: str
    calibrated: bool = Field(description="False: the model's own probability, no calibrator applied.")
    bookmaker: str
    market_odds: Decimal
    odds_captured_at: datetime
    odds_payload_hash: str | None
    p_model: Decimal
    p_lo: Decimal | None
    p_hi: Decimal | None
    p_market_fair: Decimal
    consensus_method: str | None
    consensus_as_of: datetime | None
    fair_odds: Decimal = Field(description="1 / p_model: the price at which the model would break even.")
    probability_edge: Decimal = Field(description="p_model - p_market_fair.")
    price_edge: Decimal = Field(description="odds / market fair odds - 1.")
    ev: Decimal = Field(description="p_model * odds - 1, per unit staked.")
    ev_at_lower_bound: Decimal | None
    kelly_fraction: Decimal = Field(description="Reported only. Stakes are flat.")
    stake_units: Decimal
    stake_policy: str
    decision_rule_version: str
    code_version: str
    qualification: dict[str, Any]
    result_status: str
    profit_units: Decimal | None
    settled_at: datetime | None
    settlement_basis: str | None
    review_reason: str | None
    created_at: datetime
    events: list[PickEvent]


class CandidateRow(Contract):
    id: int
    fixture_id: int
    fixture: str
    market_key: str
    selection: str
    line: Decimal
    model: str
    bookmaker: str | None
    market_odds: Decimal | None
    p_model: Decimal
    p_market_fair: Decimal | None
    probability_edge: Decimal | None
    ev: Decimal | None
    decision: Literal["selected", "rejected"]
    rejection_reason: str | None
    decision_rule_version: str | None
    odds_captured_at: datetime | None
    evaluated_at: datetime


class Lifecycle(Contract):
    candidates: int
    rejected: int
    shadow: int
    qualified: int
    published: int
    settled: int


class PicksOverview(Contract):
    lifecycle: Lifecycle
    rule: dict[str, Any]
    rejection_reasons: dict[str, int]
    publishing_enabled: Literal[False] = False
    candidates_by_decision: dict[str, int]
    picks_by_mode: dict[str, int]
    picks: Section[list[PickRow]]
    recent_candidates: Section[list[CandidateRow]]


class PerformanceSlice(Contract):
    """Settled shadow bets in one group (a market, a model, a month...)."""

    dimension: Literal["market", "model", "rule", "month", "odds_band"]
    key: str
    settled: int
    staked_units: Decimal | None
    profit_units: Decimal | None
    roi_pct: Decimal | None
    roi_ci95_pct: Decimal | None = Field(
        description="Half-width of a normal 95% interval on the ROI, clustered by fixture (the spread of per-match "
                    "profits): several picks on one match win or lose together. Null below 20 matches.")
    fixtures: int | None = Field(default=None, description="Distinct matches behind the bets: the independent sample.")
    hit_rate: Decimal | None
    mean_odds: Decimal | None
    expected_profit_units: Decimal | None = Field(
        description="What the model's own EV said these bets would make. Far above the real profit means the "
                    "model's edge was not real.")


class PerformanceSummary(Contract):
    settled: int
    pending: int
    staked_units: Decimal | None
    profit_units: Decimal | None
    roi_pct: Decimal | None
    hit_rate: Decimal | None
    note: str
    slices: list[PerformanceSlice] = Field(default_factory=list)
    roi_ci95_pct: Decimal | None = Field(default=None, description="Clustered by fixture, as in the slices.")
    fixtures: int | None = Field(default=None, description="Distinct matches behind the settled bets.")
