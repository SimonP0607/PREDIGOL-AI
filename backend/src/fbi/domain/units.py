"""Theoretical units. The platform does not custody money.

Two types, because they mean different things and combine differently:
a ``StakeUnits`` is always positive (you cannot risk nothing or less), a
``ProfitUnits`` can be negative. Adding a stake to a profit is a type error.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Final

from fbi.core.errors import InvalidUnitsError

UNITS_QUANTUM: Final[Decimal] = Decimal("0.0001")  # NUMERIC(x,4) in the schema


def _to_decimal(value: Decimal | str | int, what: str) -> Decimal:
    if isinstance(value, bool | float):
        raise InvalidUnitsError(f"{what} must be a Decimal, str or int - not {type(value).__name__}")
    try:
        d = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidUnitsError(f"{what} {value!r} is not a number") from exc
    if not d.is_finite():
        raise InvalidUnitsError(f"{what} must be finite")
    return d.quantize(UNITS_QUANTUM, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class StakeUnits:
    """Amount risked, in theoretical units. Strictly positive."""

    value: Decimal

    def __post_init__(self) -> None:
        d = _to_decimal(self.value, "stake")
        if d <= 0:
            raise InvalidUnitsError(f"a stake must be positive, got {d}")
        object.__setattr__(self, "value", d)

    def __mul__(self, factor: Decimal) -> StakeUnits:
        return StakeUnits(self.value * factor)


@dataclass(frozen=True, slots=True)
class ProfitUnits:
    """Net result of a settled pick, in theoretical units. Any sign."""

    value: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _to_decimal(self.value, "profit"))

    def __add__(self, other: ProfitUnits) -> ProfitUnits:
        return ProfitUnits(self.value + other.value)

    def __neg__(self) -> ProfitUnits:
        return ProfitUnits(-self.value)

    @classmethod
    def zero(cls) -> ProfitUnits:
        return cls(Decimal(0))


def roi(profit: ProfitUnits, staked: StakeUnits) -> Decimal:
    """profit / stake, as a fraction. The only place ROI is computed in the domain.

    It requires a StakeUnits, which cannot be zero or absent. A caller with no
    stake cannot call this, which is the whole point.
    """
    return (profit.value / staked.value).quantize(UNITS_QUANTUM, rounding=ROUND_HALF_UP)
