"""Markets, selections and lines as types.

"Over 2.5 Goals" is what API-Football says. What the domain knows is::

    Selection(market=MarketType.TOTAL_GOALS, side=Side.OVER, line=MarketLine("2.5"))

The provider label is parsed once, at the boundary, in the provider package.
Nothing past that boundary ever compares strings to decide what a bet is.

ASIAN HANDICAP AND THE SIGN OF A LINE
-------------------------------------
API-Football quotes bet 4 with the SAME number on both rows of a pair::

    {"value": "Home -0.25", "odd": "1.92"}
    {"value": "Away -0.25", "odd": "1.88"}

The number is the handicap **as applied to the home team**, repeated; the side
word says which team you are backing. (Measured, not assumed: every such pair
in our raw store devigs to exactly 1.090 under this reading, and to an
impossible 0.47 under the alternative one.)

Storing that verbatim would mean ``AH / Away / -0.25`` in the database while the
bet is actually *away receiving a quarter goal*, and every consumer would have
to remember to flip the sign. So the boundary negates: the ``line`` column
always holds the handicap **that applies to the selection stored beside it**.
``AH Away +0.75`` is a complete statement; no context is needed to read it.

That makes lines signed for Asian Handicap and unsigned everywhere else, which
is a property of the market (``MarketType.line_is_signed``) and is enforced in
the schema too, by a trigger reading ``market.markets.line_is_signed``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from fbi.core.errors import InvalidSelectionError


class MarketType(StrEnum):
    """The markets the platform can represent. ``value`` is the schema key
    (``market.markets.key``).

    Representable is not the same as modelled: whether our models may consume a
    market is ``market.markets.is_model_enabled``, and whether we capture prices
    for it is ``is_tracked``. Both live in the database, because both change
    without the domain changing.
    """

    MATCH_WINNER = "1X2"
    BOTH_TEAMS_TO_SCORE = "BTTS"
    TOTAL_GOALS = "OU"
    DOUBLE_CHANCE = "DC"
    ASIAN_HANDICAP = "AH"

    @property
    def has_line(self) -> bool:
        return self in {MarketType.TOTAL_GOALS, MarketType.ASIAN_HANDICAP}

    @property
    def line_is_signed(self) -> bool:
        """Whether a negative line is meaningful. A handicap can be negative
        (the favourite gives goals); a goal total cannot."""
        return self is MarketType.ASIAN_HANDICAP

    @property
    def is_exclusive(self) -> bool:
        """Whether the selections are mutually exclusive AND exhaustive, so that
        their fair probabilities sum to 1.

        False for Double Chance (its selections overlap) and false for Asian
        Handicap (a whole-number handicap can push, so the two sides do not
        exhaust the outcome space). For Asian Handicap the answer actually
        depends on the line, so the market-level answer is the conservative one:
        use ``Selection.push_possible`` when the line is known.
        """
        return self not in {MarketType.DOUBLE_CHANCE, MarketType.ASIAN_HANDICAP}

    @property
    def n_outcomes(self) -> int:
        return {
            MarketType.MATCH_WINNER: 3,
            MarketType.BOTH_TEAMS_TO_SCORE: 2,
            MarketType.TOTAL_GOALS: 2,
            MarketType.DOUBLE_CHANCE: 3,
            MarketType.ASIAN_HANDICAP: 2,
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
    MarketType.ASIAN_HANDICAP: frozenset({Side.HOME, Side.AWAY}),
}

NO_LINE: Final[Decimal] = Decimal("0")
"""What the schema stores for markets without a line. NOT NULL so the primary
key of the odds series is reliable: two NULLs never collide in PostgreSQL.

For Asian Handicap a stored 0 is a REAL line (level ball, a draw pushes), not
an absence. ``market_key`` is what tells the two apart, which is why the
schema-level rule is expressed against ``market.markets.has_line``."""

LINE_QUANTUM: Final[Decimal] = Decimal("0.01")

QUARTER: Final[Decimal] = Decimal("0.25")
HALF: Final[Decimal] = Decimal("0.5")


@dataclass(frozen=True, slots=True)
class MarketLine:
    """The threshold of a lined market: 2.5 in Over 2.5, -0.25 in Home -0.25.

    Quarter lines (2.25, -0.75) are valid: they are how Asian-style markets are
    quoted, and they mean half the stake on each neighbouring half-line.

    Whether a NEGATIVE line is meaningful depends on the market, so this type
    accepts the sign and ``Selection`` rejects it where it makes no sense. A
    line that is not a multiple of 0.25 is rejected here: no bookmaker quotes
    one, so such a value is a parsing failure rather than a price.
    """

    value: Decimal

    def __post_init__(self) -> None:
        try:
            d = Decimal(self.value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise InvalidSelectionError(f"line {self.value!r} is not a number") from exc
        if not d.is_finite():
            raise InvalidSelectionError(f"line must be a finite number, got {d}")
        if (d * 4) % 1 != 0:
            raise InvalidSelectionError(f"line {d} is not a multiple of 0.25")
        if d == 0:
            d = Decimal(0)  # negating a level-ball handicap must not yield -0
        object.__setattr__(self, "value", d.quantize(LINE_QUANTUM))

    @property
    def is_quarter(self) -> bool:
        """True for .25 and .75 lines - the ones that split the stake."""
        return (self.value * 2) % 1 != 0

    @property
    def is_whole(self) -> bool:
        """True for lines on which a bet can push (0, 1, 2.0, -1)."""
        return self.value % 1 == 0

    def __str__(self) -> str:
        return f"{self.value.normalize():f}"

    def signed(self) -> str:
        """Rendered the way a handicap is written: ``-0.25``, ``+0.75``, ``+0``."""
        return f"{'+' if self.value >= 0 else ''}{self}"


@dataclass(frozen=True, slots=True)
class Selection:
    """One thing you can bet on: a market, a side within it, and a line when
    the market has one. Immutable and hashable, so it can key a dict.

    For Asian Handicap the line is the handicap applied to ``side``: the away
    row of a provider pair arrives already negated (see the module docstring).
    """

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
        if self.line is not None and self.line.value < 0 and not self.market.line_is_signed:
            raise InvalidSelectionError(
                f"{self.market.value} does not take a negative line, got {self.line}"
            )

    @property
    def line_for_storage(self) -> Decimal:
        """The value that goes in the NOT NULL ``line`` column."""
        return self.line.value if self.line is not None else NO_LINE

    @property
    def push_possible(self) -> bool:
        """Whether this bet can be voided by the exact result (stake returned).

        True on a whole-number line: Over 2.0 with exactly two goals, Home -1
        won by exactly one. Downstream this is the difference between a two-way
        market whose probabilities sum to 1 and one whose do not.
        """
        return self.line is not None and self.line.is_whole

    @property
    def is_quarter_line(self) -> bool:
        return self.line is not None and self.line.is_quarter

    def quarter_components(self) -> tuple[Selection, Selection]:
        """The two half-stake bets a quarter line really is.

        ``AH Home -0.25`` is half a stake on ``AH Home +0`` (pushes on a draw)
        and half on ``AH Home -0.5``. ``OU Over 2.25`` is half ``Over 2`` and
        half ``Over 2.5``. Returned low line first.

        Raises for a line that is not a quarter line, rather than returning the
        selection twice: a caller asking this of ``Over 2.5`` has a bug.
        """
        if self.line is None or not self.line.is_quarter:
            raise InvalidSelectionError(f"{self} is not a quarter line")
        low, high = self.line.value - QUARTER, self.line.value + QUARTER
        return (
            Selection(self.market, self.side, MarketLine(low)),
            Selection(self.market, self.side, MarketLine(high)),
        )

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
        if self.line is None:
            return f"{self.market.value} {self.side.value}"
        if self.market.line_is_signed:
            return f"{self.market.value} {self.side.value} {self.line.signed()}"
        return f"{self.market.value} {self.side.value} {self.line}"
