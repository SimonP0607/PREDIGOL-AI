"""Elo -> 1X2 through an ordered logit, fitted by maximum likelihood.

The Elo rating difference says who is stronger, not how often a match is
drawn. The ordered logit adds exactly that: with latent strength
s = beta * elo_diff + h * (not neutral),

    P(away)          = sigmoid(theta1 - s)
    P(away or draw)  = sigmoid(theta2 - s),   theta1 < theta2
    P(home)          = 1 - sigmoid(theta2 - s)

Four parameters, fitted on training fixtures only. The Elo ratings themselves
come from the walk-forward feature engine, as of each fixture's cut-off.

IDENTIFICATION. Without a neutral-venue match in the training data the home
term and the two thresholds are not separately identified: only theta - home is.
The Hessian then has an exact zero eigenvalue. In that case the home term is
fixed at 0 (the thresholds absorb home advantage) and the model refuses to
price a neutral-venue fixture rather than silently counting a home advantage
that does not exist there.

Internally the rating difference is measured in hundreds of Elo points so that
all four parameters are of order one: the optimiser and the finite-difference
Hessian both behave badly when one parameter lives three orders of magnitude
below the others. ``beta`` is reported per Elo point.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.special import expit

SCALE = 100.0
INTERVAL_LEVEL = 0.9


@dataclass(frozen=True, slots=True)
class OLogitObs:
    elo_diff: float
    neutral: bool
    outcome: int  # 0 away, 1 draw, 2 home


@dataclass
class OLogitModel:
    beta: float
    home: float
    theta1: float
    theta2: float
    n_train: int
    converged: bool
    loglik: float
    cov: NDArray[np.float64] | None = None
    """Covariance of the INTERNAL parameters (beta per 100 Elo points, home, theta1, theta2).
    Row/column 1 is zero when the home term was not identified."""
    home_identified: bool = True

    def _internal(self) -> NDArray[np.float64]:
        return np.array([self.beta * SCALE, self.home, self.theta1, self.theta2])

    def predict(self, elo_diff: float, *, neutral: bool = False) -> tuple[float, float, float]:
        """(home, draw, away)."""
        if neutral and not self.home_identified:
            raise ValueError("no neutral-venue match in training: home advantage is not separable")
        return _probs(self._internal(), elo_diff / SCALE, neutral)

    def interval(self, elo_diff: float, *, neutral: bool = False, draws: int = 200,
                 level: float = INTERVAL_LEVEL,
                 seed: int = 7) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
        """(lo, hi) for (home, draw, away), or None when there is no covariance."""
        if self.cov is None:
            return None
        rng = np.random.default_rng(seed)
        try:
            samples = rng.multivariate_normal(self._internal(), self.cov, size=draws, check_valid="raise")
        except (np.linalg.LinAlgError, ValueError):
            return None
        point = np.array(self.predict(elo_diff, neutral=neutral))
        out = np.array([_probs(s, elo_diff / SCALE, neutral) for s in samples])
        q = (1 - level) / 2
        return (np.minimum(np.quantile(out, q, axis=0), point), np.maximum(np.quantile(out, 1 - q, axis=0), point))


def _probs(theta: NDArray[np.float64], x: float, neutral: bool) -> tuple[float, float, float]:
    beta, home, t1, t2 = theta
    lo, hi = min(t1, t2), max(t1, t2)
    s = beta * x + (0.0 if neutral else home)
    p_away = float(expit(lo - s))
    p_away_or_draw = float(expit(hi - s))
    return 1.0 - p_away_or_draw, p_away_or_draw - p_away, p_away


def _nll(theta: NDArray[np.float64], x: NDArray[np.float64], nt: NDArray[np.float64], y: NDArray[np.int64]) -> float:
    beta, home, t1, t2 = theta
    if t2 <= t1:
        return 1e12
    s = beta * x + home * nt
    p_away = expit(t1 - s)
    p_ad = expit(t2 - s)
    p = np.where(y == 0, p_away, np.where(y == 1, p_ad - p_away, 1.0 - p_ad))
    return float(-np.log(np.clip(p, 1e-12, 1.0)).sum())


def _numeric_hessian(theta: NDArray[np.float64], x: NDArray[np.float64], nt: NDArray[np.float64],
                     y: NDArray[np.int64]) -> NDArray[np.float64]:
    """Central second differences of the negative log-likelihood (four parameters: cheap)."""
    k = len(theta)
    step = 1e-4
    hess = np.empty((k, k))
    for i in range(k):
        for j in range(i, k):
            ei = np.zeros(k)
            ej = np.zeros(k)
            ei[i], ej[j] = step, step
            f = (_nll(theta + ei + ej, x, nt, y) - _nll(theta + ei - ej, x, nt, y)
                 - _nll(theta - ei + ej, x, nt, y) + _nll(theta - ei - ej, x, nt, y))
            hess[i, j] = hess[j, i] = f / (4 * step * step)
    return hess


def _covariance(hess: NDArray[np.float64]) -> NDArray[np.float64] | None:
    try:
        chol = np.linalg.cholesky(hess)
    except np.linalg.LinAlgError:
        return None
    inv_chol = np.linalg.inv(chol)
    return np.asarray(inv_chol.T @ inv_chol, dtype=np.float64)


def fit_ologit(obs: Sequence[OLogitObs]) -> OLogitModel:
    if len(obs) < 50:
        raise ValueError("an ordered logit on fewer than 50 matches is not worth reporting")
    x = np.array([o.elo_diff for o in obs], dtype=np.float64) / SCALE
    nt = np.array([0.0 if o.neutral else 1.0 for o in obs])
    y = np.array([o.outcome for o in obs])
    home_identified = bool(nt.min() < 0.5 < nt.max())
    free = [0, 1, 2, 3] if home_identified else [0, 2, 3]
    start = np.array([0.4, 0.3, -0.5, 0.6]) if home_identified else np.array([0.4, 0.0, -0.8, 0.3])

    def full(sub: NDArray[np.float64]) -> NDArray[np.float64]:
        theta = start.copy()
        theta[free] = sub
        return theta

    def nll_sub(sub: NDArray[np.float64]) -> float:
        return _nll(full(sub), x, nt, y)

    res = minimize(nll_sub, start[free], method="BFGS", options={"maxiter": 2000, "gtol": 1e-6})
    theta = full(np.asarray(res.x, dtype=np.float64))
    hess = _numeric_hessian(theta, x, nt, y)[np.ix_(free, free)]
    sub_cov = _covariance(hess)
    cov: NDArray[np.float64] | None = None
    if sub_cov is not None:
        cov = np.zeros((4, 4))
        cov[np.ix_(free, free)] = sub_cov
    b, h, t1, t2 = (float(v) for v in theta)
    # "precision loss" at a point with a positive-definite Hessian is still a minimum.
    return OLogitModel(b / SCALE, h, t1, t2, len(obs), bool(res.success) or cov is not None, float(-res.fun),
                       cov, home_identified)
