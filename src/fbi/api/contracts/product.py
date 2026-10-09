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
from fbi.api.contracts.common import Contract, MatchPhase
from fbi.api.envelope import Section

Source = Literal["qualified", "shadow_preview"]
Freshness = Literal["fresh", "aging", "stale", "none"]


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


class PicksBoard(Contract):
    source: Source
    top: list[PickCard] = Field(description="Up to five picks with value now, kicking off in the next 24 hours.")
    picks: list[PickCard] = Field(description="Every pick in the window, best value first.")
    competitions: list[CompetitionBadge]
    markets: list[str]
    window_hours: int
    reason: str | None = Field(description="Why there is nothing to show, as a code.")
    started: list[StartedPick] = Field(
        default_factory=list,
        description="Pre-match picks whose match has kicked off (today's, or every one of ``fixture_id``): they "
                    "stay, with the price taken, the state of the match and the result.")


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
    line: Decimal
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
    line: Decimal
    price: BestPrice


class BestOddsBoard(Contract):
    window_hours: int
    markets: list[str]
    fixtures: list[BestOddsFixture]
    highlights: list[BestHighlight] = Field(description="Best prices furthest above the market's fair price.")
    value: list[PickCard] = Field(description="Picks with value now (qualified only, unless a shadow preview).")
    source: Source


class UpcomingMatch(Contract):
    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    bookmakers: int


class DataFreshness(Contract):
    odds_at: datetime | None
    live_at: datetime | None


class Home(Contract):
    source: Source
    data_freshness: DataFreshness
    top_picks: Section[list[PickCard]]
    daily_parlay: Parlay
    multiday_parlay: Parlay
    live: Section[list[LiveMatch]]
    best_prices: Section[list[BestHighlight]]
    upcoming: Section[list[UpcomingMatch]]
