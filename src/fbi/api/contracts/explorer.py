"""Analytics page: competition, team, market, model and coverage views.

Every number is computed from stored rows at request time; nothing is
estimated, smoothed or filled. Where a sample is small the row carries its n
and a flag, and the UI says so rather than hiding it or inflating it.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from fbi.api.contracts.common import Contract, TeamRef

LOW_SAMPLE = 30
"""Below this many finished matches a rate is shown with its n and flagged."""


class CompetitionProfile(Contract):
    competition_id: int
    competition: str
    country: str | None
    competition_type: str
    season: int
    fixtures: int
    finished: int = Field(description="Fixtures with a recorded result.")
    low_sample: bool
    home_win: float | None = Field(description="Share of results won by the home side (regulation time).")
    draw: float | None
    away_win: float | None
    goals_per_match: float | None
    home_goals_per_match: float | None
    away_goals_per_match: float | None
    home_goal_difference: float | None = Field(description="Mean home-minus-away goals: the league's home edge.")
    btts: float | None
    over_2_5: float | None
    with_team_stats: int
    with_historical_odds: int
    with_odds_snapshots: int
    with_features: int = Field(description="Fixtures with a feature set of the current feature version.")
    with_predictions: int


class EloPoint(Contract):
    fixture_id: int
    kickoff_at: datetime
    competition: str
    opponent: TeamRef
    at_home: bool
    rating_before: float
    rating_after: float
    expected_score: float
    actual_score: float


class Split(Contract):
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points_per_match: float | None


class ProcessPoint(Contract):
    fixture_id: int
    kickoff_at: datetime
    source: str
    shots_for: int | None
    shots_against: int | None
    shots_on_target_for: int | None
    shots_on_target_against: int | None


class TeamFeatures(Contract):
    """The team as the models see it: its side of the newest feature set it appears in."""

    fixture_id: int
    feature_version: str
    data_cutoff: datetime
    side: str
    values: dict[str, float | None]


class TeamAnalytics(Contract):
    team: TeamRef
    splits: dict[str, Split] = Field(description="all, home, away - from recorded results only.")
    elo: list[EloPoint]
    process: list[ProcessPoint] = Field(description="Matches with team statistics, newest last.")
    features: TeamFeatures | None


class MarketBucket(Contract):
    lower: float
    upper: float
    n: int
    mean_probability: float | None
    observed_rate: float | None


class MarketSeason(Contract):
    competition_id: int
    competition: str
    season: int
    n: int
    closing_logloss: float | None
    pre_closing_logloss: float | None
    closing_improvement: float | None = Field(
        description="Pre-closing minus closing log loss: how much the last hours of trading added.")
    mean_overround_closing: float | None


class MarketAnalytics(Contract):
    baseline: str = Field(description="bookmaker/price kind/de-vig method of the calibration curve.")
    n_fixtures: int
    calibration: list[MarketBucket] = Field(description="One-vs-rest over home, draw and away, equal-width bins.")
    by_season: list[MarketSeason]
    source: str


class GateCheck(Contract):
    name: str
    passed: bool
    evidence: str


class ExperimentSummary(Contract):
    id: int
    uuid: str
    name: str
    model_family: str
    research_status: str
    gate_passed: bool
    gate: list[GateCheck]
    reproduced: bool
    reproduced_by: int | None = Field(description="The experiment that re-ran this one with identical predictions.")
    reproduction_of: int | None
    backtest_session_id: int | None
    code_version: str
    dataset_hash: str | None
    feature_version: str | None
    test_from: date | None
    test_to: date | None
    own_n: int | None
    own_logloss: float | None
    own_brier: float | None
    own_ece: float | None
    market_logloss_diff: float | None = Field(description="Model minus primary market baseline, common fixtures.")
    market_diff_low: float | None
    market_diff_high: float | None
    verdict: str | None
    evidence: str | None
    dm_p: float | None
    by_competition: list[dict[str, float | str]]
    finished_at: datetime | None


class CoverageCell(Contract):
    competition_id: int
    competition: str
    season: int
    fixtures: int
    finished: int
    with_result: int
    with_team_stats: int
    with_events: int
    with_lineups: int
    with_player_stats: int
    with_historical_odds: int
    with_odds_snapshots: int
    with_features: int
    with_predictions: int


class MigrationProgress(Contract):
    plan_id: int | None
    plan_name: str | None
    plan_created_at: datetime | None
    planned_requests: int | None
    units: dict[str, dict[str, int]] = Field(description="kind -> status -> units.")
    requests_spent: int
    rows_written: int
    by_tier: dict[str, dict[str, int]]
    last_activity_at: datetime | None
