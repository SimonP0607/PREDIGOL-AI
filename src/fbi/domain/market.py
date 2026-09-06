"""Markets, selections and lines as types.

"Over 2.5 Goals" is what API-Football says. What the domain knows is::

    Selection(market=MarketType.TOTAL_GOALS, side=Side.OVER, line=Decimal("2.5"))

The provider label is parsed once, at the boundary, in the provider package.
Nothing past that boundary ever compares strings to decide what a bet is.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from fbi.core.errors import InvalidSelectionError


class MarketType(StrEnum):
    """The markets the platform models. ``value`` is the schema key
    (market.markets.key)."""

    MATCH_WINNER = "1X2"
    BOTH_TEAMS_TO_SCORE = "BTTS"
    TOTAL_GOALS = "OU"
    DOUBLE_CHANCE = "DC"

    @property
    def has_line(self) -> bool:
        return self is MarketType.TOTAL_GOALS

    @property
    def is_exclusive(self) -> bool:
        """Whether the selections are mutually exclusive and sum to 1.
        Double Chance is the reason this property exists."""
        return self is not MarketType.DOUBLE_CHANCE

    @property
    def n_outcomes(self) -> int:
        return {
            MarketType.MATCH_WINNER: 3,
            MarketType.BOTH_TEAMS_TO_SCORE: 2,
            MarketType.TOTAL_GOALS: 2,
            MarketType.DOUBLE_CHANCE: 3,
        }[self]


class Side(StrEnum):
    """The selection within a market. ``value`` is what the schema stores in
    the ``selection`` column, so a round trip through the database is exact."""

    HOME = "Home"
    DRAW = "Draw"
    AWAY = "Away"
    YES = "Yes"
    NO = "No"
    OVER = "Over"
    UNDER = "Under"
    HOME_OR_DRAW = "1X"
    HOME_OR_AWAY = "12"
    DRAW_OR_AWAY = "X2"


SIDES_BY_MARKET: Final[dict[MarketType, frozenset[Side]]] = {
    MarketType.MATCH_WINNER: frozenset({Side.HOME, Side.DRAW, Side.AWAY}),
    MarketType.BOTH_TEAMS_TO_SCORE: frozenset({Side.YES, Side.NO}),
    MarketType.TOTAL_GOALS: frozenset({Side.OVER, Side.UNDER}),
    MarketType.DOUBLE_CHANCE: frozenset({Side.HOME_OR_DRAW, Side.HOME_OR_AWAY, Side.DRAW_OR_AWAY}),
}

NO_LINE: Final[Decimal] = Decimal("0")
"""What the schema stores for markets without a line. NOT NULL so the primary
key of the odds series is reliable: two NULLs never collide in PostgreSQL."""

LINE_QUANTUM: Final[Decimal] = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class MarketLine:
    """The threshold of a lined market, e.g. 2.5 in Over 2.5.

    Quarter lines (2.25, 2.75) are valid: they are how Asian-style totals are
    quoted. Negative lines are not a thing for goals.
    """

    value: Decimal

    def __post_init__(self) -> None:
        try:
            d = Decimal(self.value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise InvalidSelectionError(f"line {self.value!r} is not a number") from exc
        if not d.is_finite() or d < 0:
            raise InvalidSelectionError(f"line must be a finite non-negative number, got {d}")
        if (d * 4) % 1 != 0:
            raise InvalidSelectionError(f"line {d} is not a multiple of 0.25")
        object.__setattr__(self, "value", d.quantize(LINE_QUANTUM))

    def __str__(self) -> str:
        return f"{self.value.normalize():f}"


@dataclass(frozen=True, slots=True)
class Selection:
    """One thing you can bet on: a market, a side within it, and a line when
    the market has one. Immutable and hashable, so it can key a dict."""

    market: MarketType
    side: Side
    line: MarketLine | None = None

    def __post_init__(self) -> None:
        if self.side not in SIDES_BY_MARKET[self.market]:
            raise InvalidSelectionError(f"{self.side.value!r} is not a side of {self.market.value}")
        if self.market.has_line and self.line is None:
            raise InvalidSelectionError(f"{self.market.value} needs a line")
        if not self.market.has_line and self.line is not None:
            raise InvalidSelectionError(f"{self.market.value} does not take a line")

    @property
    def line_for_storage(self) -> Decimal:
        """The value that goes in the NOT NULL ``line`` column."""
        return self.line.value if self.line is not None else NO_LINE

    @classmethod
    def from_storage(cls, market_key: str, selection: str, line: Decimal) -> Selection:
        """Rebuild from the three schema columns. Exact inverse of the
        properties above; a value that does not round-trip is rejected."""
        try:
            market = MarketType(market_key)
            side = Side(selection)
        except ValueError as exc:
            raise InvalidSelectionError(f"unknown market/selection {market_key!r}/{selection!r}") from exc
        if market.has_line:
            return cls(market, side, MarketLine(line))
        if Decimal(line) != NO_LINE:
            raise InvalidSelectionError(f"{market_key} stored with a non-zero line {line}")
        return cls(market, side, None)

    def __str__(self) -> str:
        if self.line is not None:
            return f"{self.market.value} {self.side.value} {self.line}"
        return f"{self.market.value} {self.side.value}"
