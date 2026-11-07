"""Prop distributions (``player-engine-v1``): minutes x rate, a mixture over starting, coming on and not playing.

For a count with per-90 rate ``r`` and NB2 dispersion ``phi`` (``fbi.families.counts``), a man who plays ``m`` minutes has a count
distributed NB2(mean = r x m / 90, phi). He starts with ``p_start`` (and plays his minutes if he starts), comes on with ``p_sub`` (and
plays his minutes from the bench), and otherwise does not play: the count is 0. So

    P(X = k) = p_start NB2(k; r m_start / 90) + p_sub NB2(k; r m_sub / 90) + (1 - p_start - p_sub) [k = 0]

and it sums to one, up to the mass beyond the support (``tail``, reported, never hidden). P(over a line) is read off it. A bookmaker
usually voids a prop of a man who does not play; the price of that rule is ``conditional_on_playing``, the same mixture without the
no-play mass, renormalised.

THE GOAL SHARE. Given the team's expected goals ``xg`` (a team model, sim-v1 when it exists), each man's goal rate is scaled so that the
team's projected goals add up to ``xg``: rate_i x xg / sum_j rate_j E[minutes_j] / 90 over the team's projected men. Own goals are not
taken out of ``xg`` in v1.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

from fbi.families import counts

KMAX: Final = 25
"""Support of a player's count: 0..25 (a man's shots in a match rarely pass 10)."""


def mixture_pmf(per90: float, phi: float, scenarios: Sequence[tuple[float, float]], kmax: int = KMAX) -> NDArray[np.float64]:
    """P(X = k), k = 0..kmax, over the (probability, minutes) scenarios; the mass they leave is not playing (X = 0)."""
    total_p = sum(p for p, _ in scenarios)
    if any(p < -1e-12 for p, _ in scenarios) or total_p > 1.0 + 1e-9:
        raise ValueError(f"scenario probabilities must be in [0, 1] and add up to at most 1, got {total_p!r}")
    pmf = np.zeros(kmax + 1, dtype=np.float64)
    for p, minutes in scenarios:
        if p <= 0.0:
            continue
        mean = per90 * minutes / 90.0
        if mean > 0.0:
            pmf += p * counts.nb_pmf(mean, phi, kmax)
        else:
            pmf[0] += p
    pmf[0] += max(0.0, 1.0 - total_p)
    return pmf


def conditional_on_playing(per90: float, phi: float, scenarios: Sequence[tuple[float, float]], kmax: int = KMAX) -> NDArray[np.float64] | None:
    """The distribution given that he plays (a voided prop when he does not); None when he cannot play."""
    total = sum(p for p, _ in scenarios)
    if total <= 0.0:
        return None
    return mixture_pmf(per90, phi, [(p / total, m) for p, m in scenarios], kmax)


def p_over(pmf: NDArray[np.float64], line: float) -> float:
    return counts.over_under(pmf, line).over


@dataclass(frozen=True, slots=True)
class PropForecast:
    family: str
    mean: float
    pmf: NDArray[np.float64]
    over: Mapping[float, float]
    """P(count > line), unconditional (not playing is a count of 0)."""
    over_if_plays: Mapping[float, float] | None
    tail: float

    def as_json(self) -> dict[str, object]:
        return {"family": self.family, "mean": round(self.mean, 4), "tail": self.tail,
                "p_over": {str(k): round(v, 4) for k, v in self.over.items()},
                "p_over_if_plays": None if self.over_if_plays is None else {str(k): round(v, 4) for k, v in self.over_if_plays.items()},
                "pmf": [round(float(x), 5) for x in self.pmf[:8]]}


def forecast(family: str, per90: float, phi: float, scenarios: Sequence[tuple[float, float]], lines: Sequence[float]) -> PropForecast:
    pmf = mixture_pmf(per90, phi, scenarios)
    cond = conditional_on_playing(per90, phi, scenarios)
    mean = sum(p * per90 * m / 90.0 for p, m in scenarios)
    return PropForecast(family, mean, pmf, {line: p_over(pmf, line) for line in lines},
                        None if cond is None else {line: p_over(cond, line) for line in lines}, counts.tail_mass(pmf))


def goal_scale(goal_rates: Mapping[int, float], expected_minutes: Mapping[int, float], team_xg: float) -> float:
    """The factor that makes the team's projected goals equal ``team_xg``: xg / sum_i rate_i E[minutes_i] / 90."""
    if team_xg < 0:
        raise ValueError("expected goals cannot be negative")
    projected = sum(goal_rates[p] * expected_minutes.get(p, 0.0) / 90.0 for p in goal_rates)
    if projected <= 0.0:
        raise ValueError("the team has no projected goals to share")
    return team_xg / projected
