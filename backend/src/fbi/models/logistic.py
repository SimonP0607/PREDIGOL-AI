"""Multinomial logistic regression for 1X2: the first feature-based model family.

softmax(W x + b) over (home, draw, away) with an L2 penalty on W, fitted by
L-BFGS with the exact gradient. Features are standardised on the training
set (mean and sd stored with the model), so the penalty treats them alike.
A missing feature value is replaced by its training mean - and the fixture
is declined instead when a REQUIRED feature is missing (the caller's rule).

It is a baseline for the feature engine, not a claim: if Elo difference and
pi-ratings already say everything, the extra features get small weights and
the model scores like the ordered logit. That is a result worth knowing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize


@dataclass(frozen=True, slots=True)
class LogisticModel:
    features: tuple[str, ...]
    mean: NDArray[np.float64]
    sd: NDArray[np.float64]
    weights: NDArray[np.float64]
    """(3, k), on standardised features"""
    intercept: NDArray[np.float64]
    """(3,)"""
    l2: float
    n_train: int
    converged: bool
    loglik: float

    def predict(self, x: Sequence[float | None]) -> tuple[float, float, float]:
        if len(x) != len(self.features):
            raise ValueError(f"expected {len(self.features)} features, got {len(x)}")
        v = np.array([self.mean[i] if xi is None else float(xi) for i, xi in enumerate(x)])
        z = self.weights @ ((v - self.mean) / self.sd) + self.intercept
        z -= z.max()
        e = np.exp(z)
        p = e / e.sum()
        return float(p[0]), float(p[1]), float(p[2])


def _objective(theta: NDArray[np.float64], xs: NDArray[np.float64], onehot: NDArray[np.float64], l2: float
               ) -> tuple[float, NDArray[np.float64]]:
    """Mean negative log-likelihood + 0.5 * l2 * ||W||^2 / n, and its exact gradient."""
    k = xs.shape[1]
    w = theta[: 3 * k].reshape(3, k)
    b = theta[3 * k:]
    z = xs @ w.T + b
    z -= z.max(axis=1, keepdims=True)
    e = np.exp(z)
    p = e / e.sum(axis=1, keepdims=True)
    n = xs.shape[0]
    nll = -float(np.log(np.clip((p * onehot).sum(axis=1), 1e-15, 1.0)).sum()) / n
    value = nll + 0.5 * l2 * float((w ** 2).sum()) / n
    g = (p - onehot) / n
    grad_w = g.T @ xs + l2 * w / n
    grad_b = g.sum(axis=0)
    return value, np.concatenate([grad_w.ravel(), grad_b])


def fit_logistic(rows: Sequence[Sequence[float | None]], y: Sequence[int], *, features: Sequence[str],
                 l2: float = 1.0) -> LogisticModel:
    """``y``: 0 home, 1 draw, 2 away. Rows may contain None (imputed with the training mean)."""
    raw = np.array([[np.nan if v is None else float(v) for v in row] for row in rows], dtype=np.float64)
    if raw.ndim != 2 or raw.shape[1] != len(features):
        raise ValueError("every row needs one value per feature")
    if raw.shape[0] < 3 * (raw.shape[1] + 1):
        raise ValueError("too few training rows for the number of features")
    mean = np.nanmean(np.where(np.isnan(raw).all(axis=0), 0.0, raw), axis=0)
    filled = np.where(np.isnan(raw), mean, raw)
    sd = filled.std(axis=0)
    sd = np.where(sd > 1e-12, sd, 1.0)
    xs = (filled - mean) / sd
    onehot = np.eye(3)[np.asarray(y, dtype=np.int64)]
    k = xs.shape[1]
    base = np.log(np.clip(onehot.mean(axis=0), 1e-6, 1.0))
    theta0 = np.concatenate([np.zeros(3 * k), base - base.mean()])
    res = minimize(_objective, theta0, args=(xs, onehot, l2), jac=True, method="L-BFGS-B",
                   options={"maxiter": 500, "gtol": 1e-8})
    return LogisticModel(tuple(features), mean, sd, res.x[: 3 * k].reshape(3, k), res.x[3 * k:], l2,
                         int(xs.shape[0]), bool(res.success), -float(res.fun) * xs.shape[0])
