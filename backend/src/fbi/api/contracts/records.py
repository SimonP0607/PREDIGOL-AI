"""The product's records: the day's picks and parlays as persisted, a user's own picks and
parlays, and the user's history (DAILY_PICKS_SPEC, PARLAY_ENGINE_SPEC, USER_PICK_HISTORY_SPEC)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from fbi.api.contracts.common import Contract, MatchPhase, StatusReason, UserStatus
from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.contracts.reading import ReadingFact

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


class AiLatest(Contract):
    """The AI's NEWEST combined review of a selection before its kick-off - which can differ from the one frozen
    when the selection entered the set (``ai``): the review keeps working until the match starts. Unless the owner
    previews (or the review was enforced) only that it was reviewed is said."""

    reviewed_at: datetime
    decision: Literal["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"] | None = None
    confidence: Decimal | None = None
    reason: str | None = None
    by_llm: bool = False


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


CorrectionCause = Literal["result_corrected", "status_changed", "audit"]


class ResultCorrection(Contract):
    """A settled record whose result changed afterwards (plan F0, defect 5): the record shows the result it has now,
    this is one it had. A leg's correction carries the leg's number; a record's own - a pick's, a parlay's - does not.

    What the person is told is the cause as a code and the words they translate - never the trail's own reason, which
    names internal revisions and whoever ran a manual pass."""

    at: datetime = Field(description="When the record was settled again.")
    leg_no: int | None = Field(default=None, description="The leg, for a correction of one leg of a parlay.")
    from_status: ResultStatus | ParlayStatus
    to_status: ResultStatus | ParlayStatus
    from_profit: Decimal | None = None
    to_profit: Decimal | None = None
    cause: CorrectionCause = Field(description=(
        "result_corrected: the data provider corrected the match's result after full time. status_changed: the match's "
        "status moved (a result confirmed, a match annulled). audit: a review found the stored result was not the one "
        "the match's result gives - and no correction of the match was recorded."))


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
    ai_latest: AiLatest | None = None
    corrections: list[ResultCorrection] = Field(default_factory=list, description=(
        "Settled again after the provider corrected the match; oldest first. Empty: never."))
    user_status: UserStatus = Field(description=(
        "What a reader is shown (plan UX, B3; fbi/picks/user_status.py, the one table), as the pick stood when it entered the "
        "set: its price then passed the value rule, and the AI review frozen with it counts only if it was applied then. "
        "EVALUATION for the evaluation set (the owner's preview). A reader is shown the items that entered RECOMMENDED only "
        "(UX-002, «solo verde»)."))
    status_reason: StatusReason
    context_pending: bool = Field(description="RECOMMENDED by the value rule alone: «revisión de contexto aún no "
                                              "aplicada» is said beside it.")


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
    ai_latest: AiLatest | None = None
    why: ReadingFact | None = Field(default=None, description=(
        "One line of why this leg: a fact of the match's reading that stands behind the side the leg backs (a run without "
        "defeat, a key player out for the other side, a run without a win of the other, what the side plays for), as the reading "
        "itself words it. None when the match has no such fact, the leg backs no side or readers do not see the reading: "
        "nothing is made up. Known before kick-off (plan de Inicio, 2.4b)."))


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
    corrections: list[ResultCorrection] = Field(default_factory=list, description=(
        "The parlay's own and its legs' (with ``leg_no``); oldest first. Empty: never corrected."))


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
    previous_day_open: bool = Field(default=False, description=(
        "The set of the day before (same source, what a reader of it is shown) still has a pick to finish or settle: only "
        "then does Inicio ask for that day (plan Inicio, P4)."))


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
    corrections: list[ResultCorrection] = Field(default_factory=list, description=(
        "Settled again after the provider corrected the match; oldest first. Empty: never."))
    p_close: Decimal | None = Field(default=None, description=(
        "Once the match started: the de-vigged (Shin) consensus probability of the selection at the last capture before "
        "kick-off - the closing reference (plan UX, B5; clv-v1). Null before kick-off or without a capture."))
    line_value: Decimal | None = Field(default=None, description=(
        "clv-v1 (fbi.market.closing_value): the price the reader counts - user_odds when they gave it, else odds - at "
        "p_close, odds x p_close - 1, a share. Null without a price or a closing reference."))


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
    corrections: list[ResultCorrection] = Field(default_factory=list, description=(
        "The parlay's own and its legs' (with ``leg_no``); oldest first. Empty: never corrected."))


class HistoryGroup(Contract):
    """A group of records counted with the sample rule of Mis picks (plan UX, B5, section 30; «Cómo le va a PrediGol»'s): below
    min_sample settled records only the counts - hit rate, units and ROI are null - and below `conclusive` the page says the
    sample does not allow a conclusion yet."""

    total: int
    pending: int
    won: int
    lost: int
    push: int
    void: int
    hit_rate: float | None = Field(description="Won over won and lost; null below min_sample settled records.")
    staked_units: Decimal = Field(description="Settled records with a stake - the n of the sample.")
    profit_units: Decimal | None = Field(description="The profit at one unit per record; null below min_sample.")
    roi: float | None = Field(description="Profit over the units staked; null below min_sample.")
    margin: float | None = Field(default=None, description=(
        "Plus or minus one standard error of the ROI, a share: 1 / sqrt(staked) (0.20 with 25, 0.10 with 100); null below "
        "min_sample."))
    conclusive: bool = Field(default=False, description="False below `conclusive` settled records (100).")


class History(Contract):
    period: Literal["today", "7d", "30d", "all"]
    timezone: str
    since: datetime
    until: datetime
    evaluation_mode: bool
    groups: dict[str, HistoryGroup] = Field(description="predigol_picks, my_picks, predigol_parlays, my_parlays")
    min_sample: int = Field(default=25, description="Settled records from which hit rate, units, ROI and margin are shown.")
    conclusive: int = Field(default=100, description="Settled records from which the sample allows a conclusion.")
