"""Probability as a type, not as a float that happens to be small.

The legacy stored ``confidence_score`` and ``model_probability`` in columns of
the same shape and let them drift into each other. It also, in at least one
place, treated a percentage and a fraction as interchangeable. Both mistakes
are impossible with these types: a ``Probability`` cannot be built from 83, and
there is no implicit conversion in either direction.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from fbi.core.errors import InvalidDistributionError, InvalidProbabilityError

DISTRIBUTION_TOLERANCE: Final[float] = 1e-6
"""How far from 1.0 the outcomes of an exclusive market may sum before the
distribution is rejected. Explicit, so nobody has to guess what "about 1" means."""


@dataclass(frozen=True, slots=True)
class Probability:
    """A value in the closed interval [0, 1]. Immutable.

    Storage and presentation are separate: ``value`` is the number, and
    ``as_percentage()`` is a *rendering* of it. Nothing in the domain ever
    reasons in percentage points.
    """

    value: float

    def __post_init__(self) -> None:
        v = self.value
        if isinstance(v, bool) or not isinstance(v, int | float):
            raise InvalidProbabilityError(f"probability must be a real number, got {type(v).__name__}")
        if math.isnan(v) or math.isinf(v):
            raise InvalidProbabilityError("probability must be finite")
        if v > 1.0:
            hint = " (did you pass a percentage? use Probability.from_percentage)" if v <= 100 else ""
            raise InvalidProbabilityError(f"probability {v} is above 1{hint}")
        if v < 0.0:
            raise InvalidProbabilityError(f"probability {v} is below 0")
        object.__setattr__(self, "value", float(v))

    @classmethod
    def from_percentage(cls, percent: float) -> Probability:
        """The ONLY way a percentage becomes a probability."""
        return cls(percent / 100.0)

    @classmethod
    def from_decimal(cls, value: Decimal) -> Probability:
        return cls(float(value))

    def as_decimal(self, places: int = 6) -> Decimal:
        """Exact-decimal form for persistence (NUMERIC(8,6) in the schema)."""
        return Decimal(str(round(self.value, places)))

    def as_percentage(self) -> float:
        """For presentation only. Never store this."""
        return self.value * 100.0

    def complement(self) -> Probability:
        return Probability(1.0 - self.value)

    def __float__(self) -> float:
        return self.value

    def __lt__(self, other: Probability) -> bool:
        return self.value < other.value

    def __le__(self, other: Probability) -> bool:
        return self.value <= other.value

    def __gt__(self, other: Probability) -> bool:
        return self.value > other.value

    def __ge__(self, other: Probability) -> bool:
        return self.value >= other.value


@dataclass(frozen=True, slots=True)
class ProbabilityDistribution:
    """Probabilities over the outcomes of a mutually exclusive market.

    The outcomes must sum to 1 within ``DISTRIBUTION_TOLERANCE``. A distribution
    that does not is rejected loudly; it is never normalised behind the caller's
    back. If normalising is what you mean, call ``normalize()`` and say so.

    Not for Double Chance: its selections overlap and do not sum to 1. Use
    individual ``Probability`` values there.
    """

    outcomes: Mapping[str, Probability]

    def __post_init__(self) -> None:
        if not self.outcomes:
            raise InvalidDistributionError("a distribution needs at least one outcome")
        if any(not k for k in self.outcomes):
            raise InvalidDistributionError("outcome names must be non-empty")
        total = sum(p.value for p in self.outcomes.values())
        if abs(total - 1.0) > DISTRIBUTION_TOLERANCE:
            raise InvalidDistributionError(
                f"outcomes sum to {total:.6f}, not 1 (tolerance {DISTRIBUTION_TOLERANCE}); "
                "call ProbabilityDistribution.normalize() if that is really what you want"
            )
        object.__setattr__(self, "outcomes", dict(self.outcomes))

    @classmethod
    def normalize(cls, raw: Mapping[str, float]) -> ProbabilityDistribution:
        """Scale non-negative weights so they sum to 1. Explicit by design."""
        if not raw:
            raise InvalidDistributionError("nothing to normalise")
        if any(v < 0 for v in raw.values()):
            raise InvalidDistributionError("cannot normalise negative weights")
        total = sum(raw.values())
        if total <= 0:
            raise InvalidDistributionError("cannot normalise weights that sum to zero")
        return cls({k: Probability(v / total) for k, v in raw.items()})

    def __getitem__(self, outcome: str) -> Probability:
        return self.outcomes[outcome]

    def __iter__(self) -> Iterator[str]:
        return iter(self.outcomes)

    def __len__(self) -> int:
        return len(self.outcomes)

    def items(self) -> list[tuple[str, Probability]]:
        return list(self.outcomes.items())

    def most_likely(self) -> str:
        return max(self.outcomes, key=lambda k: self.outcomes[k].value)


def three_way(home: Probability, draw: Probability, away: Probability) -> ProbabilityDistribution:
    """The 1X2 distribution, with the outcome names the schema uses."""
    return ProbabilityDistribution({"Home": home, "Draw": draw, "Away": away})
