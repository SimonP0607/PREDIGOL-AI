"""The odds explorer (plan Cuotas, ola 2, BE-011): the families and markets with prices, a market's board across matches, a match's
whole book, the movement of a selection and the owner's health panel - read from the current-price book (``market.book_current``,
``fbi.odds.book``) and the stored history, never from the provider.

Names are stable keys the web translates: a market is its ``tax-v3`` key without the period (``corners.total``,
``goals.total.home``; an interval keeps its own, ``result.1x2.m0_10``), a family a key of ``market.market_families``, a selection a
vocabulary code (Home, Draw, Away, Over, Under, Yes, No, 1X, 12, X2, an exact score "2:1", a band "0-2", "Player" with the player's
name apart). Bookmakers are the PROVIDER's ids (``market.bookmakers.provider_bookmaker_id``), the ids the book holds; each answer
names the ones it uses in ``bookmakers``. Decimals travel as strings, times as ISO-8601 UTC.

``state`` follows one rule (``fbi.odds.freshness``): ``current`` when the price was confirmed by the latest scheduled capture or
book refresh for its distance to kick-off (with the capture's window tolerance), ``stale`` when one was missed since. A stale
price is shown dimmed, never goes to Mi Parlay and is left out of ``sort=edge``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.product import CompetitionBadge, TeamBadge

Subject = Literal["match", "home", "away", "player", "keeper"]
Period = Literal["FT", "1H", "2H", "INTERVAL"]
RowState = Literal["current", "stale"]
BookState = Literal["current", "stale", "none"]
Horizon = Literal["0-6h", "6-24h", "24-72h"]
Sort = Literal["time", "competition", "edge"]


class OddsMarketInfo(Contract):
    key: str = Field(description="Stable market key: the tax-v3 key without its period (corners.total, goals.total.home); "
                                 "a minute interval keeps its own (result.1x2.m0_10).")
    family: str = Field(description="The family it is listed under (result, goals, goals_half, corners, cards, shots, "
                                    "players, saves, offsides, tackles, special, timing, advance).")
    kind: str = Field(description="How its selections read (the tax-v3 reader): plain, line, signed_line, signed_line_3way, "
                                  "exact_score, ht_ft, result_total, total_btts, count, range, player, player_count.")
    subject: Subject
    periods: list[Period] = Field(description="The periods with prices (in the window, or in the match).")
    has_line: bool
    fair: bool = Field(description="A fair price can be computed for it (exhaustive, with a method; it still needs three "
                                   "complete bookmakers in a match).")
    parlay: bool = Field(description="One of its periods is one of Mi Parlay's five markets.")
    fixtures: int = Field(description="Matches with prices for it (in the window; 1 in a match's book).")
    max_books: int = Field(description="The most bookmakers quoting it in one match.")


class OddsFamily(Contract):
    key: str
    fixtures: int = Field(description="Matches of the window with prices in the family.")
    markets: list[OddsMarketInfo]


class OddsFamilies(Contract):
    window_hours: int
    families: list[OddsFamily] = Field(description="Only the families and markets with prices in the window, in the "
                                                   "explorer's order.")
    book_enabled: bool = Field(description="FBI_ODDS_BOOK: the worker builds the book. Off, the lists are empty or old.")
    generated_at: datetime


class OddsSelectionPrice(Contract):
    selection: str = Field(description="A vocabulary code; 'Player' in a player market, with the name in ``player``.")
    player: str | None = Field(description="The player of a player market's price (null elsewhere).")
    line: Decimal | None = Field(description="The selection's OWN line: an Asian handicap's away side is -h. Null: no line; "
                                             "a player count's line is the count reached (N or more).")
    best_odds: Decimal = Field(description="The highest price among every bookmaker in force (one definition, plan E12).")
    bookmaker_id: int = Field(description="The provider bookmaker of the best price (the lowest id on a tie).")
    n_books: int
    fair_odds: Decimal | None = Field(description="1 / p of the market's de-vigged consensus (Shin per bookmaker, three "
                                                  "complete bookmakers at least); null where it means nothing.")
    price_edge: Decimal | None = Field(description="best_odds * p_fair - 1, only with fair_odds. A market comparison, not "
                                                   "a model's edge.")
    outlier: bool = Field(description="More than 25 % above fair: suspect, never highlighted, never in Mi Parlay.")
    parlay_ok: bool = Field(description="May go to Mi Parlay: one of its five markets, not a quarter line, not an outlier, "
                                        "current and not started.")


class OddsBoardRow(Contract):
    fixture_id: int
    kickoff_at: datetime
    competition_id: int
    home: TeamBadge
    away: TeamBadge
    line: Decimal | None = Field(description="The line shown (an Asian handicap's: the home line).")
    lines: list[Decimal] = Field(description="Every line this match quotes for the market, sorted.")
    selections: list[OddsSelectionPrice]
    captured_at: datetime = Field(description="When the body in force was first fetched.")
    provider_update_at: datetime | None = Field(description="The provider's own update stamp of that body.")
    state: RowState


class OddsBookmaker(Contract):
    id: int = Field(description="The provider's bookmaker id.")
    name: str


class OddsBoardPage(Contract):
    market: OddsMarketInfo
    period: Period
    rows: list[OddsBoardRow]
    total: int = Field(description="Rows matching the filters (under sort=edge: current rows with a fair price only).")
    next_cursor: str | None = Field(description="Pass back as ``cursor`` for the next page; null on the last one. Opaque.")
    competitions: list[CompetitionBadge] = Field(description="The competitions of the rows (a dictionary).")
    bookmakers: list[OddsBookmaker] = Field(description="The bookmakers the rows name (a dictionary).")
    generated_at: datetime


class OddsBookPrices(Contract):
    bookmaker_id: int
    odds: list[Decimal | None] = Field(description="This bookmaker's price of each selection of the line, in the order of "
                                                   "``selections``; null where it does not quote one.")


class OddsBookLine(Contract):
    line: Decimal | None
    selections: list[OddsSelectionPrice]
    books: list[OddsBookPrices]


class OddsBookMarket(Contract):
    info: OddsMarketInfo
    period: Period
    main_line: Decimal | None = Field(description="The line shown first (null without lines).")
    lines: list[OddsBookLine]


class OddsBookFamily(Contract):
    key: str
    markets: list[OddsBookMarket]


class MatchOddsBook(Contract):
    fixture_id: int
    kickoff_at: datetime
    captured_at: datetime | None
    provider_update_at: datetime | None
    state: BookState = Field(description="none: no price in force (never asked, withdrawn, or not built).")
    families: list[OddsBookFamily]
    bookmakers: list[OddsBookmaker]


class OddsMovementPoint(Contract):
    at: datetime = Field(description="The capture's instant.")
    best_odds: Decimal = Field(description="The best price at that capture, outliers left out.")
    bookmaker_id: int
    n_books: int


class OddsMovementSeries(Contract):
    selection: str
    line: Decimal | None = Field(description="The selection's own line (an Asian handicap's away side: -h).")
    points: list[OddsMovementPoint]


class OddsMovement(Contract):
    fixture_id: int
    market: str
    period: Period
    line: Decimal | None = Field(description="The line followed (the market's main line when none was asked for).")
    available: bool = Field(description="False for a type with no stored history (only the five classic markets, from "
                                        "odds_snapshots, and the 55 extracted types, from odds_quotes, have one).")
    source: Literal["snapshots", "quotes"] | None
    series: list[OddsMovementSeries]
    bookmakers: list[OddsBookmaker]


class OddsHorizonHealth(Contract):
    horizon: Horizon
    fixtures: int = Field(description="Followed matches with odds kicking off in the horizon.")
    with_book: int = Field(description="Those with rows in the book.")
    median_age_min: int | None = Field(description="Median minutes since the ask that confirmed their prices.")
    stale: int = Field(description="Those whose prices missed a scheduled capture or refresh.")


class OddsHealth(Contract):
    by_horizon: list[OddsHorizonHealth]
    extraction_lag_min: int | None = Field(description="Age of the oldest /odds body of the last day the extractor has not "
                                                       "read (0: caught up; book refreshes are not its to read).")
    book_rows: int
    book_mb: float
    quota_today: int = Field(description="Requests issued today, counted by us (raw.provider_quota).")
    quota_limit: int = Field(description="Our daily budget, never above the plan.")
    provider_requests_remaining: int | None = Field(description="What the provider's headers said remains today; null "
                                                                "before any answer of the day carried it.")
    default_partition_rows: int = Field(description="Rows in the DEFAULT partitions of the odds series (should be 0).")
    odds_quotes_gb: float
    odds_quotes_brake_gb: float = Field(description="FBI_QUOTES_MAX_TABLE_GB: the extractor stops past it.")


# ── /odds/status: the reader's «Estado de los precios» (plan maestro UX/UI 2026, decision 4) ──────────────────────────


class OddsStatusHorizon(Contract):
    horizon: Horizon
    fixtures: int = Field(description="Followed matches with odds kicking off in the horizon.")
    with_price: int = Field(description="Those with a price in force.")
    stale: int = Field(description="Those whose price missed a scheduled capture (shown with a clock and its hour).")


class OddsStatusMatch(Contract):
    fixture_id: int
    kickoff_at: datetime
    home: str
    away: str
    competition: str


class OddsStatus(Contract):
    """What a reader may know of the prices they see: when they were last read, how many matches have one and how many are
    late - the same judgement as the owner's /admin/odds/health, without its machinery (quota, sizes, partitions)."""

    last_read_at: datetime | None = Field(description="The latest ask that confirmed a price of a followed match of the "
                                                      "next 72 h; null without any.")
    by_horizon: list[OddsStatusHorizon]
    without_price: list[OddsStatusMatch] = Field(description="Followed matches of the next 24 h without a price in force, "
                                                             "soonest first (at most 20).")
    without_price_total: int = Field(description="How many there are in the next 24 h.")
    schedule_minutes: list[int] = Field(description="The rule in force: the minutes before kick-off at which a price is "
                                                    "read again. A price that missed its last closed point is late.")
    tolerance_minutes: int = Field(description="The margin of each point.")
