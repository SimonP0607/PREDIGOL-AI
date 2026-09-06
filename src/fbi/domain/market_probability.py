"""Raw implied probability versus de-vigged market probability.

Two different numbers about the same selection, which the legacy stored in
columns of the same type and occasionally swapped. Here they are two different
types. A function that needs the fair one cannot be handed the raw one by
accident, and ``mypy --strict`` enforces it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fbi.core.errors import InvalidDistributionError, InvalidOddsError
from fbi.domain.odds import DecimalOdds
from fbi.domain.probability import Probability, ProbabilityDistribution


class DevigMethod(StrEnum):
    """Matches market.market_consensus.devig_method in the schema."""

    PROPORTIONAL = "proportional"
    SHIN = "shin"
    POWER = "power"
    LOGARITHMIC = "logarithmic"


@dataclass(frozen=True, slots=True)
class RawImpliedProbability:
    """1 / odds for one selection. Carries the bookmaker's margin."""

    probability: Probability
    odds: DecimalOdds

    @classmethod
    def from_odds(cls, odds: DecimalOdds) -> RawImpliedProbability:
        return cls(probability=odds.raw_implied_probability(), odds=odds)


@dataclass(frozen=True, slots=True)
class FairProbability:
    """Market probability with the margin removed by a named method.

    The method is part of the value: a Shin-fair and a proportional-fair number
    are not interchangeable, so neither is a bare float.
    """

    probability: Probability
    method: DevigMethod
    overround: float

    def __float__(self) -> float:
        return self.probability.value


SHIN_MAX_ITER: Final[int] = 100
SHIN_TOLERANCE: Final[float] = 1e-10


def devig(
    odds_by_outcome: Mapping[str, DecimalOdds], method: DevigMethod
) -> dict[str, FairProbability]:
    """Remove the margin from the odds of one exclusive market.

    Returns one FairProbability per outcome; the results form a valid
    ProbabilityDistribution. Only for mutually exclusive outcomes.
    """
    if len(odds_by_outcome) < 2:
        raise InvalidOddsError("de-vigging needs at least two exclusive outcomes")
    names = list(odds_by_outcome)
    raw = [1.0 / float(odds_by_outcome[n].value) for n in names]
    book = sum(raw)
    if book <= 1.0:
        raise InvalidOddsError(
            f"raw implied probabilities sum to {book:.5f} <= 1: these odds have no margin "
            "to remove, which is not how a bookmaker prices a market"
        )

    if method is DevigMethod.PROPORTIONAL:
        fair = [r / book for r in raw]
    elif method is DevigMethod.SHIN:
        fair = _shin(raw)
    elif method is DevigMethod.POWER:
        fair = _power(raw)
    elif method is DevigMethod.LOGARITHMIC:
        fair = _logarithmic(raw)
    else:  # pragma: no cover - StrEnum is closed
        raise InvalidOddsError(f"unknown devig method {method!r}")

    dist = ProbabilityDistribution.normalize(dict(zip(names, fair, strict=True)))
    return {
        n: FairProbability(probability=dist[n], method=method, overround=book) for n in names
    }


def _shin(raw: Sequence[float]) -> list[float]:
    """Shin (1993): margin explained by a fraction z of insider money.

    Solves for z such that the implied fair probabilities sum to 1, then maps
    each raw probability through the Shin formula. Favourite-longshot bias is
    corrected rather than spread proportionally.
    """
    n = len(raw)
    book = sum(raw)
    lo, hi = 0.0, 1.0
    z = 0.0
    for _ in range(SHIN_MAX_ITER):
        z = (lo + hi) / 2.0
        total = sum(_shin_p(r, z, book, n) for r in raw)
        if abs(total - 1.0) < SHIN_TOLERANCE:
            break
        if total > 1.0:
            lo = z
        else:
            hi = z
    return [_shin_p(r, z, book, n) for r in raw]


def _shin_p(r: float, z: float, book: float, n: int) -> float:
    return (math.sqrt(z * z + 4.0 * (1.0 - z) * (r * r) / book) - z) / (2.0 * (1.0 - z))


def _power(raw: Sequence[float]) -> list[float]:
    """Find k such that sum(r ** k) == 1; longshots are shrunk more than favourites."""
    lo, hi = 0.5, 3.0
    k = 1.0
    for _ in range(SHIN_MAX_ITER):
        k = (lo + hi) / 2.0
        total = sum(r**k for r in raw)
        if abs(total - 1.0) < SHIN_TOLERANCE:
            break
        if total > 1.0:
            lo = k
        else:
            hi = k
    return [r**k for r in raw]


def _logarithmic(raw: Sequence[float]) -> list[float]:
    """Not implemented yet - and it says so instead of silently aliasing another
    method. The schema allows 'logarithmic' so the door is open; the domain
    refuses to produce a number under that name until the method is specified
    and tested."""
    raise NotImplementedError(
        "DevigMethod.LOGARITHMIC is declared in the schema but not implemented in the domain; "
        "use PROPORTIONAL, SHIN or POWER"
    )


def fair_distribution(fair: Mapping[str, FairProbability]) -> ProbabilityDistribution:
    if not fair:
        raise InvalidDistributionError("no fair probabilities to combine")
    return ProbabilityDistribution({k: v.probability for k, v in fair.items()})
