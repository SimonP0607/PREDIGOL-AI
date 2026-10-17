"""The minimal domain entities. Contracts first; behaviour comes later.

Every entity that exists at a provider carries a ``ProviderRef`` separately
from its internal id. Every number that means something is a value object
from this package, never a bare float.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from fbi.core.errors import DomainError, TemporalIntegrityError
from fbi.domain.identity import (
    BookmakerId,
    CalibratorId,
    CandidateId,
    CompetitionId,
    FixtureId,
    ModelVersionId,
    PickId,
    PredictionId,
    ProviderRef,
    RunId,
    SeasonId,
    TeamId,
    VenueId,
)
from fbi.domain.market import MarketType, Selection
from fbi.domain.market_probability import FairProbability
from fbi.domain.odds import DecimalOdds
from fbi.domain.probability import Probability
from fbi.domain.units import ProfitUnits, StakeUnits
from fbi.domain.value import Edge, ExpectedValue, PriceEdge


class EntityScope(StrEnum):
    CLUB = "club"
    NATIONAL_TEAM = "national_team"


class CompetitionKind(StrEnum):
    DOMESTIC_LEAGUE = "domestic_league"
    DOMESTIC_CUP = "domestic_cup"
    CONTINENTAL = "continental"
    INTERNATIONAL = "international"


class CompetitionFormat(StrEnum):
    LEAGUE = "league"
    CUP = "cup"
    SUPERCUP = "supercup"
    FRIENDLY = "friendly"


@dataclass(frozen=True, slots=True)
class Competition:
    id: CompetitionId
    provider_ref: ProviderRef
    name: str
    country: str | None
    format: CompetitionFormat
    entity_scope: EntityScope
    kind: CompetitionKind
    elo_weight: float
    neutral_venue: bool
    tier: int | None
    is_tracked: bool

    def __post_init__(self) -> None:
        if not 0.0 <= self.elo_weight <= 1.0:
            raise DomainError(f"elo_weight must be in [0, 1], got {self.elo_weight}")


@dataclass(frozen=True, slots=True)
class Season:
    id: SeasonId
    competition_id: CompetitionId
    year: int
    start_date: date | None
    end_date: date | None
    is_current: bool


@dataclass(frozen=True, slots=True)
class Team:
    id: TeamId
    provider_ref: ProviderRef
    name: str
    short_name: str | None
    country: str | None
    is_national: bool | None
    venue_id: VenueId | None


class FixtureStatus(StrEnum):
    """Matches core.fixtures.status_group."""

    SCHEDULED = "scheduled"
    LIVE = "live"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    POSTPONED = "postponed"


@dataclass(frozen=True, slots=True)
class Fixture:
    id: FixtureId
    provider_ref: ProviderRef
    season_id: SeasonId
    home_team_id: TeamId
    away_team_id: TeamId
    kickoff_at: datetime
    status: FixtureStatus
    status_short: str
    round: str | None
    venue_id: VenueId | None
    is_neutral: bool

    def __post_init__(self) -> None:
        if self.home_team_id == self.away_team_id:
            raise DomainError("a team cannot play itself")
        if self.kickoff_at.tzinfo is None:
            raise DomainError("kickoff_at must be timezone-aware")

    def minutes_to_kickoff(self, at: datetime) -> int:
        return max(0, int((self.kickoff_at - at).total_seconds() // 60))


@dataclass(frozen=True, slots=True)
class Bookmaker:
    id: BookmakerId
    provider_ref: ProviderRef
    name: str
    is_sharp: bool
    consensus_weight: float
    is_active: bool


@dataclass(frozen=True, slots=True)
class Market:
    type: MarketType
    name: str
    provider_bet_id: int | None
    is_tracked: bool


class OddsSource(StrEnum):
    PREMATCH = "prematch"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class OddsSnapshot:
    """One price at one instant from one bookmaker.

    ``captured_at`` is part of the identity: two snapshots of the same
    selection at different instants are two facts, and both are kept.
    """

    fixture_id: FixtureId
    bookmaker_id: BookmakerId
    selection: Selection
    odds: DecimalOdds
    captured_at: datetime
    minutes_to_kickoff: int
    source: OddsSource
    payload_hash: str

    def __post_init__(self) -> None:
        if self.captured_at.tzinfo is None:
            raise DomainError("captured_at must be timezone-aware")
        if self.minutes_to_kickoff < 0:
            raise DomainError("a snapshot cannot be captured after kick-off and still be pre-match")
        if not self.payload_hash:
            raise DomainError("a snapshot without its raw payload hash is untraceable")


@dataclass(frozen=True, slots=True)
class Prediction:
    """What a model version said about one selection, at one data cutoff.

    ``p_raw`` and ``p_calibrated`` are separate on purpose: a calibrator's
    effect must be visible, never folded into a single number the way the
    legacy folded its context adjustment into ``model_probability``.
    """

    id: PredictionId
    fixture_id: FixtureId
    model_version_id: ModelVersionId
    calibrator_id: CalibratorId | None
    selection: Selection
    p_raw: Probability
    p_calibrated: Probability
    p_lower: Probability
    p_upper: Probability
    feature_set_hash: str
    data_cutoff: datetime

    def __post_init__(self) -> None:
        if not self.p_lower <= self.p_calibrated <= self.p_upper:
            raise DomainError("the interval must contain the calibrated probability")
        if self.data_cutoff.tzinfo is None:
            raise DomainError("data_cutoff must be timezone-aware")


class Decision(StrEnum):
    SELECTED = "selected"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PickCandidate:
    """Every evaluated opportunity, chosen or not, with the reason.

    A selected candidate always has a price. A rejected one always has a
    reason. The schema enforces both with CHECK constraints; the domain
    enforces them first so the error is raised where it was caused.
    """

    id: CandidateId
    run_id: RunId
    fixture_id: FixtureId
    prediction_id: PredictionId
    selection: Selection
    decision: Decision
    p_calibrated: Probability
    market_fair: FairProbability | None = None
    bookmaker_id: BookmakerId | None = None
    market_odds: DecimalOdds | None = None
    edge: Edge | None = None
    price_edge: PriceEdge | None = None
    ev: ExpectedValue | None = None
    ev_adjusted: ExpectedValue | None = None
    rejection_reason: str | None = None

    def __post_init__(self) -> None:
        if self.decision is Decision.SELECTED and (self.market_odds is None or self.bookmaker_id is None):
            raise DomainError("a selected candidate without a price cannot be evaluated - ever")
        if self.decision is Decision.REJECTED and not self.rejection_reason:
            raise DomainError("a rejected candidate must say why")


class PickMode(StrEnum):
    SHADOW = "shadow"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class PublishedPick:
    """A selected candidate that was recorded as a pick, with everything
    needed to reproduce the decision six months later."""

    id: PickId
    candidate_id: CandidateId
    fixture_id: FixtureId
    selection: Selection
    model_version_id: ModelVersionId
    calibrator_id: CalibratorId
    feature_set_hash: str
    data_cutoff: datetime
    decision_rule_version: str
    code_version: str
    bookmaker_id: BookmakerId
    market_odds: DecimalOdds
    odds_captured_at: datetime
    p_model: Probability
    p_calibrated: Probability
    p_lower: Probability
    p_upper: Probability
    market_fair: FairProbability
    edge: Edge
    price_edge: PriceEdge
    ev: ExpectedValue
    ev_adjusted: ExpectedValue
    kelly_fraction: float
    stake: StakeUnits
    mode: PickMode = PickMode.SHADOW
    published_at: datetime | None = None
    selection_reason: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.data_cutoff > self.odds_captured_at:
            raise TemporalIntegrityError(
                "the decision would use information that appeared after the price it was taken at"
            )
        if not 0.0 <= self.kelly_fraction <= 1.0:
            raise DomainError("kelly fraction is a fraction of bankroll in [0, 1]")


class SettlementStatus(StrEnum):
    """All seven. Three (win/loss/void) cannot settle a half-line."""

    PENDING = "pending"
    WIN = "win"
    LOSS = "loss"
    PUSH = "push"
    HALF_WIN = "half_win"
    HALF_LOSS = "half_loss"
    VOID = "void"


@dataclass(frozen=True, slots=True)
class Settlement:
    pick_id: PickId
    status: SettlementStatus
    profit: ProfitUnits | None
    settled_at: datetime | None
    settled_by: str | None

    def __post_init__(self) -> None:
        if self.status is not SettlementStatus.PENDING and (self.profit is None or self.settled_at is None):
            raise DomainError("a settled pick records its profit and when it was settled")
        if self.status is SettlementStatus.PENDING and (self.profit is not None or self.settled_at is not None):
            raise DomainError("a pending pick has no profit yet")


def settle(status: SettlementStatus, stake: StakeUnits, odds: DecimalOdds) -> ProfitUnits:
    """Profit for a settled outcome. The only place the seven states become money."""
    payout = stake.value * odds.payout_per_unit()
    if status is SettlementStatus.WIN:
        return ProfitUnits(payout)
    if status is SettlementStatus.HALF_WIN:
        return ProfitUnits(payout / 2)
    if status is SettlementStatus.LOSS:
        return ProfitUnits(-stake.value)
    if status is SettlementStatus.HALF_LOSS:
        return ProfitUnits(-stake.value / 2)
    if status in (SettlementStatus.PUSH, SettlementStatus.VOID):
        return ProfitUnits.zero()
    raise DomainError("a pending pick has no profit")
