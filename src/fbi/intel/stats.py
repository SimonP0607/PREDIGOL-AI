"""The few statistics the decision layer needs, in numpy only (no scikit-learn in the production image).

* ``fit_logistic``  L2-penalised logistic regression by Newton-Raphson (IRLS). The penalty is on the slopes only and
  is small (1.0) against samples of thousands: it keeps a near-separable or collinear fit finite, nothing more.
* ``logloss`` / ``brier`` / ``ece``  scoring rules on probabilities of a binary outcome; ``ece`` with ten equal-width
  bins, weighted by their share of the sample.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

EPS = 1e-6
Arr = NDArray[np.float64]


def logit(p: Arr | Sequence[float] | float) -> Arr:
    x = np.clip(np.asarray(p, dtype=np.float64), EPS, 1 - EPS)
    return np.asarray(np.log(x / (1 - x)), dtype=np.float64)


def sigmoid(z: Arr | float) -> Arr:
    z = np.clip(np.asarray(z, dtype=np.float64), -40.0, 40.0)
    return np.asarray(1.0 / (1.0 + np.exp(-z)), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Logistic:
    """``p = sigmoid(w[0] + w[1:] . x)``."""

    w: tuple[float, ...]
    iterations: int
    converged: bool

    def predict(self, x: Arr) -> Arr:
        x2 = np.atleast_2d(np.asarray(x, dtype=np.float64))
        if x2.shape[0] == 1 and len(self.w) - 1 != x2.shape[1]:
            x2 = x2.T
        w = np.asarray(self.w)
        return sigmoid(w[0] + x2 @ w[1:])


def fit_logistic(x: Arr, y: Arr, *, l2: float = 1.0, weights: Arr | None = None, max_iter: int = 60,
                 tol: float = 1e-9) -> Logistic:
    """Newton-Raphson on the penalised log likelihood. ``x``: n x k, ``y`` in [0, 1] (fractional allowed)."""
    xm = np.asarray(x, dtype=np.float64)
    if xm.ndim == 1:
        xm = xm.reshape(-1, 1)
    yv = np.asarray(y, dtype=np.float64)
    n, k = xm.shape
    if n == 0:
        raise ValueError("no data to fit")
    sw = np.ones(n) if weights is None else np.asarray(weights, dtype=np.float64)
    design = np.column_stack([np.ones(n), xm])
    w = np.zeros(k + 1)
    penalty = np.r_[0.0, np.full(k, l2)]
    converged = False
    iterations = 0
    for iterations in range(1, max_iter + 1):  # noqa: B007 - the count is returned
        p = sigmoid(design @ w)
        grad = design.T @ (sw * (p - yv)) + penalty * w
        hess = (design * (sw * p * (1 - p))[:, None]).T @ design + np.diag(penalty)
        step = np.linalg.solve(hess + 1e-12 * np.eye(k + 1), grad)
        w = w - step
        if float(np.max(np.abs(step))) < tol:
            converged = True
            break
    return Logistic(tuple(float(v) for v in w), iterations, converged)


def logloss(y: Arr, p: Arr) -> float:
    yv, pv = np.asarray(y, dtype=np.float64), np.clip(np.asarray(p, dtype=np.float64), EPS, 1 - EPS)
    if yv.size == 0:
        return float("nan")
    return float(-np.mean(yv * np.log(pv) + (1 - yv) * np.log(1 - pv)))


def brier(y: Arr, p: Arr) -> float:
    yv, pv = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64)
    if yv.size == 0:
        return float("nan")
    return float(np.mean((pv - yv) ** 2))


def ece(y: Arr, p: Arr, bins: int = 10) -> float:
    yv, pv = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64)
    if yv.size == 0:
        return float("nan")
    idx = np.minimum((pv * bins).astype(int), bins - 1)
    out = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            out += float(m.mean()) * abs(float(pv[m].mean()) - float(yv[m].mean()))
    return out


def reliability(y: Arr, p: Arr, bins: int = 10, min_n: int = 30) -> list[dict[str, Any]]:
    """Calibration table: per band of predicted probability, n, mean prediction and observed frequency."""
    yv, pv = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64)
    idx = np.minimum((pv * bins).astype(int), bins - 1)
    out: list[dict[str, Any]] = []
    for b in range(bins):
        m = idx == b
        if int(m.sum()) >= min_n:
            out.append({"band": f"{b / bins:.1f}-{(b + 1) / bins:.1f}", "n": int(m.sum()),
                        "p": round(float(pv[m].mean()), 4), "hit": round(float(yv[m].mean()), 4)})
    return out


def bootstrap_mean_ci(values: Arr, groups: Arr, *, reps: int = 400, seed: int = 7) -> tuple[float, float]:
    """95 % interval of a mean by resampling whole groups (days), so dependence inside a day is respected."""
    v = np.asarray(values, dtype=np.float64)
    g = np.asarray(groups)
    uniq = np.unique(g)
    if v.size == 0 or uniq.size == 0:
        return float("nan"), float("nan")
    sums = {u: (float(v[g == u].sum()), int((g == u).sum())) for u in uniq}
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(reps):
        draw = rng.integers(0, uniq.size, uniq.size)
        s = sum(sums[uniq[j]][0] for j in draw)
        n = sum(sums[uniq[j]][1] for j in draw)
        means.append(s / n if n else 0.0)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)
