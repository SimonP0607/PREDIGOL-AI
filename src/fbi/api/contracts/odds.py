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


class FixtureOdds(Contract):
    match: MatchSummary
    board: Section[list[MarketQuote]]
    series: Section[list[OddsSeries]]
    near_close: Section[list[NearCloseQuote]]
    consensus: Section[list[ConsensusQuote]]
