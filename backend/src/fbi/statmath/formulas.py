"""The formulas of the statistics documents (plan EA, EA-003 to EA-006). Pure: numbers in, numbers out; no database, no clock.

* ``percentile`` - mid-rank: the share of the others strictly below plus half the ties, x 100, rounded half up.
* ``wilson`` - the score interval of a proportion (z = 1.96): with 7 of 10 it is [39 %, 89 %].
* ``quantiles`` - p10, p25, p50, p75, p90 by linear interpolation (numpy's default).
* ``smoothing_matrix`` / ``pulse`` - ``pulso-v1``: a Gaussian kernel of ``SIGMA`` minutes over the 5' bins of each half, 45+ and 90+
  kept as their own masses; the band is the 10th and 90th percentile of the index over a bootstrap that resamples MATCHES (seeded:
  the same data gives the same band).
* ``survival`` - Kaplan-Meier of the first goal; a match without a goal is censored at 90+ (every match ends there, so the estimate
  is the share of matches still 0-0 after each minute).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

import numpy as np

Z95: Final = 1.959963984540054
SIGMA: Final = 7.5
"""The kernel's width in minutes (pulso-v1)."""
BOOTSTRAP: Final = 1000
BAND: Final = (10.0, 90.0)

PULSE_LABELS: Final = (
    "0-5", "5-10", "10-15", "15-20", "20-25", "25-30", "30-35", "35-40", "40-45", "45+",
    "45-50", "50-55", "55-60", "60-65", "65-70", "70-75", "75-80", "80-85", "85-90", "90+",
)
PULSE_STARTS: Final = (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90)
FIRST_REGULAR: Final = tuple(range(0, 9))
SECOND_REGULAR: Final = tuple(range(10, 19))
ADDED: Final = (9, 19)

INTERVAL_LABELS: Final = ("1-15", "16-30", "31-45", "45+", "46-60", "61-75", "76-90", "90+")


def half_up(value: float, decimals: int = 0) -> float:
    q = Decimal(1).scaleb(-decimals)
    return float(Decimal(repr(float(value))).quantize(q, rounding=ROUND_HALF_UP))


def pct_int(value: float) -> int:
    return int(half_up(value * 100))


def percentile(value: float, others: Sequence[float]) -> int:
    """Mid-rank percentile of ``value`` among ``others`` (the population, the value itself included or not)."""
    if not others:
        raise ValueError("a percentile needs a population")
    below = sum(1 for o in others if o < value)
    ties = sum(1 for o in others if o == value)
    return int(half_up(100.0 * (below + 0.5 * ties) / len(others)))


def wilson(hits: int, n: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval of hits/n, as proportions."""
    if n <= 0 or not 0 <= hits <= n:
        raise ValueError("a proportion needs 0 <= hits <= n and n > 0")
    p = hits / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - half) / denom), min(1.0, (centre + half) / denom)


def wilson_pct(hits: int, n: int) -> tuple[int, int, int]:
    """(pct, low, high) in whole percentage points; low <= pct <= high always holds after rounding."""
    low, high = wilson(hits, n)
    pct = pct_int(hits / n)
    return pct, min(pct, pct_int(low)), max(pct, pct_int(high))


def quantiles(values: Sequence[float]) -> tuple[float, float, float, float, float]:
    if not values:
        raise ValueError("quantiles need values")
    q = np.percentile(np.asarray(values, dtype=float), [10, 25, 50, 75, 90])
    return tuple(half_up(float(x), 3) for x in q)  # type: ignore[return-value]


# ── minutes and bins ─────────────────────────────────────────────────────────────────────────────────────────────────

def pulse_bin(minute: int, extra: int | None) -> int | None:
    """The 5' bin of an event (0-19), or None for a minute of extra time (91+ without an added minute)."""
    if extra and minute == 45:
        return 9
    if extra and minute >= 90:
        return 19
    if minute <= 0:
        return 0
    if minute <= 45:
        return min(8, (minute - 1) // 5)
    if minute <= 90:
        return 10 + min(8, (minute - 46) // 5)
    return None


def interval_bin(minute: int, extra: int | None) -> int | None:
    """The 15' bin (0-7) of ``INTERVAL_LABELS``, or None in extra time."""
    if extra and minute == 45:
        return 3
    if extra and minute >= 90:
        return 7
    if minute <= 15:
        return 0
    if minute <= 30:
        return 1
    if minute <= 45:
        return 2
    if minute <= 60:
        return 4
    if minute <= 75:
        return 5
    if minute <= 90:
        return 6
    return None


def clock(minute: int, extra: int | None) -> float:
    """The position of an event on the 90-minute clock: an added minute stays at 45 or 90 (it lasts nothing), ordered by its
    added minute."""
    if extra and minute in (45, 90):
        return minute + extra / 1000.0
    return float(minute)


# ── pulso-v1 ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def smoothing_matrix(sigma: float = SIGMA) -> np.ndarray:
    """20 x 20: row i is how the mass of bin i spreads. Each half's regular bins are smoothed among themselves (normalised so that
    the mass is kept); 45+ and 90+ keep their own mass."""
    m = np.zeros((20, 20))
    for block in (FIRST_REGULAR, SECOND_REGULAR):
        centres = np.array([PULSE_STARTS[i] + 2.5 for i in block])
        for i, ci in zip(block, centres, strict=True):
            w = np.exp(-0.5 * ((centres - ci) / sigma) ** 2)
            w = w / w.sum()
            for j, wj in zip(block, w, strict=True):
                m[i, j] = wj
    for i in ADDED:
        m[i, i] = 1.0
    return m


def pulse(per_match: np.ndarray, league_rate: np.ndarray, *, seed: int, bootstrap: int = BOOTSTRAP,
          sigma: float = SIGMA) -> tuple[np.ndarray, list[float | None], list[float | None], list[float | None]]:
    """``per_match``: n x 20 raw counts. Returns the smoothed rate per match (20), and per bin the index, low and high (None where
    the league's rate is 0). ``league_rate`` is the league's smoothed rate per team-match (20)."""
    if per_match.ndim != 2 or per_match.shape[1] != 20 or per_match.shape[0] == 0:
        raise ValueError("pulse needs n x 20 counts with n >= 1")
    s = smoothing_matrix(sigma)
    smoothed = per_match @ s
    n = smoothed.shape[0]
    rate = smoothed.mean(axis=0)
    idx: list[float | None] = []
    low: list[float | None] = []
    high: list[float | None] = []
    if bootstrap > 0:
        rng = np.random.default_rng(seed)
        weights = rng.multinomial(n, np.full(n, 1.0 / n), size=bootstrap)
        samples = weights @ smoothed / n
    else:
        samples = rate[None, :]
    for b in range(20):
        lr = float(league_rate[b])
        if lr <= 0:
            idx.append(None)
            low.append(None)
            high.append(None)
            continue
        idx.append(half_up(100.0 * float(rate[b]) / lr, 1))
        lo, hi = np.percentile(100.0 * samples[:, b] / lr, BAND)
        low.append(half_up(float(lo), 1))
        high.append(half_up(float(hi), 1))
    return rate, idx, low, high


def smoothed_rate(per_match: np.ndarray, sigma: float = SIGMA) -> np.ndarray:
    if per_match.shape[0] == 0:
        return np.zeros(20)
    return np.asarray((per_match @ smoothing_matrix(sigma)).mean(axis=0))


# ── survival of 0-0 ─────────────────────────────────────────────────────────────────────────────────────────────────

SURVIVAL_STEPS: Final = (
    ("0", 0, 0.0), ("5", 5, 5.0), ("10", 10, 10.0), ("15", 15, 15.0), ("20", 20, 20.0), ("25", 25, 25.0), ("30", 30, 30.0),
    ("35", 35, 35.0), ("40", 40, 40.0), ("45", 45, 45.0), ("45+", 45, 45.999), ("50", 50, 50.0), ("55", 55, 55.0),
    ("60", 60, 60.0), ("65", 65, 65.0), ("70", 70, 70.0), ("75", 75, 75.0), ("80", 80, 80.0), ("85", 85, 85.0),
    ("90", 90, 90.0), ("90+", 90, 90.999),
)
"""(label, minute, clock): the survival is read after each clock position."""


def survival(first_goal: Sequence[float | None]) -> list[tuple[str, int, float]]:
    """Kaplan-Meier of the first goal of each match (its clock position, or None for 0-0). Every match is followed to 90+, so the
    only censoring is the end and the estimate equals the share of matches without a goal yet."""
    n = len(first_goal)
    if n == 0:
        raise ValueError("survival needs matches")
    times = sorted(t for t in first_goal if t is not None)
    out = []
    s, at_risk, k = 1.0, n, 0
    for label, minute, c in SURVIVAL_STEPS:
        while k < len(times) and times[k] <= c:
            d = 1
            while k + d < len(times) and times[k + d] == times[k]:
                d += 1
            s *= 1 - d / at_risk
            at_risk -= d
            k += d
        out.append((label, minute, half_up(s, 4)))
    return out


def median_label(points: Sequence[tuple[str, int, float]]) -> str | None:
    for label, _, s in points:
        if s <= 0.5:
            return label
    return None
