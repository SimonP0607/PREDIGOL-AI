"""The two teams before a match, side by side (REVIEW PREDIGOL, 11 Oct 2026, point 5), and every price captured
for it (point 10).

Every figure says how many of the matches it rests on (``n``): competitions and seasons do not all carry the same
data (corners, cards, xG), and a figure built from 3 of 10 matches is shown as such - never as a zero, never as a
full sample.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

ProfileScopeName = Literal["all", "competition"]
ProfileKind = Literal["count", "average", "ratio"]


class ProfileValue(Contract):
    value: Decimal | None = Field(
        description="count: the share of the n matches (0-1); average: the mean over n; ratio: null. "
                    "Null when no match carries the data.")
    count: int | None = Field(default=None, description="count: in how many matches it happened; ratio: the "
                                                        "numerator (penalties scored).")
    total: int | None = Field(default=None, description="ratio: the denominator (penalties taken).")
    n: int = Field(description="How many of the matches carry the data this figure is built from.")


class ProfileMetric(Contract):
    key: str = Field(description="wins, draws, losses, win_or_draw, btts, over_2_5, clean_sheets, failed_to_score, "
                                 "ht_lead, scored_first, conceded_first, goals_for, goals_against, xg_for, "
                                 "xg_against, shots, shots_on_target, shots_against, corners, corners_against, "
                                 "cards, fouls, possession, penalties.")
    kind: ProfileKind
    home: ProfileValue
    away: ProfileValue


class ProfileScope(Contract):
    scope: ProfileScopeName = Field(description="all: every competition; competition: this match's competition.")
    home_matches: int = Field(description="Finished matches of the home side found before kick-off (at most window).")
    away_matches: int
    metrics: list[ProfileMetric]


class MatchProfile(Contract):
    fixture_id: int
    window: int = Field(description="At most this many finished matches per team, the newest before kick-off.")
    scopes: list[ProfileScope]


# ── every captured price of a match (REVIEW point 10) ───────────────────────


class BookQuote(Contract):
    bookmaker_id: int
    bookmaker: str
    odds: Decimal = Field(description="The newest pre-match price this bookmaker gave for the selection.")
    captured_at: datetime
    opening_odds: Decimal = Field(description="The first price we captured from this bookmaker for it.")
    opening_at: datetime
    captures: int = Field(description="In how many captures this bookmaker priced the selection.")


class SelectionQuotes(Contract):
    market_key: str
    selection: str
    line: Decimal
    books: list[BookQuote]


class CaptureSummary(Contract):
    captured_at: datetime
    minutes_to_ko: int
    source: str = Field(description="prematch, or live for an in-play capture kept by an older build.")
    quotes: int = Field(description="Prices stored by this capture - the number the Cronología shows.")
    bookmakers: int
    by_market: dict[str, int] = Field(description="Prices per market in this capture.")


class MatchMarkets(Contract):
    fixture_id: int
    quotes: int = Field(description="Every price stored for the match, all captures together.")
    captures: list[CaptureSummary]
    selections: list[SelectionQuotes] = Field(
        description="Every pre-match selection and line, with each bookmaker's newest and first price.")
