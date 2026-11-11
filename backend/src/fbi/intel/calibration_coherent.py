"""INT-A02 (LAB, IA-036): a coherent multiclass calibration of a market, ``cal-coherent-v1`` - a challenger, registered nowhere.

WHY. ``cal-logit2-v1`` (``fbi.intel.calibration``) calibrates each selection on its own, so the calibrated outcomes of one market do
not add up to one (measured on 10 Nov 2026: a median 3.2 points over one in 1X2, 4.4 in both teams to score, 7.6 in over/under 2.5),
and the common view (``fbi.forecasting.market_view``) divides them by their sum afterwards. This calibrator adds up to one BY
CONSTRUCTION: a logarithmic pool of the model and the de-vigged market with one term per outcome (Kull et al. 2019, Dirichlet
calibration; Ranjan and Gneiting 2010, combining probability forecasts),

    p_k  proportional to  exp(a_k + b * log q_k + c * log m_k)        k: the outcomes of the market, a_reference = 0

q the model's probability, m the market's without its margin. One fit per (market, model) by penalised multinomial maximum
likelihood: Newton-Raphson with step halving, the same small L2 penalty as ``fbi.intel.stats.fit_logistic`` (1.0, on the slopes b and
c only; the intercepts are free). The reference outcome's intercept is fixed at 0 so that the intercepts are identifiable. Neither q
nor m needs to add up to one: a constant added to every log of a row cancels in the softmax.

With two outcomes it IS ``cal-logit2-v1`` of one side with the other at its complement: ``logit p_1 = (a_1 - a_2) + b logit q_1 +
c logit m_1`` (``tests/unit/test_calibration_coherent.py`` holds the two fits equal).

THE MARKET'S SHARE of the pool is ``c / (b + c)``: 0 the model alone, 1 the market alone, as the single weight of
``fbi.research.blend``; here ``b + c`` is free as well, so the pool can also sharpen or soften the two.

Also here, pure, what the evaluation of protocol ``proto-int-a02-v1`` (``fbi.research.protocol.A02``) needs: the multiclass log loss,
the expected calibration error over bins of equal size and its reliability table, the training rule of the walk-forward (a day is
fitted only on matches that kicked off and were settled before it began) and the mean of daily values with its interval by bootstrap
of days.

It decides nothing: no model, forecast, calibrator in use, pick, threshold or agent reads it. Pure: no database, no clock; numpy only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

VERSION: Final = "cal-coherent-v1"
L2: Final = 1.0
"""The penalty on the slopes b and c: ``fbi.intel.calibration.L2``, so the two calibrators are penalised alike."""
EPS: Final = 1e-6
"""Probabilities are clipped to [EPS, 1] before their log (``fbi.intel.stats.EPS``)."""
BINS: Final = 10
MAX_ITER: Final = 100
TOL: Final = 1e-9
MAX_HALVINGS: Final = 40
SUM_TOLERANCE: Final = 1e-9
"""A market adds up to one when its sum is within this of one (the protocol's ``|suma - 1| <= 1e-9``)."""

Arr = NDArray[np.float64]
IntArr = NDArray[np.int64]
BoolArr = NDArray[np.bool_]


def _matrix(x: Arr | Sequence[Sequence[float]], name: str) -> Arr:
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] < 2:
        raise ValueError(f"{name} must be a matrix with one column per outcome (two or more)")
    if not np.all(np.isfinite(a)) or np.any(a <= 0.0):
        raise ValueError(f"{name} must hold probabilities above zero")
    return a


def _labels(y: IntArr | Sequence[int], n: int, k: int) -> IntArr:
    v = np.asarray(y, dtype=np.int64)
    if v.shape != (n,):
        raise ValueError("y must hold one outcome index per row")
    if v.size and (int(v.min()) < 0 or int(v.max()) >= k):
        raise ValueError(f"y must be outcome indices in [0, {k})")
    return v


def _design(q: Arr, m: Arr, reference: int) -> Arr:
    """(n, K, K + 1): per row and outcome, the one-hot of the outcome's intercept (none for the reference), log q and log m."""
    n, k = q.shape
    x = np.zeros((n, k, k + 1), dtype=np.float64)
    for col, j in enumerate(j for j in range(k) if j != reference):
        x[:, j, col] = 1.0
    x[:, :, k - 1] = np.log(np.clip(q, EPS, 1.0))
    x[:, :, k] = np.log(np.clip(m, EPS, 1.0))
    return x


def _softmax(eta: Arr) -> Arr:
    z = eta - eta.max(axis=1, keepdims=True)
    e = np.exp(z)
    return np.asarray(e / e.sum(axis=1, keepdims=True), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class CoherentFit:
    """``p_k proportional to exp(a_k + b log q_k + c log m_k)`` with ``a[reference] = 0``."""

    intercepts: tuple[float, ...]
    b: float
    c: float
    reference: int
    n: int
    iterations: int
    converged: bool

    @property
    def outcomes(self) -> int:
        return len(self.intercepts)

    @property
    def market_share(self) -> float | None:
        """``c / (b + c)``: the market's share of the pool (None when ``b + c`` is zero)."""
        s = self.b + self.c
        return None if abs(s) < 1e-12 else self.c / s

    def theta(self) -> Arr:
        free = [a for j, a in enumerate(self.intercepts) if j != self.reference]
        return np.asarray([*free, self.b, self.c], dtype=np.float64)

    def predict(self, q: Arr | Sequence[Sequence[float]], m: Arr | Sequence[Sequence[float]]) -> Arr:
        return predict(self, q, m)

    def as_json(self) -> dict[str, Any]:
        share = self.market_share
        return {"version": VERSION, "intercepts": [round(a, 6) for a in self.intercepts], "b": round(self.b, 6),
                "c": round(self.c, 6), "market_share": None if share is None else round(share, 6), "reference": self.reference,
                "n": self.n, "iterations": self.iterations, "converged": self.converged}


def _objective(x: Arr, y: IntArr, theta: Arr, penalty: Arr) -> tuple[float, Arr]:
    p = _softmax(x @ theta)
    nll = -float(np.sum(np.log(np.clip(p[np.arange(y.size), y], 1e-300, 1.0))))
    return nll + 0.5 * float(np.sum(penalty * theta * theta)), p


def fit(q: Arr | Sequence[Sequence[float]], m: Arr | Sequence[Sequence[float]], y: IntArr | Sequence[int], *,
        l2: float = L2, reference: int | None = None, max_iter: int = MAX_ITER, tol: float = TOL) -> CoherentFit:
    """Penalised multinomial maximum likelihood of the pool. ``q``, ``m``: n x K; ``y``: the index of the outcome that happened.
    ``reference``: the outcome whose intercept is 0 (the last one by default)."""
    qa, ma = _matrix(q, "q"), _matrix(m, "m")
    if qa.shape != ma.shape:
        raise ValueError("q and m must have the same shape")
    n, k = qa.shape
    if n == 0:
        raise ValueError("no data to fit")
    yv = _labels(y, n, k)
    ref = k - 1 if reference is None else reference
    if not 0 <= ref < k:
        raise ValueError(f"reference must be an outcome index in [0, {k})")
    x = _design(qa, ma, ref)
    d = k + 1
    penalty = np.zeros(d, dtype=np.float64)
    penalty[k - 1:] = l2
    theta = np.zeros(d, dtype=np.float64)
    value, p = _objective(x, yv, theta, penalty)
    observed = x[np.arange(n), yv, :].sum(axis=0)
    converged = False
    iterations = 0
    for iterations in range(1, max_iter + 1):  # noqa: B007 - the count is returned
        xbar = np.einsum("nk,nkd->nd", p, x)
        grad = -(observed - xbar.sum(axis=0)) + penalty * theta
        hess = np.einsum("nk,nkd,nke->de", p, x, x) - xbar.T @ xbar + np.diag(penalty)
        step = np.linalg.solve(hess + 1e-12 * np.eye(d), grad)
        t = 1.0
        for _ in range(MAX_HALVINGS):
            cand = theta - t * step
            cand_value, cand_p = _objective(x, yv, cand, penalty)
            if cand_value <= value + 1e-12:
                break
            t /= 2.0
        else:
            break
        moved = float(np.max(np.abs(cand - theta)))
        theta, value, p = cand, cand_value, cand_p
        if moved < tol:
            converged = True
            break
    free = iter(theta[: k - 1].tolist())
    intercepts = tuple(0.0 if j == ref else float(next(free)) for j in range(k))
    return CoherentFit(intercepts, float(theta[k - 1]), float(theta[k]), ref, n, iterations, converged)


def predict(f: CoherentFit, q: Arr | Sequence[Sequence[float]], m: Arr | Sequence[Sequence[float]]) -> Arr:
    """The calibrated market, one row per match: every row adds up to one."""
    qa, ma = _matrix(q, "q"), _matrix(m, "m")
    if qa.shape != ma.shape or qa.shape[1] != f.outcomes:
        raise ValueError(f"q and m must be n x {f.outcomes}")
    return _softmax(_design(qa, ma, f.reference) @ f.theta())


def rescale(p: Arr | Sequence[Sequence[float]]) -> Arr:
    """Each row divided by its sum: what the common view does after calibrating each outcome on its own (``market_view._calibrate``)."""
    a = np.asarray(p, dtype=np.float64)
    return np.asarray(a / a.sum(axis=1, keepdims=True), dtype=np.float64)


def sum_gap(p: Arr | Sequence[Sequence[float]]) -> Arr:
    """``|sum - 1|`` of each row."""
    return np.asarray(np.abs(np.asarray(p, dtype=np.float64).sum(axis=1) - 1.0), dtype=np.float64)


def log_loss(p: Arr | Sequence[Sequence[float]], y: IntArr | Sequence[int]) -> Arr:
    """The multiclass log loss of each row: ``-log p[y]`` (natural log, p clipped to [EPS, 1])."""
    a = np.asarray(p, dtype=np.float64)
    if a.ndim != 2:
        raise ValueError("p must be a matrix with one column per outcome")
    yv = _labels(y, a.shape[0], a.shape[1])
    return np.asarray(-np.log(np.clip(a[np.arange(yv.size), yv], EPS, 1.0)), dtype=np.float64)


def _bins(p: Arr, bins: int) -> list[IntArr]:
    order = np.argsort(p, kind="stable")
    return [np.asarray(b, dtype=np.int64) for b in np.array_split(order, min(bins, p.size)) if b.size]


def ece_equal_mass(y: Arr | Sequence[float], p: Arr | Sequence[float], bins: int = BINS) -> float:
    """Expected calibration error of one outcome over ``bins`` groups of equal size (the predictions sorted; the groups differ by
    one at most): the size-weighted mean of ``|mean prediction - observed frequency|``. NaN without data."""
    yv, pv = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64)
    if yv.shape != pv.shape:
        raise ValueError("y and p must have the same shape")
    if pv.size == 0:
        return float("nan")
    return float(sum(b.size / pv.size * abs(float(pv[b].mean()) - float(yv[b].mean())) for b in _bins(pv, bins)))


def reliability_equal_mass(y: Arr | Sequence[float], p: Arr | Sequence[float], bins: int = BINS) -> list[dict[str, Any]]:
    """The reliability table behind ``ece_equal_mass``: per group, its size, range and mean prediction and the observed frequency."""
    yv, pv = np.asarray(y, dtype=np.float64), np.asarray(p, dtype=np.float64)
    if yv.shape != pv.shape:
        raise ValueError("y and p must have the same shape")
    if pv.size == 0:
        return []
    return [{"bin": i + 1, "n": int(b.size), "p_min": round(float(pv[b].min()), 4), "p_max": round(float(pv[b].max()), 4),
             "p": round(float(pv[b].mean()), 4), "hit": round(float(yv[b].mean()), 4)} for i, b in enumerate(_bins(pv, bins))]


def train_mask(kickoff: Arr | Sequence[float], settled: Arr | Sequence[float], *, cutoff: float, window: float) -> BoolArr:
    """What a fit at ``cutoff`` may learn from (times as seconds since any epoch): matches that kicked off in ``[cutoff - window,
    cutoff)`` and whose result was settled before ``cutoff`` - ``fbi.intel.calibration.train_set``'s rule."""
    k, s = np.asarray(kickoff, dtype=np.float64), np.asarray(settled, dtype=np.float64)
    if k.shape != s.shape:
        raise ValueError("kickoff and settled must have the same shape")
    return np.asarray((s < cutoff) & (k < cutoff) & (k >= cutoff - window), dtype=np.bool_)


def day_bootstrap(values: Arr | Sequence[float], *, reps: int, seed: int, level: float = 0.95) -> tuple[float, float, float]:
    """(mean, low, high): the mean of daily values (one per day: each day counts once) and its percentile interval from resampling
    the days with replacement. NaN without days."""
    v = np.asarray(values, dtype=np.float64)
    if v.size == 0:
        return float("nan"), float("nan"), float("nan")
    if reps < 1 or not 0.0 < level < 1.0:
        raise ValueError("reps must be positive and level in (0, 1)")
    draws = np.random.default_rng(seed).integers(0, v.size, size=(reps, v.size))
    means = v[draws].mean(axis=1)
    lo, hi = np.percentile(means, [50.0 * (1.0 - level), 50.0 * (1.0 + level)])
    return float(v.mean()), float(lo), float(hi)


def cluster_bootstrap(sums: Arr | Sequence[float], counts: Arr | Sequence[float], *, reps: int, seed: int,
                      level: float = 0.95) -> tuple[float, float, float]:
    """(mean, low, high) of a mean over observations grouped in days (each observation counts once), the days resampled whole:
    ``sums`` and ``counts`` hold each day's total and size. NaN without days."""
    s, c = np.asarray(sums, dtype=np.float64), np.asarray(counts, dtype=np.float64)
    if s.shape != c.shape:
        raise ValueError("sums and counts must have the same shape")
    if s.size == 0 or float(c.sum()) <= 0.0:
        return float("nan"), float("nan"), float("nan")
    if reps < 1 or not 0.0 < level < 1.0:
        raise ValueError("reps must be positive and level in (0, 1)")
    draws = np.random.default_rng(seed).integers(0, s.size, size=(reps, s.size))
    means = s[draws].sum(axis=1) / c[draws].sum(axis=1)
    lo, hi = np.percentile(means, [50.0 * (1.0 - level), 50.0 * (1.0 + level)])
    return float(s.sum() / c.sum()), float(lo), float(hi)


def sd(values: Arr | Sequence[float]) -> float:
    """The sample standard deviation (n - 1); NaN with fewer than two values."""
    v = np.asarray(values, dtype=np.float64)
    return float(np.std(v, ddof=1)) if v.size > 1 else float("nan")


def finite(x: float | None) -> float | None:
    """``x`` rounded to six places, None when it is None or not finite (for JSON)."""
    return None if x is None or not math.isfinite(x) else round(x, 6)
