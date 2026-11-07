"""Every structured market of a match by category, with the price IN FORCE of each selection (plan Partidos y Match Center,
F4a: M1, M2 and M4).

The 55 bet types of the price clock (``fbi.odds.quote_taxonomy``) - the five the product always showed and the fifty it kept
and never showed - read from the provider's last answer before kick-off (``fbi.odds.quote_current``), never from the newest row
of each price. Names are stable keys (code, period, subject; the selections in the vocabulary of ``market.odds_snapshots``):
the web translates them. A category appears only when the match has prices in force in it.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

CatalogCategory = Literal["result", "goals", "goals_half", "corners", "cards", "shots"]
CatalogState = Literal["priced", "withdrawn", "unread", "never_asked"]


class MarketCatalogBook(Contract):
    bookmaker_id: int
    bookmaker: str
    odds: Decimal = Field(description="This bookmaker's price in force for the selection and line.")
    captured_at: datetime = Field(
        description="Since when the answer carrying this price has been the provider's answer: the first ask of the run "
                    "of identical answers (after A -> B -> A, the ask that brought A back). The price is in force at "
                    "least since then.")
    bet_id: int = Field(description="The provider bet type the price came from (307 or 339 for the one corners "
                                    "double chance market).")


class MarketCatalogSelection(Contract):
    selection: str = Field(description="Home, Draw, Away, 1X, 12, X2, Over, Under, Yes, No, Odd, Even; the provider's "
                                       "own text for HT/FT and highest-scoring-half markets.")
    line: Decimal = Field(description="0 when the market has no line; for handicaps, the handicap of this selection.")
    best_odds: Decimal = Field(description="The highest price in force among the bookmakers below.")
    bookmaker_id: int = Field(description="The bookmaker of the best price (ties: by name).")
    bookmaker: str
    captured_at: datetime = Field(description="captured_at of the best price (see MarketCatalogBook).")
    bookmakers: int = Field(description="How many bookmakers have a price in force for this selection and line.")
    books: list[MarketCatalogBook] = Field(description="Every bookmaker's price in force, best first.")


class MarketCatalogMarket(Contract):
    key: str = Field(description="Stable key: code.period.subject, e.g. corners_double_chance.FT.match.")
    code: str = Field(description="What the market prices, e.g. goals_over_under, result_1x2, yellow_cards_over_under; "
                                  "bet_<id> for a bet switched on that has no code yet.")
    period: str = Field(description="FT, 1H, 2H.")
    subject: str = Field(description="match, home or away.")
    kind: str = Field(description="The taxonomy's shape: one_x_two, double_chance, over_under, asian_handicap, ...")
    has_line: bool
    category: CatalogCategory
    bet_ids: list[int] = Field(description="Provider bet types read as this one market (307 and 339 are one).")
    provider_name: str = Field(description="The provider's English name of the bet (of the lowest bet id).")
    market_key: str | None = Field(
        description="1X2, DC, BTTS, OU or AH for the five markets that are settled and go to the parlay; null for "
                    "the others, which are shown and never settled.")
    bookmakers: int = Field(description="How many bookmakers price this market.")
    selections: list[MarketCatalogSelection] = Field(
        description="Each selection and line, ordered by line (the home handicap for Asian handicaps) and selection.")


class MarketCatalogCategory(Contract):
    key: CatalogCategory
    markets: int = Field(description="Markets with a price in force in the category.")
    selections: int = Field(description="Selections and lines with a price in force.")
    bookmakers: int = Field(description="Bookmakers with a price in force in the category.")


class MarketCatalog(Contract):
    fixture_id: int
    kickoff_at: datetime
    state: CatalogState = Field(
        description="priced: the provider's newest readable answer before kick-off has prices; withdrawn: its newest "
                    "answer came back empty, so nothing is in force; unread: answers exist that are not structured yet; "
                    "never_asked: no pre-match ask in the 4 days before kick-off.")
    checked_at: datetime | None = Field(description="The ask whose answer is in force (null: never asked).")
    newer_answer_pending: bool = Field(
        description="A newer answer is not structured yet: the prices are those of the newest one that is.")
    partial: bool = Field(description="Some later page of the answer could not be tied to the ask in force and was "
                                      "left out (never shown stale).")
    category: CatalogCategory | None = Field(description="The category asked for; null when none was.")
    categories: list[MarketCatalogCategory] = Field(description="Only the categories with prices in force, in order.")
    markets: list[MarketCatalogMarket] = Field(description="The markets of the category asked for; empty when none was.")
