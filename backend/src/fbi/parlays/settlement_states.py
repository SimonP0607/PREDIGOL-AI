"""The joint probability of a parlay over the SIX settlement states of each leg, and the dependence of its pairs (plan RP-11.2, finding H23,
``parlay-states-v1``).

Today a quarter line or a void leg collapses to «win» or «lose». Here a leg is a distribution over six states that add up to one:

* ``win`` pays the whole price; ``half_win`` (quarter line, half of the stake wins) pays ``1 + (price - 1) / 2``;
* ``push`` and ``void`` (a line that lands on the number; a cancelled selection) return the stake: the leg counts as 1 and the parlay goes on;
* ``half_loss`` (quarter line, half of the stake loses) returns half the stake: 0.5; ``loss`` returns nothing and loses the parlay.

The parlay's payout is the product of the legs' factors, so its distribution is the sum over the combinations of states. The legs of a parlay are of distinct
matches and teams (``fbi.parlays.engine.guard``), and this module never relaxes that: a repeated fixture is refused. The dependence of a pair is not assumed: it is
read from the measured intra-class correlation of ``fbi.parlays.correlation`` (EXP-E7's table) and a pair whose interval does not contain zero is MARKED, with its
direction. A mark never raises a probability: the joint reported is the one over independent legs, and the marks say where it may be wrong. Pure: reads nothing,
writes nothing.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from fbi.parlays.correlation import MIN_GROUPS, Estimate

VERSION: Final = "parlay-states-v1"
STATES: Final = ("win", "half_win", "push", "half_loss", "loss", "void")
TOLERANCE: Final = 1e-9
MAX_LEGS: Final = 3

Mark = Literal["independiente", "dependiente_positiva", "dependiente_negativa", "sin_medida"]


class StatesError(ValueError):
    """A leg or a parlay that the model of states cannot hold."""


@dataclass(frozen=True, slots=True)
class LegStates:
    fixture_id: int
    price: float
    states: Mapping[str, float]
    market: str | None = None
    """The measured market of ``fbi.parlays.correlation.market_of`` the leg belongs to, when it has one."""
    group: tuple[int, str] | None = None
    """(competition season, day) the leg's match is counted in: two legs of the same group share an environment."""

    def __post_init__(self) -> None:
        if self.price <= 1:
            raise StatesError("a price is above 1")
        if set(self.states) - set(STATES):
            raise StatesError(f"unknown states {sorted(set(self.states) - set(STATES))}")
        if any(p < 0 or p > 1 for p in self.states.values()):
            raise StatesError("a probability is between 0 and 1")
        if abs(sum(self.states.values()) - 1.0) > TOLERANCE:
            raise StatesError(f"the states of a leg add up to one, not {sum(self.states.values()):.12f}")

    def factor(self, state: str) -> float:
        """What a unit staked on the leg becomes in ``state``."""
        return {"win": self.price, "half_win": 1 + (self.price - 1) / 2, "push": 1.0, "void": 1.0, "half_loss": 0.5, "loss": 0.0}[state]


@dataclass(frozen=True, slots=True)
class Pair:
    first: int
    second: int
    mark: Mark
    rho: float | None
    lower: float | None
    upper: float | None


@dataclass(frozen=True, slots=True)
class Distribution:
    """The parlay's payout over the combinations of the legs' states."""

    outcomes: tuple[tuple[float, float], ...]
    """(payout factor, probability), one entry per payout, ordered by factor."""
    full: float = 0.0
    """The probability that every leg paid in full."""

    @property
    def total(self) -> float:
        return sum(p for _, p in self.outcomes)

    @property
    def p_loss(self) -> float:
        return sum(p for f, p in self.outcomes if f == 0.0)

    @property
    def p_return_stake_or_more(self) -> float:
        return sum(p for f, p in self.outcomes if f >= 1.0)

    @property
    def p_profit(self) -> float:
        return sum(p for f, p in self.outcomes if f > 1.0)

    @property
    def p_full_win(self) -> float:
        """Every leg paid in full: the only case the old calculation called «win»."""
        return self.full

    @property
    def expected_return(self) -> float:
        return sum(f * p for f, p in self.outcomes)


def distribution(legs: Sequence[LegStates]) -> Distribution:
    """The sum over the combinations of states. Raises on a repeated fixture or more than three legs: the rules of the parlays are not relaxed here."""
    if not 1 <= len(legs) <= MAX_LEGS:
        raise StatesError(f"a parlay holds 1 to {MAX_LEGS} legs")
    if len({leg.fixture_id for leg in legs}) != len(legs):
        raise StatesError("two legs of the same match are never combined")
    by_factor: dict[float, float] = {}
    full = 0.0
    for combo in itertools.product(*(tuple(s for s in STATES if leg.states.get(s, 0.0) > 0) for leg in legs)):
        p = math.prod(leg.states[s] for leg, s in zip(legs, combo, strict=True))
        factor = math.prod(leg.factor(s) for leg, s in zip(legs, combo, strict=True))
        key = round(factor, 10)
        by_factor[key] = by_factor.get(key, 0.0) + p
        if all(s == "win" for s in combo):
            full += p
    return Distribution(tuple(sorted(by_factor.items())), full=full)


def pairs(legs: Sequence[LegStates], estimates: Mapping[str, Estimate]) -> list[Pair]:
    """The mark of every pair of legs. Legs that share a (competition season, day) share an environment and the market's measured correlation says whether it
    matters; a pair that does not share one is independent by construction; a pair that shares one whose market has no measure (or too few days) is «sin medida»."""
    out: list[Pair] = []
    for i, j in itertools.combinations(range(len(legs)), 2):
        a, b = legs[i], legs[j]
        if a.group is None or b.group is None or a.group != b.group:
            out.append(Pair(i, j, "independiente", None, None, None))
            continue
        est = estimates.get(a.market or "") if a.market == b.market else None
        if est is None or est.n_groups < MIN_GROUPS:
            out.append(Pair(i, j, "sin_medida", None, None, None))
            continue
        low, high = est.rho - 1.96 * est.se, est.upper
        mark: Mark = "independiente" if low <= 0 <= high else ("dependiente_positiva" if low > 0 else "dependiente_negativa")
        out.append(Pair(i, j, mark, est.rho, low, high))
    return out


def check(dist: Distribution) -> bool:
    """The coherence test of the states: the distribution adds up to one."""
    return abs(dist.total - 1.0) <= 1e-9


__all__ = ["MAX_LEGS", "STATES", "VERSION", "Distribution", "LegStates", "Pair", "StatesError", "check", "distribution", "pairs"]
