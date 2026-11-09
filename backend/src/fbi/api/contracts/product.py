"""The product's own answers: home, qualified picks, parlays, best prices.

These are built for the screens a signed-in user sees, so a page asks one endpoint
instead of stitching twenty. Where a block has nothing to show, its ``reason`` is a
machine-readable code (``no_qualified_picks``, ``no_valid_parlay``...) that the
frontend translates - never a sentence in one language.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.center import LiveMatch
from fbi.api.contracts.common import Contract, MatchPhase, StatusReason, UserStatus
from fbi.api.envelope import Section

Source = Literal["qualified", "shadow_preview"]
Freshness = Literal["fresh", "aging", "stale", "none"]
DecisionState = Literal["RECOMMENDED", "CAUTION", "WATCH", "ABSTAIN", "REJECTED"]
DecisionSource = Literal["legacy", "intelligence"]


class TeamBadge(Contract):
    id: int
    name: str
    logo_url: str | None


class CompetitionBadge(Contract):
    id: int
    name: str
    country: str | None
    logo_url: str | None
    flag_url: str | None


class PickDecision(Contract):
    """What PrediGol Intelligence decided about this selection (``decision-v1``, its newest row; ``fbi.intel.state_v2`` words it).

    Present only while the board reads Intelligence (``FBI_PICKS_SOURCE=intelligence``, plan PICKS F3). The card's ``p_model`` is
    the calibrated probability then, and its ``ev`` and ``edge`` are computed with it; the pick engine's raw one is ``p_raw`` here
    («sin calibrar»)."""

    state: DecisionState = Field(description="state-v2 of the decision: RECOMMENDED, CAUTION, WATCH (waiting for something that "
                                             "clears before kick-off), ABSTAIN (no opinion today) or REJECTED.")
    reason: str = Field(description="The reason code state-v2 gives (``approved``, ``risk``, ``price_stale``, ``edge_not_validated``...).")
    known_at: datetime
    checkpoint: str
    p_calibrated: Decimal | None = Field(description="Calibrated probability (cal-logit2-v1); null while the market has no champion calibrator.")
    p_raw: Decimal = Field(description="The model's probability before calibrating: what the board showed before F3, kept as «sin calibrar».")
    ev_calibrated: Decimal | None
    edge_calibrated: Decimal | None
    odds: Decimal | None = Field(description="The price Intelligence judged at known_at.")
    price_at: datetime | None


class PickCard(Contract):
    """A pick as the product shows it, re-priced at the best price available now."""

    pick_id: int
    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    market_key: str
    selection: str
    line: Decimal
    status: Literal["shadow", "qualified", "published"]
    model: str
    best_odds: Decimal | None = Field(description="Best price available now (latest de-vigged consensus).")
    bookmaker: str | None
    price_at: datetime | None
    p_model: Decimal = Field(description="Model probability, conditional on the bet being settled.")
    p_market: Decimal | None = Field(description="De-vigged market consensus probability (Shin).")
    fair_odds: Decimal | None = Field(description="1 / p_market: the market's fair price.")
    edge: Decimal | None = Field(description="p_model - p_market.")
    ev: Decimal | None = Field(description="Expected value per unit at best_odds. Null without a price.")
    freshness: Freshness
    value_now: bool = Field(description="Passes the value gate at this moment.")
    value_reason: str | None = Field(description="The gate it fails, as a code, when value_now is false.")
    user_status: UserStatus = Field(description=(
        "The pick's visible state (plan UX, B3; fbi/picks/user_status.py, the one table): RECOMMENDED, CAUTION (the applied AI "
        "review downgrades it), NOT_RECOMMENDED (no value at the best price now, or the applied review rejects it) or "
        "EVALUATION (a shadow pick). A reader is shown RECOMMENDED cards only (UX-002, «solo verde»); the others reach the "
        "owner's preview alone, labelled."))
    status_reason: StatusReason = Field(description="Why, as a code: approved, value, not_reviewed, downgraded, rejected, "
                                                    "no_value_now or evaluation.")
    context_pending: bool = Field(description="RECOMMENDED by the value rule alone: «revisión de contexto aún no aplicada» "
                                              "is said beside it (the AI's review does not act on picks, or has no "
                                              "decision on this one).")
    decision: PickDecision | None = Field(default=None, description=(
        "PrediGol Intelligence's decision on this selection, when the board reads it (``decision_source`` of the board is "
        "``intelligence``, plan PICKS F3); null otherwise, and null when Intelligence has not decided this selection."))


class StartedPick(Contract):
    """A pre-match pick whose match has kicked off: the record as it was taken before kick-off, never re-priced.

    One per selection: the last pick made before kick-off (``evaluations`` says how many there were). What
    happened since - the state, the minute, the score, the result, the line value - is shown beside it, never
    mixed into it."""

    pick_id: int
    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    market_key: str
    selection: str
    line: Decimal
    status: Literal["shadow", "qualified", "published"] = Field(description="What it was before kick-off.")
    model: str
    created_at: datetime = Field(description="When the pick was made.")
    taken_at: datetime = Field(description="When the price was captured.")
    odds_taken: Decimal
    bookmaker: str | None
    p_model: Decimal
    p_market: Decimal = Field(description="De-vigged market probability when it was taken.")
    fair_odds: Decimal
    edge: Decimal
    ev: Decimal = Field(description="Expected value per unit at the price taken.")
    evaluations: int = Field(description="Picks made on this selection before kick-off; this is the last.")
    phase: MatchPhase
    status_short: str | None
    live_minute: int | None = None
    live_extra: int | None = None
    live_home: int | None = None
    live_away: int | None = None
    score_home: int | None = Field(default=None, description="The 90-minute score, once the match has one.")
    score_away: int | None = None
    result_status: str | None = Field(default=None, description="win, loss, push, void, half_win, half_loss, "
                                                                "pending, or None before the match ends.")
    profit_units: Decimal | None = None
    settled_at: datetime | None = None
    review_reason: str | None = Field(default=None, description="Why it waits for a human, if it does.")
    near_close_odds: Decimal | None = Field(default=None, description="The same bookmaker's last pre-match price.")
    line_value: Decimal | None = Field(default=None, description="odds_taken / near_close_odds - 1: value against "
                                                                 "a near-close price, not validated as the close.")
    user_status: UserStatus = Field(default="EVALUATION", description=(
        "The state a reader is shown for this pick (the one table, ``fbi/picks/user_status.py``), read as it was taken: a reader "
        "is shown it only while RECOMMENDED (plan PICKS, L1: «solo verde» holds after kick-off too). Merged with Intelligence's "
        "decision while ``FBI_PICKS_SOURCE=intelligence``."))
    status_reason: StatusReason = Field(default="evaluation", description="Why ``user_status`` is the one it is.")
    context_pending: bool = Field(default=False, description="The review of context was not yet applied when it was taken.")
    decision: PickDecision | None = Field(default=None, description=(
        "PrediGol Intelligence's last decision before kick-off on this selection, while the board reads it "
        "(``FBI_PICKS_SOURCE=intelligence``); null otherwise. ``p_model``, ``edge`` and ``ev`` are then computed with its "
        "calibrated probability at the price taken."))


class PicksBoard(Contract):
    source: Source
    top: list[PickCard] = Field(description="Up to five picks with value now, kicking off in the next 24 hours.")
    picks: list[PickCard] = Field(description="Every pick in the window, best value first.")
    competitions: list[CompetitionBadge]
    markets: list[str]
    window_hours: int
    reason: str | None = Field(description=(
        "Why there is nothing to show, as a code: no_qualified_picks, no_shadow_picks, no_picks_match_filters, no_value_now "
        "or, when no pick of the window is recommended now and some were downgraded or rejected by the applied AI review, "
        "none_recommended (plan UX, B3)."))
    withheld: int = Field(default=0, description=(
        "Published picks of the window a reader is not shown now (plan UX, B3; UX-002, «solo verde»): every one that is not "
        "RECOMMENDED - without value at the best price now, or downgraded or rejected by the applied AI review -, in a list "
        "and on one match (``fixture_id``) alike. Always 0 in the owner's preview, which shows every pick."))
    started: list[StartedPick] = Field(
        default_factory=list,
        description="Pre-match picks whose match has kicked off (today's, or every one of ``fixture_id``): they "
                    "stay, with the price taken, the state of the match and the result.")
    decision_source: DecisionSource = Field(default="legacy", description=(
        "Where the cards' numbers and states come from: ``legacy`` (the pick engine's own, raw probability) or "
        "``intelligence`` (PrediGol Intelligence's newest decision: calibrated probability, EV and edge, and its state; "
        "``FBI_PICKS_SOURCE``, plan PICKS F3)."))


class ParlayLeg(Contract):
    pick_id: int
    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    market_key: str
    selection: str
    line: Decimal
    odds: Decimal
    bookmaker: str | None
    price_at: datetime
    p_model: Decimal
    p_market: Decimal
    p_win: Decimal = Field(description="Unconditional probability this leg wins (pushes excluded).")
    edge: Decimal
    ev: Decimal


class Parlay(Contract):
    kind: Literal["daily", "multiday"]
    status: Literal["ok", "no_valid_parlay"]
    source: Source
    legs: list[ParlayLeg]
    required_legs: int
    max_legs: int
    eligible_legs: int = Field(description="Selections that passed the value gate in the window.")
    window_from: datetime
    window_to: datetime
    combined_odds: Decimal | None
    probability_all_win: Decimal | None = Field(
        description="Product of the legs' win probabilities - legs are distinct matches of distinct teams. "
                    "Null when that independence does not hold.")
    expected_value: Decimal | None = Field(description="Per unit: product of (1 + leg EV) minus one.")
    risk: Literal["moderate", "high", "very_high"] | None
    independence: Literal["distinct_fixtures_and_teams", "not_independent"] | None
    prices_as_of: datetime | None = Field(description="The oldest price among the legs.")
    rejections: dict[str, int] = Field(description="Selections left out, by the rule they failed.")
    generated_at: datetime


class BestPrice(Contract):
    selection: str
    best_odds: Decimal
    bookmaker: str | None
    p_fair: Decimal
    fair_odds: Decimal
    price_edge: Decimal = Field(description="best_odds * p_fair - 1: how far the best price sits above fair.")
    outlier: bool = Field(default=False, description="More than 25% above fair: very likely one book's stale or "
                                                     "mistaken quote. Shown, flagged, never highlighted.")
    n_bookmakers: int
    as_of: datetime


class BestMarket(Contract):
    market_key: str
    line: Decimal = Field(description=(
        "The line of the market's prices. An Asian handicap's is the HOME side's handicap h: its two prices are one bet, "
        "Home at h and Away at -h (each side is quoted at its own line)."))
    selections: list[BestPrice]


class BestOddsFixture(Contract):
    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    markets: list[BestMarket]
    as_of: datetime


class BestHighlight(Contract):
    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    market_key: str
    line: Decimal = Field(description=(
        "The highlighted selection's own line: an Asian handicap's away side at -h, the opposite of its market's line."))
    price: BestPrice


class BestOddsBoard(Contract):
    window_hours: int
    markets: list[str]
    fixtures: list[BestOddsFixture]
    highlights: list[BestHighlight] = Field(description="Best prices furthest above the market's fair price.")
    value: list[PickCard] = Field(description="Picks with value now (qualified only, unless a shadow preview).")
    source: Source


class DataFreshness(Contract):
    live_at: datetime | None


class HomeResult(Contract):
    """A match that ended in the last 24 hours (plan de Inicio, 3.1): who, where, the score and how it ended."""

    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    status: Literal["FT", "AET", "PEN"] = Field(description="Over after 90 minutes, after extra time or after the shoot-out.")
    goals_home: int
    goals_away: int
    pens_home: int | None = Field(default=None, description="The shoot-out's score, when there was one.")
    pens_away: int | None = None


class HomeReason(Contract):
    """Why a match is on Inicio's «Partidos relevantes» or «Qué se juega» (plan de Inicio, 3.1b): a code and the values its sentence
    fills in, both chosen on the server from facts PrediGol Intelligence stored or from the match's own score - the web only
    words it. ``final`` (a final), ``tie`` (a tie's second leg: the aggregate now), ``first_leg`` (a second leg still to be
    played: how the first ended), ``stakes`` (a side fights for ``pressure``: title, europe, relegation or promotion; live,
    with ``state`` - ahead, level or behind) and ``comeback`` (a side was behind and is now level or ahead)."""

    code: Literal["final", "tie", "first_leg", "stakes", "comeback"]
    params: dict[str, str | int | float | bool | None]


class HomeRelevant(Contract):
    """A match in play that has a reason to be looked at now: the live match and why (one or two reasons, the strongest first)."""

    match: LiveMatch
    reasons: list[HomeReason]


class HomeAtStake(Contract):
    """A match still to be played in the next 36 hours with something at stake: one reason, one sentence."""

    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    reason: HomeReason


class Home(Contract):
    source: Source
    data_freshness: DataFreshness
    relevant: Section[list[HomeRelevant]] = Field(description=(
        "The matches in play that have a reason (a final, a second leg and how the tie goes, a fight for the title, Europe, "
        "relegation or promotion, a comeback), by competition priority, four at most (``home_board.relevant``). A match "
        "with no reason is not here."))
    at_stake: Section[list[HomeAtStake]] = Field(description=(
        "The matches not yet started in the next 36 hours with something at stake, by competition priority, four at most "
        "(``home_board.at_stake``)."))
    live: Section[list[LiveMatch]] = Field(description=(
        "What else is in play: the matches of ``relevant`` are not repeated here; six at most."))
    results: Section[list[HomeResult]] = Field(description=(
        "The matches that ended in the last 24 hours, the most recent first, six at most (``home_board.results``)."))
