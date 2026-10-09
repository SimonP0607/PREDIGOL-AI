"""The product's records: the day's picks and parlays as persisted, a user's own picks and
parlays, and the user's history (DAILY_PICKS_SPEC, PARLAY_ENGINE_SPEC, USER_PICK_HISTORY_SPEC)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from fbi.api.contracts.common import Contract, MatchPhase
from fbi.api.contracts.product import CompetitionBadge, TeamBadge

ResultStatus = Literal["PENDING", "WIN", "LOSS", "PUSH", "VOID", "HALF_WIN", "HALF_LOSS"]
ParlayStatus = Literal["BUILDING", "READY", "ACTIVE", "WON", "LOST", "VOID", "PARTIAL_VOID"]
ParlayProgress = Literal["OPEN", "PARTIAL_WON", "PARTIAL_LOST", "WON", "LOST", "VOID"]
SetSource = Literal["qualified", "evaluation"]


class ItemAi(Contract):
    """The AI decision layer's review of a selection, frozen when the selection entered the set or parlay.
    In shadow mode it is shown and recorded but changed nothing; only with enforcement on (the owner's switch AND
    a passed shadow gate) can a REJECT keep a selection out."""

    decision: Literal["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"] | None = Field(
        description="Null when no review existed when the selection was frozen.")
    mode: Literal["off", "shadow", "enforce"]
    enforced: bool
    review_id: int | None = None
    confidence: Decimal | None = None
    reason: str | None = None
    by_llm: bool = Field(default=False, description="A language model took part; otherwise the rules reviewer alone.")
    positives: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class MatchRef(Contract):
    fixture_id: int
    kickoff_at: datetime
    status_group: str
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    score_home: int | None = Field(default=None, description="Regulation score, once the match has one.")
    score_away: int | None = None
    status_short: str | None = Field(default=None, description="The provider's code (NS, 1H, HT, FT, PST...).")
    phase: MatchPhase = Field(default="unknown", description="What the card shows (fbi.core.match_state).")
    live_minute: int | None = Field(default=None, description="The minute, while in play.")
    live_extra: int | None = None
    live_home: int | None = Field(default=None, description="The score now, while in play (extra time included).")
    live_away: int | None = None
    live_at: datetime | None = Field(default=None, description="When that state was observed.")


class DailyItem(Contract):
    rank: int
    pick_id: int
    match: MatchRef
    market_key: str
    selection: str
    line: Decimal
    stage: Literal["T-24h", "T-12h", "T-6h", "T-3h"]
    selected_at: datetime
    odds: Decimal = Field(description="The price frozen when the pick entered the set.")
    bookmaker: str | None
    price_at: datetime
    p_model: Decimal
    p_low: Decimal
    p_market: Decimal
    ev: Decimal
    model: str | None
    status: ResultStatus
    profit_units: Decimal | None
    settled_at: datetime | None
    ai: ItemAi | None = None


class DailySet(Contract):
    id: int
    day: date
    timezone: str
    source: SetSource
    rule_version: str
    status: Literal["BUILDING", "COMPLETE", "SETTLED"]
    items: list[DailyItem]


class ParlayRecordLeg(Contract):
    leg_no: int
    pick_id: int
    match: MatchRef
    market_key: str
    selection: str
    line: Decimal
    odds: Decimal
    bookmaker: str | None
    p_model: Decimal
    p_low: Decimal
    p_market: Decimal
    ev: Decimal
    status: ResultStatus
    ai: ItemAi | None = None


class ParlayRecord(Contract):
    id: int
    kind: Literal["daily", "multiday"]
    day: date
    source: SetSource
    rule_version: str
    status: ParlayStatus
    min_legs: int
    max_legs: int
    window_from: datetime
    window_to: datetime
    combined_odds: Decimal | None
    p_all_low: Decimal | None = Field(description="Probability every leg wins, at each leg's pessimistic probability.")
    expected_log_growth: Decimal | None = Field(description="Of a 1% stake, at the pessimistic probabilities.")
    ready_at: datetime | None
    settled_at: datetime | None
    profit_units: Decimal | None
    legs: list[ParlayRecordLeg]
    progress: ParlayProgress = Field(default="OPEN", description="From the legs: OPEN (none settled), PARTIAL_WON "
                                     "(some won, none lost), PARTIAL_LOST (a leg lost, others still to play), WON, "
                                     "LOST, VOID. A parlay stays on the board until every leg is settled.")
    legs_pending: int = 0


class DailyBoard(Contract):
    day: date
    timezone: str
    source: SetSource
    evaluation_mode: bool = Field(description="True when this is the owner's preview of shadow picks: no model has "
                                              "beaten the market, nothing here is a recommendation.")
    set: DailySet | None
    daily_parlay: ParlayRecord | None
    multiday_parlay: ParlayRecord | None
    reason: str | None = None


class SavePickIn(BaseModel):
    fixture_id: int = Field(ge=1)
    market_key: Literal["1X2", "OU", "BTTS", "AH", "DC"]
    selection: str = Field(min_length=1, max_length=12)
    line: Decimal = Field(default=Decimal(0), ge=-20, le=20)
    pick_id: int | None = Field(default=None, ge=1)
    user_odds: Decimal | None = Field(default=None, gt=1, lt=1000)


class UserOddsIn(BaseModel):
    user_odds: Decimal | None = Field(default=None, gt=1, lt=1000,
                                      description="The price the user got at their own bookmaker; null clears it.")


class UserPick(Contract):
    id: int
    match: MatchRef
    market_key: str
    selection: str
    line: Decimal
    origin: Literal["predigol_pick", "market"]
    pick_id: int | None
    odds: Decimal | None
    bookmaker: str | None
    price_at: datetime | None
    user_odds: Decimal | None
    saved_at: datetime
    status: ResultStatus
    profit_units: Decimal | None
    settled_at: datetime | None
    snapshot: dict[str, Any]


class LegInBody(BaseModel):
    fixture_id: int = Field(ge=1)
    market_key: Literal["1X2", "OU", "BTTS", "AH", "DC"]
    selection: str = Field(min_length=1, max_length=12)
    line: Decimal = Field(default=Decimal(0), ge=-20, le=20)
    odds: Decimal | None = Field(default=None, gt=1, lt=1000)


class ParlayIn(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    legs: list[LegInBody] = Field(min_length=1, max_length=12)


class ParlayValidation(Contract):
    ok: bool
    errors: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    legs: list[dict[str, Any]]
    combined_odds: Decimal | None
    fair_probability: Decimal | None = Field(default=None, description="Every leg wins, by the de-vigged market.")
    model_probability: Decimal | None = Field(default=None, description="The same by PrediGol's model where it priced "
                                                                        "every leg: evaluation, not a recommendation.")
    expected_value: Decimal | None = Field(default=None, description="Combined odds x fair probability - 1.")
    risk: Literal["moderate", "high", "very_high"] | None = None
    n_legs: int = 0
    correlation: dict[str, Any] = Field(default_factory=dict)
    estimated_probability: Decimal | None = Field(default=None, description=(
        "Every leg wins by PrediGol's model (the market's where the model did not price a leg), adjusted for the "
        "measured dependence of legs of the same competition and day."))
    dependency: dict[str, Any] = Field(default_factory=dict, description="level low / medium / high and its reasons.")


class UserParlayLeg(Contract):
    leg_no: int
    match: MatchRef
    market_key: str
    selection: str
    line: Decimal
    odds: Decimal | None
    status: ResultStatus


class UserParlay(Contract):
    id: int
    name: str | None
    created_at: datetime
    combined_odds: Decimal | None
    status: ParlayStatus
    profit_units: Decimal | None
    settled_at: datetime | None
    warnings: list[dict[str, Any]]
    legs: list[UserParlayLeg]


class HistoryGroup(Contract):
    total: int
    pending: int
    won: int
    lost: int
    push: int
    void: int
    hit_rate: float | None
    staked_units: Decimal
    profit_units: Decimal
    roi: float | None


class History(Contract):
    period: Literal["today", "7d", "30d", "all"]
    timezone: str
    since: datetime
    until: datetime
    evaluation_mode: bool
    groups: dict[str, HistoryGroup] = Field(description="predigol_picks, my_picks, predigol_parlays, my_parlays")
