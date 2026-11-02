"""Counts of events in a match as distributions (plan F10): the goals of a half, the corners, the cards.

Goals are close to Poisson. Corners and cards are not: their variance is larger than their mean (over-dispersion), which is why the plan asks
for a negative binomial ("Forecasting the number of corner kicks", arXiv 2112.13001). The parameterisation is NB2: a mean ``mu`` and a
dispersion ``phi >= 0`` with variance ``mu + phi * mu**2``; ``phi = 0`` is the Poisson. Everything here is a pure function of numbers: no
database, no clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.optimize import minimize_scalar
from scipy.special import gammaln

MAX_COUNT = 40
"""Counts up to 40 for one team (or 60 for a total). A team's corners rarely pass 20; the mass beyond is returned, never hidden."""
PHI_FLOOR = 2e-3
"""Below this dispersion the count is Poisson for every practical purpose (at a mean of 10 it inflates the variance by 2 %). Poisson data give a
maximum-likelihood dispersion of a few 1e-4 from noise alone, so a floor lower than this would call that over-dispersion."""
PHI_CEILING = 4.0


def nb_pmf(mean: float, phi: float, kmax: int = MAX_COUNT) -> NDArray[np.float64]:
    """P(X = k) for k = 0..kmax. The mass beyond ``kmax`` is ``1 - pmf.sum()``."""
    if not mean > 0.0:
        raise ValueError(f"the mean of a count must be positive, got {mean!r}")
    if phi < 0.0:
        raise ValueError("the dispersion cannot be negative")
    k = np.arange(kmax + 1, dtype=np.float64)
    if phi < PHI_FLOOR:
        logp = k * np.log(mean) - mean - gammaln(k + 1.0)
    else:
        r = 1.0 / phi
        logp = gammaln(k + r) - gammaln(r) - gammaln(k + 1.0) + r * np.log(r / (r + mean)) + k * np.log(mean / (r + mean))
    return np.asarray(np.exp(logp), dtype=np.float64)


def tail_mass(pmf: NDArray[np.float64]) -> float:
    return max(0.0, 1.0 - float(pmf.sum()))


def normalised(pmf: NDArray[np.float64]) -> NDArray[np.float64]:
    total = float(pmf.sum())
    if total <= 0.0:
        raise ValueError("not a distribution")
    return np.asarray(pmf / total, dtype=np.float64)


def convolve(a: NDArray[np.float64], b: NDArray[np.float64]) -> NDArray[np.float64]:
    """The distribution of the sum of two independent counts."""
    return np.asarray(np.convolve(a, b), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Line:
    """What a line asks of a count: ``over`` is P(X > line), ``push`` is P(X = line) (only an integer line has one), ``under`` the rest."""
    over: float
    push: float
    under: float


def over_under(pmf: NDArray[np.float64], line: float) -> Line:
    """Over/Under a half-integer or integer line. A quarter line is two half-stakes: the caller splits it, the distribution is the same."""
    pmf = normalised(pmf)
    k = np.arange(pmf.size, dtype=np.float64)
    over = float(pmf[k > line].sum())
    push = float(pmf[k == line].sum()) if float(line).is_integer() else 0.0
    return Line(over, push, max(0.0, 1.0 - over - push))


def difference_probs(home: NDArray[np.float64], away: NDArray[np.float64]) -> tuple[float, float, float]:
    """P(home > away), P(home = away), P(home < away) for two independent counts (the "1X2" of corners or cards)."""
    home, away = normalised(home), normalised(away)
    joint = np.outer(home, away)
    return float(np.tril(joint, -1).sum()), float(np.trace(joint)), float(np.triu(joint, 1).sum())


def handicap_probs(home: NDArray[np.float64], away: NDArray[np.float64], handicap: float) -> Line:
    """The home count plus ``handicap`` against the away count: ``over`` is P(home + h > away) (the home side wins), ``under`` the away side."""
    home, away = normalised(home), normalised(away)
    joint = np.outer(home, away)
    i = np.arange(home.size, dtype=np.float64)[:, None]
    j = np.arange(away.size, dtype=np.float64)[None, :]
    margin = i + handicap - j
    win = float(joint[margin > 0].sum())
    push = float(joint[margin == 0].sum())
    return Line(win, push, max(0.0, 1.0 - win - push))


def nb_loglik(y: NDArray[np.float64], mu: NDArray[np.float64], phi: float, w: NDArray[np.float64] | None = None) -> float:
    """The weighted log-likelihood of counts ``y`` under NB2 with means ``mu`` and dispersion ``phi`` (Poisson below the floor)."""
    weights = np.ones_like(y) if w is None else w
    if phi < PHI_FLOOR:
        ll = y * np.log(mu) - mu - gammaln(y + 1.0)
    else:
        r = 1.0 / phi
        ll = gammaln(y + r) - gammaln(r) - gammaln(y + 1.0) + r * np.log(r / (r + mu)) + y * np.log(mu / (r + mu))
    return float((weights * ll).sum())


def fit_dispersion(y: ArrayLike, mu: ArrayLike, w: ArrayLike | None = None) -> float:
    """The maximum-likelihood NB2 dispersion given the means (0.0 when the data are not over-dispersed).

    Fit on predictions made WITHOUT the match in the training window (out of sample), the dispersion is honest; fit on the means of the model's
    own training window it is a little too small, because those means have already bent towards the data.
    """
    yy = np.asarray(y, dtype=np.float64)
    mm = np.maximum(np.asarray(mu, dtype=np.float64), 1e-9)
    if yy.size == 0 or yy.size != mm.size:
        raise ValueError("counts and means must be the same, non-zero, length")
    ww = None if w is None else np.asarray(w, dtype=np.float64)

    def negative(log_phi: float) -> float:
        return -nb_loglik(yy, mm, float(np.exp(log_phi)), ww)

    res = minimize_scalar(negative, bounds=(np.log(PHI_FLOOR / 10.0), np.log(PHI_CEILING)), method="bounded",
                          options={"xatol": 1e-4})
    phi = float(np.exp(res.x))
    return 0.0 if phi < PHI_FLOOR else phi


def mean_log_score(pmfs: Sequence[NDArray[np.float64]], observed: Sequence[int]) -> float:
    """The mean log probability each distribution gave to the count that happened (higher is better; a count beyond the support scores the floor)."""
    if not pmfs or len(pmfs) != len(observed):
        raise ValueError("one distribution per observed count")
    total = 0.0
    for pmf, k in zip(pmfs, observed, strict=True):
        p = float(pmf[k]) if 0 <= k < pmf.size else 0.0
        total += float(np.log(max(p, 1e-12)))
    return total / len(observed)
