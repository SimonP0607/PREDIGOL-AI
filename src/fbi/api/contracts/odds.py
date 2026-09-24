from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.matches import MarketQuote, MatchSummary
from fbi.api.envelope import Section


class OddsPoint(Contract):
    captured_at: datetime
    odds_decimal: Decimal
    minutes_to_ko: int
    source: Literal["prematch", "live"]
    payload_hash: str


class OddsSeries(Contract):
    """Every captured price of one selection at one bookmaker, oldest first."""

    bookmaker_id: int
    bookmaker: str
    market_key: str
    selection: str
    line: Decimal
    points: list[OddsPoint]


class NearCloseQuote(Contract):
    """The capture nearest to kick-off our cadence allowed.

    Not a closing line: ``is_validated_close`` stays false until a snapshot
    has been shown to BE the close, and the UI must not call it one before.
    """

    bookmaker: str
    market_key: str
    selection: str
    line: Decimal
    odds_decimal: Decimal
    captured_at: datetime
    minutes_to_ko: int
    source: Literal["prematch", "live"]
    is_validated_close: bool
    close_validation_method: str | None


class ConsensusQuote(Contract):
    market_key: str
    selection: str
    line: Decimal
    as_of: datetime
    devig_method: str
    p_fair: Decimal = Field(description="De-vigged market probability.")
    n_bookmakers: int
    overround: Decimal
    best_odds: Decimal
    best_bookmaker: str
    dispersion: Decimal | None


class HistoricalPrice(Contract):
    selection: str
    odds_decimal: Decimal
    raw_implied: Decimal = Field(description="1 / odds. Still contains the margin.")


class HistoricalBook(Contract):
    """One bookmaker's prices for one market as the SOURCE published them."""

    bookmaker_code: str
    price_kind: Literal["closing", "pre_closing"] = Field(
        description="The source's own label. No timestamp exists for either kind.")
    market_key: str
    line: Decimal
    overround: Decimal | None = Field(description="Sum of raw implied probabilities; null for a best-price composite.")
    is_composite: bool = Field(description="True for MAX (best price across books) and AVG (market average).")
    prices: list[HistoricalPrice]


class HistoricalFair(Contract):
    bookmaker_code: str
    price_kind: Literal["closing", "pre_closing"]
    devig_method: str
    p_home: Decimal
    p_draw: Decimal
    p_away: Decimal
    overround: Decimal


class HistoricalMarket(Contract):
    source: str
    note: str
    books: list[HistoricalBook]
    fair_1x2: list[HistoricalFair]


class FixtureOdds(Contract):
    match: MatchSummary
    board: Section[list[MarketQuote]]
    series: Section[list[OddsSeries]]
    near_close: Section[list[NearCloseQuote]]
    consensus: Section[list[ConsensusQuote]]
    historical: Section[HistoricalMarket | None] = Field(
        description="Prices from a second source (Football-Data.co.uk), kept apart from what we captured.")


class BookmakerMargin(Contract):
    bookmaker_code: str
    price_kind: str
    market_key: str
    fixtures: int
    mean_overround: Decimal
    median_overround: Decimal
    best_price_share: Decimal | None = Field(
        description="Share of 1X2 selections where this book had the highest price among named books "
                    "(a tie counts for every book sharing the top price).")


class MovementRow(Contract):
    """Pinnacle pre-closing -> closing, de-vigged (Shin), per competition and season."""

    competition_id: int
    competition: str
    season: int
    fixtures: int
    mean_abs_home_shift: Decimal = Field(description="Mean |p_home(closing) - p_home(pre-closing)|.")
    favourite_shortened_share: Decimal = Field(
        description="Share of fixtures where the pre-closing favourite's probability rose by kick-off.")
    pre_closing_logloss: Decimal
    closing_logloss: Decimal


class OddsIntelligence(Contract):
    source: str
    note: str
    fixtures_with_prices: int
    seasons: list[int]
    margins: Section[list[BookmakerMargin]]
    movement: Section[list[MovementRow]]
    live: Section[dict[str, int]] = Field(description="What our own capturer holds.")
