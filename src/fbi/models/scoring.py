"""From goal expectations to market probabilities, by summing a score matrix."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.special import gammaln
from scipy.stats import poisson

MAX_GOALS = 10
"""Scores up to 10-10. The mass beyond is renormalised, and it is recorded:
for typical lambdas it is below 1e-5."""

_GOALS = np.arange(MAX_GOALS + 1)
_LOG_FACT = gammaln(_GOALS + 1.0)
_TOTAL = _GOALS[:, None] + _GOALS[None, :]
_OVER_2_5 = _TOTAL > 2.5
_HOME_WIN = _GOALS[:, None] > _GOALS[None, :]
_AWAY_WIN = _GOALS[:, None] < _GOALS[None, :]
_DRAW = _GOALS[:, None] == _GOALS[None, :]
_BOTH_SCORE = (_GOALS[:, None] > 0) & (_GOALS[None, :] > 0)

MARKET_ROWS: tuple[tuple[str, str, float], ...] = (
    ("1X2", "Home", 0.0),
    ("1X2", "Draw", 0.0),
    ("1X2", "Away", 0.0),
    ("OU", "Over", 2.5),
    ("OU", "Under", 2.5),
    ("BTTS", "Yes", 0.0),
    ("BTTS", "No", 0.0),
)
"""Every (market, selection, line) a goal model prices, in a fixed order."""


@dataclass(frozen=True, slots=True)
class MarketProbabilities:
    home: float
    draw: float
    away: float
    over_2_5: float
    under_2_5: float
    btts_yes: float
    btts_no: float
    lambda_home: float
    lambda_away: float
    truncated_mass: float

    def as_1x2(self) -> tuple[float, float, float]:
        return self.home, self.draw, self.away

    def as_rows(self) -> tuple[float, ...]:
        """Probabilities in MARKET_ROWS order."""
        return (self.home, self.draw, self.away, self.over_2_5, self.under_2_5, self.btts_yes, self.btts_no)


def poisson_matrix(lam_home: float, lam_away: float, max_goals: int = MAX_GOALS) -> NDArray[np.float64]:
    goals = np.arange(max_goals + 1)
    ph = poisson.pmf(goals, lam_home)
    pa = poisson.pmf(goals, lam_away)
    return np.outer(ph, pa).astype(np.float64)


def dc_tau(matrix: NDArray[np.float64], lam_home: float, lam_away: float, rho: float) -> NDArray[np.float64]:
    """Dixon-Coles (1997) low-score dependence: rescale 0-0, 1-0, 0-1, 1-1."""
    m = matrix.copy()
    m[0, 0] *= 1.0 - lam_home * lam_away * rho
    m[0, 1] *= 1.0 + lam_home * rho
    m[1, 0] *= 1.0 + lam_away * rho
    m[1, 1] *= 1.0 - rho
    return m


def from_matrix(m: NDArray[np.float64], lam_home: float, lam_away: float) -> MarketProbabilities:
    total = float(m.sum())
    if total <= 0 or np.any(m < -1e-12):
        raise ValueError("score matrix is not a distribution")
    m = np.clip(m, 0.0, None) / total
    idx = np.arange(m.shape[0])
    home = float(np.tril(m, -1).sum())
    away = float(np.triu(m, 1).sum())
    draw = float(np.trace(m))
    total_goals = idx[:, None] + idx[None, :]
    over = float(m[total_goals > 2.5].sum())
    btts = float(m[1:, 1:].sum())
    return MarketProbabilities(home, draw, away, over, 1.0 - over, btts, 1.0 - btts,
                               lam_home, lam_away, max(0.0, 1.0 - total))


def matrices_batch(lam_home: NDArray[np.float64], lam_away: NDArray[np.float64],
                   rho: NDArray[np.float64] | None = None) -> NDArray[np.float64]:
    """Normalised score matrices for many (lambda_home, lambda_away[, rho]) at once: shape (n, 11, 11)."""
    lh = np.asarray(lam_home, dtype=np.float64)[:, None]
    la = np.asarray(lam_away, dtype=np.float64)[:, None]
    ph = np.exp(_GOALS[None, :] * np.log(lh) - lh - _LOG_FACT[None, :])
    pa = np.exp(_GOALS[None, :] * np.log(la) - la - _LOG_FACT[None, :])
    m = ph[:, :, None] * pa[:, None, :]
    if rho is not None:
        r = np.asarray(rho, dtype=np.float64)
        lh1, la1 = lh[:, 0], la[:, 0]
        m[:, 0, 0] *= 1.0 - lh1 * la1 * r
        m[:, 0, 1] *= 1.0 + lh1 * r
        m[:, 1, 0] *= 1.0 + la1 * r
        m[:, 1, 1] *= 1.0 - r
    m = np.clip(m, 0.0, None)
    m /= m.sum(axis=(1, 2), keepdims=True)
    return np.asarray(m, dtype=np.float64)


def market_rows_batch(lam_home: NDArray[np.float64], lam_away: NDArray[np.float64],
                      rho: NDArray[np.float64] | None = None) -> NDArray[np.float64]:
    """The same arithmetic as ``from_matrix``, for many (lambda_home, lambda_away) pairs at once.

    Returns shape (n, 7) in MARKET_ROWS order. Used for interval draws, where
    the scalar path would build hundreds of matrices one by one. A test holds
    the two paths equal.
    """
    m = matrices_batch(lam_home, lam_away, rho)
    home = m[:, _HOME_WIN].sum(axis=1)
    draw = m[:, _DRAW].sum(axis=1)
    away = m[:, _AWAY_WIN].sum(axis=1)
    over = m[:, _OVER_2_5].sum(axis=1)
    btts = m[:, _BOTH_SCORE].sum(axis=1)
    return np.stack([home, draw, away, over, 1.0 - over, btts, 1.0 - btts], axis=1)
