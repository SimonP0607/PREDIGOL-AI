"""The joint distribution of a match by halves: P(home_1H = i, away_1H = j, home_2H = k, away_2H = l).

WHERE THE INTENSITIES COME FROM. Each of the four counts is Poisson with its own intensity (``HalfIntensities``):

    from the half fits ........ ``fbi.families`` fits ``goals_1h`` and ``goals_2h`` separately (a Poisson per team and half, plan F10);
                                their means ARE the four intensities (``HalfIntensities`` directly), or they give only the SHARE of
                                each side's goals that falls in the first half, applied to the full-time model's expected goals
                                (``rescale_to_full_time``), so the full-time margin stays the model in force
    from full time only ....... the Poisson / Dixon-Coles fit (``fbi.models.goals``) knows full time only; its expected goals are split
                                with the documented constants ``FIRST_HALF_SHARE_HOME`` / ``FIRST_HALF_SHARE_AWAY`` (``split_full_time``)

Whatever the split, the full-time marginal of independent Poisson halves is Poisson with the summed intensity (the sum of independent
Poisson counts is Poisson), so the full-time markets do not depend on the split at all: only the half markets (and HT/FT) do.

THE DIXON-COLES CORRECTION. Where the source model has it (``kind == "dixon_coles"``, its fitted ``rho``), every cell is multiplied by
the model's own tau factor of its FULL-TIME score (0-0, 1-0, 0-1, 1-1), at the full-time expected goals. The full-time marginal is then
exactly the source model's matrix: summing the cells of one full-time score gives its Poisson probability, and tau multiplies that.
tau moves no mass in total (the four adjustments add up to zero, and all four scores are inside the truncation), so the correction
needs no renormalisation of its own. A rho outside the region where every tau is positive is refused, as the source model refuses it
(``fbi.models.goals.InvalidCorrectionError``): clipping it would be another model.

THE ASSUMPTION, STATED (the same as ``fbi.families.halves``). Given the strengths, the two halves are independent and so are the two
sides within a half, apart from the Dixon-Coles reweighting of the low full-time scores. A match 2-0 at half-time is played differently
afterwards; ``fbi.families.evaluate_halves`` measures how much that matters (the correlation of the halves' residuals).

TRUNCATION. Each count stops at ``MAX_HALF_GOALS`` (so full time reaches ``2 * MAX_HALF_GOALS`` per side, beyond the 10-10 of the
full-time models). The mass beyond is reported (``tail_mass``) and the truncated distribution is renormalised, as the source models do.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Final

import numpy as np
from numpy.typing import NDArray
from scipy.stats import poisson

from fbi.models.goals import GoalModel, InvalidCorrectionError, dc_valid

MAX_HALF_GOALS: Final = 10
"""Goals of one side in one half, 0..10. At an intensity of 2 per half (a full-time expectation of about 4.5 for one side, far above any
league average) the mass beyond is under 1e-5 per count; ``tail_mass`` reports it for every match."""

FIRST_HALF_SHARE_HOME: Final = 0.45
FIRST_HALF_SHARE_AWAY: Final = 0.45
"""The share of a side's expected goals that falls in the FIRST half, used only when nothing better than the full-time fit is given.
A documented constant, not a measurement made here: across top-flight football about 44-46% of goals come before half-time (the second
half is longer with stoppage time and is played by tired, chasing teams). It moves only the half markets and HT/FT; the full-time
markets are independent of it (see the module docstring). The half fits of ``fbi.families`` replace it when they are given."""

DC_KINDS: Final = frozenset({"dixon_coles"})
"""The source model kinds that carry the low-score correction."""


@dataclass(frozen=True, slots=True)
class HalfIntensities:
    """The expected goals of each side in each half."""

    home_1h: float
    away_1h: float
    home_2h: float
    away_2h: float

    def __post_init__(self) -> None:
        for name in ("home_1h", "away_1h", "home_2h", "away_2h"):
            value = getattr(self, name)
            if not (np.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be a positive expected number of goals, not {value!r}")

    @property
    def home(self) -> float:
        return self.home_1h + self.home_2h

    @property
    def away(self) -> float:
        return self.away_1h + self.away_2h

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self.home_1h, self.away_1h, self.home_2h, self.away_2h


def split_full_time(lam_home: float, lam_away: float, *, share_home: float = FIRST_HALF_SHARE_HOME,
                    share_away: float = FIRST_HALF_SHARE_AWAY) -> HalfIntensities:
    """The four intensities of a full-time fit, split by the first-half shares."""
    for name, share in (("share_home", share_home), ("share_away", share_away)):
        if not 0 < share < 1:
            raise ValueError(f"{name} must be strictly between 0 and 1, not {share!r}")
    return HalfIntensities(lam_home * share_home, lam_away * share_away, lam_home * (1 - share_home), lam_away * (1 - share_away))


def rescale_to_full_time(halves: HalfIntensities, lam_home: float, lam_away: float) -> HalfIntensities:
    """The half fits' split of each side's goals, applied to the full-time model's expected goals.

    The half fits and the full-time fit are separate fits: their sums need not agree. Keeping the full-time model's expected goals and
    taking only the shares from the halves keeps every full-time market equal to the model in force."""
    return split_full_time(lam_home, lam_away, share_home=halves.home_1h / halves.home,
                           share_away=halves.away_1h / halves.away)


@dataclass(frozen=True)
class JointScore:
    """The normalised joint distribution of one match, indexed ``p[home_1h, away_1h, home_2h, away_2h]``."""

    p: NDArray[np.float64]
    intensities: HalfIntensities
    rho: float | None
    tail_mass: float
    """Mass beyond ``max_goals`` in any count, before the renormalisation."""
    source: str = ""

    @property
    def max_goals(self) -> int:
        return int(self.p.shape[0]) - 1

    @cached_property
    def grids(self) -> tuple[NDArray[np.int64], NDArray[np.int64], NDArray[np.int64], NDArray[np.int64]]:
        """``(h1, a1, h2, a2)``: the goals of each count at every cell, broadcastable against ``p``."""
        n = self.p.shape[0]
        g = np.arange(n, dtype=np.int64)
        return g[:, None, None, None], g[None, :, None, None], g[None, None, :, None], g[None, None, None, :]

    def goals(self, period: str) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
        """(home goals, away goals) of ``period`` (``FT``, ``1H``, ``2H``) at every cell, broadcastable against ``p``."""
        h1, a1, h2, a2 = self.grids
        if period == "FT":
            return h1 + h2, a1 + a2
        if period == "1H":
            return h1, a1
        if period == "2H":
            return h2, a2
        raise ValueError(f"a period is FT, 1H or 2H, not {period!r}")

    def expectation(self, values: NDArray[np.float64] | NDArray[np.int64] | NDArray[np.bool_]) -> float:
        """E[values] under the joint; ``values`` broadcasts against ``p``."""
        return float((self.p * values).sum())

    def score_matrix(self, period: str = "FT") -> NDArray[np.float64]:
        """P(home = i, away = j) of the period: (2M+1)x(2M+1) at full time, (M+1)x(M+1) for a half."""
        if period == "1H":
            return np.asarray(self.p.sum(axis=(2, 3)), dtype=np.float64)
        if period == "2H":
            return np.asarray(self.p.sum(axis=(0, 1)), dtype=np.float64)
        if period != "FT":
            raise ValueError(f"a period is FT, 1H or 2H, not {period!r}")
        n = self.p.shape[0]
        home, away = (np.broadcast_to(g, self.p.shape).ravel() for g in self.goals("FT"))
        out = np.zeros((2 * n - 1, 2 * n - 1))
        np.add.at(out, (home, away), self.p.ravel())
        return out


def _pmf(lam: float, n: int) -> NDArray[np.float64]:
    return np.asarray(poisson.pmf(np.arange(n), lam), dtype=np.float64)


def build(intensities: HalfIntensities, *, rho: float | None = None, max_goals: int = MAX_HALF_GOALS, source: str = "") -> JointScore:
    """The joint distribution of independent Poisson halves, Dixon-Coles corrected at full time when ``rho`` is given."""
    if max_goals < 2:
        raise ValueError("max_goals must be at least 2: the Dixon-Coles cells and a 2-0 need room")
    n = max_goals + 1
    h1, a1, h2, a2 = (_pmf(x, n) for x in intensities.as_tuple())
    p = h1[:, None, None, None] * a1[None, :, None, None] * h2[None, None, :, None] * a2[None, None, None, :]
    kept = float(p.sum())
    tail = max(0.0, 1.0 - kept)
    if rho is not None:
        lh, la = intensities.home, intensities.away
        if not dc_valid(lh, la, rho):
            raise InvalidCorrectionError(f"Dixon-Coles correction rho={rho:.3f} is invalid for expected goals {lh:.2f}-{la:.2f}")
        tau = {(0, 0): 1.0 - lh * la * rho, (0, 1): 1.0 + lh * rho, (1, 0): 1.0 + la * rho, (1, 1): 1.0 - rho}
        for (fh, fa), factor in tau.items():
            # every split of the full-time score (fh, fa) into two halves
            for i in range(fh + 1):
                for j in range(fa + 1):
                    p[i, j, fh - i, fa - j] *= factor
    p = np.clip(p, 0.0, None)
    p /= p.sum()
    return JointScore(np.asarray(p, dtype=np.float64), intensities, rho, tail, source)


def from_goal_model(model: GoalModel, home_id: int, away_id: int, *, neutral: bool = False, halves: HalfIntensities | None = None,
                    max_goals: int = MAX_HALF_GOALS) -> JointScore:
    """The joint of a fitted full-time model (Poisson or Dixon-Coles), split by the half fits' shares when ``halves`` is given and by the
    documented constants otherwise."""
    lh, la = model.lambdas(home_id, away_id, neutral=neutral)
    split = rescale_to_full_time(halves, lh, la) if halves is not None else split_full_time(lh, la)
    rho = model.rho if model.kind in DC_KINDS else None
    how = "half fits' shares" if halves is not None else "documented split"
    return build(split, rho=rho, max_goals=max_goals, source=f"{model.kind} ({how})")
