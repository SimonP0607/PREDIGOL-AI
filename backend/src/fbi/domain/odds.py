"""Decimal odds and what can honestly be derived from them.

``1 / odds`` is the *raw implied probability*. It contains the bookmaker's
margin, and across the outcomes of a market it sums to more than 1. It is
NOT a fair probability, and this module never calls it one. De-vigging lives in
``fbi.domain.market_probability`` and returns a different type on purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final

from fbi.core.errors import InvalidOddsError
from fbi.domain.probability import Probability

MIN_ODDS: Final[Decimal] = Decimal("1.001")
MAX_ODDS: Final[Decimal] = Decimal("999.999")
ODDS_QUANTUM: Final[Decimal] = Decimal("0.001")  # NUMERIC(9,3) in the schema


@dataclass(frozen=True, slots=True)
class DecimalOdds:
    """A price. Strictly greater than 1: at 1.000 the bettor cannot win."""

    value: Decimal

    def __post_init__(self) -> None:
        v = self.value
        if isinstance(v, bool | float):
            # A float here is almost always a bug: 2.1 is not 2.100 exactly.
            raise InvalidOddsError(
                f"odds must be a Decimal (or str), got {type(v).__name__}; use DecimalOdds.parse"
            )
        try:
            d = Decimal(v)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise InvalidOddsError(f"odds {v!r} is not a number") from exc
        if not d.is_finite():
            raise InvalidOddsError("odds must be finite")
        if d < MIN_ODDS or d > MAX_ODDS:
            raise InvalidOddsError(f"odds {d} outside the plausible range [{MIN_ODDS}, {MAX_ODDS}]")
        object.__setattr__(self, "value", d.quantize(ODDS_QUANTUM, rounding=ROUND_HALF_UP))

    @classmethod
    def parse(cls, text: str | int | float | Decimal) -> DecimalOdds:
        """From provider text or a number. Goes through str so floats do not
        smuggle binary noise into the third decimal."""
        try:
            return cls(Decimal(str(text).strip()))
        except InvalidOperation as exc:
            raise InvalidOddsError(f"odds {text!r} is not a number") from exc

    def raw_implied_probability(self) -> Probability:
        """1 / odds. Includes the margin. Not fair, and not called fair."""
        return Probability(float(Decimal(1) / self.value))

    def payout_per_unit(self) -> Decimal:
        """Net profit per unit staked if the selection wins: odds - 1."""
        return self.value - Decimal(1)

    def __float__(self) -> float:
        return float(self.value)

    def __lt__(self, other: DecimalOdds) -> bool:
        return self.value < other.value

    def __gt__(self, other: DecimalOdds) -> bool:
        return self.value > other.value

    def __str__(self) -> str:
        return f"{self.value:.3f}"


def overround(odds: list[DecimalOdds]) -> Decimal:
    """Sum of raw implied probabilities across an exclusive market's outcomes.

    1.000 would be a fair book; 1.05 means a 5 % margin. Only meaningful for
    mutually exclusive outcomes (1X2, OU, BTTS) - never for Double Chance.
    """
    if len(odds) < 2:
        raise InvalidOddsError("overround needs the odds of at least two outcomes")
    total = sum((Decimal(1) / o.value for o in odds), Decimal(0))
    return total.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
