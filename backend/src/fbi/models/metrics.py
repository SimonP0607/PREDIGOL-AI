"""Probability scoring - the numbers a model is judged by.

Accuracy is deliberately absent from the ranking: it rewards picking the
favourite and says nothing about whether 60% meant 60%. Brier and log loss
are proper scoring rules; calibration error says whether stated probabilities
come true at the stated rate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

EPS = 1e-15


def brier(p: NDArray[np.float64], y: NDArray[np.int64]) -> float:
    """Multi-class Brier score: mean over matches of sum_k (p_k - 1[y=k])^2."""
    onehot = np.eye(p.shape[1])[y]
    return float(((p - onehot) ** 2).sum(axis=1).mean())


def log_loss(p: NDArray[np.float64], y: NDArray[np.int64]) -> float:
    return float(-np.log(np.clip(p[np.arange(len(y)), y], EPS, 1.0)).mean())


def per_match_log_loss(p: NDArray[np.float64], y: NDArray[np.int64]) -> NDArray[np.float64]:
    return np.asarray(-np.log(np.clip(p[np.arange(len(y)), y], EPS, 1.0)), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Bucket:
    lower: float
    upper: float
    n: int
    mean_predicted: float | None
    observed_rate: float | None


def calibration(p: NDArray[np.float64], y: NDArray[np.int64], bins: int = 10) -> tuple[float, list[Bucket]]:
    """ECE over all (match, outcome) pairs, one-vs-rest, equal-width bins."""
    probs = p.ravel()
    hits = np.eye(p.shape[1])[y].ravel()
    edges = np.linspace(0.0, 1.0, bins + 1)
    buckets: list[Bucket] = []
    ece = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (probs >= lo) & ((probs < hi) if i < bins - 1 else (probs <= hi))
        n = int(mask.sum())
        if n == 0:
            buckets.append(Bucket(float(lo), float(hi), 0, None, None))
            continue
        mp, orate = float(probs[mask].mean()), float(hits[mask].mean())
        ece += n / len(probs) * abs(mp - orate)
        buckets.append(Bucket(float(lo), float(hi), n, mp, orate))
    return float(ece), buckets


def paired_bootstrap_ci(a: Sequence[float] | NDArray[np.float64], b: Sequence[float] | NDArray[np.float64],
                        *, draws: int = 2000, level: float = 0.95, seed: int = 11) -> tuple[float, float, float]:
    """Mean of (a - b) with a percentile CI, resampling matches with replacement.
    Paired: both scores come from the same matches."""
    d = np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), size=(draws, len(d)))
    means = d[idx].mean(axis=1)
    q = (1 - level) / 2
    return float(d.mean()), float(np.quantile(means, q)), float(np.quantile(means, 1 - q))


def per_match_rps(p: NDArray[np.float64], y: NDArray[np.int64]) -> NDArray[np.float64]:
    """Ranked probability score per match for ORDERED outcomes (home, draw, away).

    RPS = 1/(K-1) * sum_k (P(outcome <= k) - 1[y <= k])^2. Reported for comparison
    with the football forecasting literature; log loss stays the primary score
    (it is the only proper local rule, and RPS's ordering assumption is debated).
    """
    k = p.shape[1]
    cp = np.cumsum(p, axis=1)[:, :-1]
    co = np.cumsum(np.eye(k)[y], axis=1)[:, :-1]
    return np.asarray(((cp - co) ** 2).sum(axis=1) / (k - 1), dtype=np.float64)


def rps(p: NDArray[np.float64], y: NDArray[np.int64]) -> float:
    return float(per_match_rps(p, y).mean())


def block_bootstrap_ci(d: Sequence[float] | NDArray[np.float64], blocks: Sequence[object], *, draws: int = 2000,
                       level: float = 0.95, seed: int = 11) -> tuple[float, float, float, int]:
    """Mean of d with a percentile CI that resamples whole BLOCKS (e.g. match days).

    Matches played on the same day share information and model state, so their
    score differences are not independent; resampling single matches understates
    the uncertainty. Returns (mean, low, high, number of blocks)."""
    x = np.asarray(d, dtype=np.float64)
    keys = list(blocks)
    if len(keys) != len(x):
        raise ValueError("one block label per observation")
    index: dict[object, list[int]] = {}
    for i, key in enumerate(keys):
        index.setdefault(key, []).append(i)
    groups = [np.asarray(v) for v in index.values()]
    sums = np.array([x[g].sum() for g in groups])
    sizes = np.array([len(g) for g in groups], dtype=np.float64)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(groups), size=(draws, len(groups)))
    means = sums[pick].sum(axis=1) / sizes[pick].sum(axis=1)
    q = (1 - level) / 2
    return float(x.mean()), float(np.quantile(means, q)), float(np.quantile(means, 1 - q)), len(groups)


def diebold_mariano(d: Sequence[float] | NDArray[np.float64], *, lags: int | None = None) -> tuple[float, float, int]:
    """Diebold-Mariano test of equal predictive accuracy on a loss-difference series
    in time order, with a Newey-West (Bartlett) long-run variance and the
    Harvey-Leybourne-Newbold small-sample correction, against Student t(n-1).

    Returns (statistic, two-sided p-value, lags used). Negative statistic: the
    first forecast has lower loss."""
    from scipy import stats as st

    x = np.asarray(d, dtype=np.float64)
    n = len(x)
    if n < 10:
        raise ValueError("too few observations for a Diebold-Mariano test")
    lag = lags if lags is not None else int(np.floor(4 * (n / 100) ** (2 / 9)))
    u = x - x.mean()
    var = float(u @ u) / n
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        var += 2 * w * float(u[k:] @ u[:-k]) / n
    if var <= 0:
        return 0.0, 1.0, lag
    dm = x.mean() / np.sqrt(var / n)
    hln = dm * np.sqrt((n - 1) / n)  # h = 1: the HLN factor sqrt((n + 1 - 2h + h(h-1)/n) / n)
    p = 2 * float(st.t.sf(abs(hln), df=n - 1))
    return float(hln), p, lag


def minimum_detectable_difference(d: Sequence[float] | NDArray[np.float64], *, level: float = 0.95,
                                  power: float = 0.8, se: float | None = None) -> float:
    """The smallest true mean difference this sample would detect with the given
    power: (z_{1-a/2} + z_power) * SE. SE is sd / sqrt(n) unless a dependence-robust
    standard error is passed (e.g. from a block bootstrap).

    A true difference below it would usually go unnoticed: "indistinguishable"
    then means "insufficient evidence", not "no difference"."""
    from scipy import stats as st

    x = np.asarray(d, dtype=np.float64)
    if se is None:
        if len(x) < 2:
            return float("inf")
        se = float(x.std(ddof=1)) / float(np.sqrt(len(x)))
    z = float(st.norm.ppf(1 - (1 - level) / 2) + st.norm.ppf(power))
    return z * float(se)
