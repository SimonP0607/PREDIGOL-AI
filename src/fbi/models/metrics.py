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
