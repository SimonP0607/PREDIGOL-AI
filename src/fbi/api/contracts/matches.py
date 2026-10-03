from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import (
    CompetitionRef,
    Contract,
    Lineage,
    Score,
    StatusGroup,
    TeamRef,
    VenueRef,
)
from fbi.api.envelope import Section


class OddsSummary(Contract):
    snapshots: int
    bookmakers: int
    markets: int
    first_captured_at: datetime | None
    last_captured_at: datetime | None
    near_close_snapshots: int


class MatchSummary(Contract):
    id: int
    provider_fixture_id: int
    kickoff_at: datetime
    status_short: str
    status_group: StatusGroup
    round: str | None
    competition: CompetitionRef
    home: TeamRef
    away: TeamRef
    score: Score | None
    odds: OddsSummary
    predictions: int
    awaiting_result: bool = Field(
        description="Kicked off and the row has not moved on: still scheduled 15 minutes after kick-off, "
                    "or still live 3.5 hours after it. A match being played is live, not awaiting."
    )


class MarketQuote(Contract):
    """One bookmaker's latest price for one selection."""

    bookmaker_id: int
    bookmaker: str
    market_key: str
    selection: str
    line: Decimal
    odds_decimal: Decimal
    implied_probability: Decimal = Field(description="1/odds. Raw: the bookmaker margin is still in it.")
    captured_at: datetime
    minutes_to_ko: int
    source: Literal["prematch", "live"]
    payload_hash: str


class PredictionRow(Contract):
    model: str
    model_version: str
    kind: Literal["backtest", "forecast"] = Field(
        description="'backtest': a historical replay, made walk-forward with data up to data_cutoff_ts. "
                    "'forecast': made in real time before kick-off.")
    backtest_session_id: int | None
    market_key: str
    selection: str
    line: Decimal
    p_raw: Decimal
    p_calibrated: Decimal
    p_lo: Decimal | None = Field(description="Null when no interval was computed - never a zero-width interval.")
    p_hi: Decimal | None
    data_cutoff_ts: datetime
    feature_set_hash: str
    created_at: datetime


class TimelineEvent(Contract):
    key: str
    label: str
    detail: str
    at: datetime | None
    state: Literal["done", "pending", "skipped", "failed"]


class MatchDetail(Contract):
    match: MatchSummary
    venue: VenueRef | None
    lineage: Lineage
    markets: Section[list[MarketQuote]]
    predictions: Section[list[PredictionRow]]
    timeline: list[TimelineEvent]


class MatchView(Contract):
    """What the product shows for a fixture: the match, where it is played, and its prices.
    Model output, lineage and the capture timeline belong to the Admin Console's MatchDetail."""

    match: MatchSummary
    venue: VenueRef | None
    markets: Section[list[MarketQuote]]
