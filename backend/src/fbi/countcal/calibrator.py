"""``count-cal-v1``: the calibrator of the ladder of lines of a count (corners, cards), as the protocol ``AD-B07`` fixes it. Pure.

What it corrects. ``family-v1`` states the distribution of a count (a negative binomial per side, ``fbi.families.fit``). Out of sample
its «over L» can be systematically too high or too low (the corners: 47 % said, 53 % happened, ``FAMILIAS_VS_MERCADO_F11.md``), or
too sure. A separate calibrator per line would make the ladder incoherent (P(over 9.5) above P(over 8.5)); this one is ONE map for
all the lines of a count:

    q(L) = sigmoid(a * logit(S(L)) + b)        S(L) = P(X > L) under family-v1,  a > 0

Because the map is increasing and ``S`` decreases with the line, ``q`` decreases too: it is the survival function of a distribution,
so the calibrated count is a distribution (``calibrated_pmf``) and every line, total and side, reads from it - the ladder is coherent
by construction and sums to one. ``a = 1, b = 0`` is the identity.

How it is fitted. Maximum likelihood of the yes/no events «the count was over L» for the preregistered lines of the ladder, pooled,
with a ridge towards the identity (``RIDGE``): with few matches the calibrator stays the model. ``a`` is kept in ``A_BOUNDS``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
from numpy.typing import NDArray

VERSION: Final = "count-cal-v1"
METHOD: Final = "survival-logit"
RIDGE: Final = 10.0
"""The weight, in nats, of «the model is right» on (a - 1) and b: a quarter of a log-loss point over 40 matches, nothing over 5.000."""
A_BOUNDS: Final = (0.25, 4.0)
MIN_FIT: Final = 500
"""Out-of-sample matches a calibrator (and the dispersion of its block) needs: fewer and the block is not scored (protocol AD-B07)."""
CLIP: Final = 1e-9

FAMILIES: Final = ("corners_total", "corners_side", "cards_total", "cards_side")
"""The four families of the protocol: each gets its own calibrator and its own verdict."""
MEASURE_OF: Final[Mapping[str, str]] = {"corners_total": "corners_ft", "corners_side": "corners_ft",
                                         "cards_total": "cards_lines_ft", "cards_side": "cards_lines_ft"}
"""The settlement rule each family is trained on and graded by (``fbi.market.rules``: ``corners_ft@v1``, ``cards_lines_ft@v1``)."""
LADDERS: Final[Mapping[str, tuple[float, ...]]] = {
    "corners_total": (7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5),
    "corners_side": (2.5, 3.5, 4.5, 5.5, 6.5, 7.5),
    "cards_total": (2.5, 3.5, 4.5, 5.5, 6.5),
    "cards_side": (0.5, 1.5, 2.5, 3.5),
}
"""The preregistered lines of each family (protocol AD-B07): the ones the books price, around the median of each count."""
FAMILY_OF_KEY: Final[Mapping[str, tuple[str, str]]] = {
    "CORNERS_OU": ("corners_total", "total"), "CORNERS_OU_HOME": ("corners_side", "home"), "CORNERS_OU_AWAY": ("corners_side", "away"),
    "CARDS_OU": ("cards_total", "total"), "CARDS_OU_HOME": ("cards_side", "home"), "CARDS_OU_AWAY": ("cards_side", "away"),
}
"""The market keys of the catalogue each family prices, and which count of the match (total, home side, away side) they read."""


@dataclass(frozen=True, slots=True)
class Params:
    """One fitted calibrator: the slope ``a`` and the shift ``b`` of the logit, and how many matches and events fitted it."""

    a: float = 1.0
    b: float = 0.0
    n_matches: int = 0
    n_events: int = 0

    @property
    def identity(self) -> bool:
        return self.a == 1.0 and self.b == 0.0

    def as_json(self) -> dict[str, float | int | str]:
        return {"a": self.a, "b": self.b, "n_matches": self.n_matches, "n_events": self.n_events, "version": VERSION,
                "method": METHOD}


IDENTITY: Final = Params()


def logit(p: NDArray[np.float64]) -> NDArray[np.float64]:
    q = np.clip(p, CLIP, 1.0 - CLIP)
    return np.asarray(np.log(q / (1.0 - q)), dtype=np.float64)


def sigmoid(z: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.asarray(1.0 / (1.0 + np.exp(-z)), dtype=np.float64)


def survival(pmf: NDArray[np.float64]) -> NDArray[np.float64]:
    """``S[k] = P(X > k)`` for k = 0..len-1: the probability of «over k + 0.5». The pmf is normalised first."""
    p = np.asarray(pmf, dtype=np.float64)
    total = float(p.sum())
    if total <= 0.0:
        raise ValueError("not a distribution")
    return np.asarray(np.clip(1.0 - np.cumsum(p / total), 0.0, 1.0), dtype=np.float64)


def transform(s: NDArray[np.float64], params: Params) -> NDArray[np.float64]:
    """The calibrated probability of each «over» (``s``: the model's)."""
    if params.identity:
        return np.asarray(s, dtype=np.float64)
    return sigmoid(params.a * logit(np.asarray(s, dtype=np.float64)) + params.b)


def calibrated_pmf(pmf: NDArray[np.float64], params: Params) -> NDArray[np.float64]:
    """The calibrated distribution of the count: the differences of the calibrated survival function. Sums to one; same support."""
    q = transform(survival(pmf), params)
    out = np.empty_like(q)
    out[0] = 1.0 - q[0]
    out[1:] = q[:-1] - q[1:]
    out[-1] += q[-1]  # the calibrated mass beyond the support, kept in the last count (it is never hidden)
    return np.asarray(np.clip(out, 0.0, 1.0), dtype=np.float64)


def over(pmf: NDArray[np.float64], line: float) -> float:
    """P(X > line) of a distribution (a half line: no push)."""
    p = np.asarray(pmf, dtype=np.float64)
    k = np.arange(p.size, dtype=np.float64)
    return float(p[k > line].sum() / p.sum())


def ladder(pmf: NDArray[np.float64], lines: Sequence[float]) -> NDArray[np.float64]:
    """P(over L) for each line of the ladder."""
    s = survival(pmf)
    idx = [math.floor(ln) for ln in lines]
    if any(i < 0 or i >= s.size for i in idx) or any(not float(ln - 0.5).is_integer() for ln in lines):
        raise ValueError(f"a ladder is made of half lines inside the support: {lines!r}")
    return np.asarray(s[idx], dtype=np.float64)


def fit(p: NDArray[np.float64], y: NDArray[np.float64], *, n_matches: int, ridge: float = RIDGE) -> Params:
    """The calibrator that best explains ``y`` (0/1: the count was over the line) from ``p`` (the model's P(over)), pooled over the
    lines of the ladder, by Newton's method on the likelihood with a ridge towards the identity. Fewer than ``MIN_FIT`` matches,
    or events that all went one way, give the identity."""
    pp, yy = np.asarray(p, dtype=np.float64).ravel(), np.asarray(y, dtype=np.float64).ravel()
    if pp.size != yy.size:
        raise ValueError("one outcome per probability")
    if n_matches < MIN_FIT or pp.size == 0 or float(yy.min()) == float(yy.max()):
        return Params(1.0, 0.0, n_matches, int(pp.size))
    z = logit(pp)
    a, b = 1.0, 0.0
    for _ in range(100):
        q = sigmoid(a * z + b)
        w = q * (1.0 - q) + 1e-12
        g = np.array([float(((q - yy) * z).sum()) + ridge * (a - 1.0), float((q - yy).sum()) + ridge * b])
        h = np.array([[float((w * z * z).sum()) + ridge, float((w * z).sum())],
                      [float((w * z).sum()), float(w.sum()) + ridge]])
        step = np.linalg.solve(h, g)
        a_new = min(max(a - float(step[0]), A_BOUNDS[0]), A_BOUNDS[1])
        b_new = b - float(step[1])
        done = abs(a_new - a) < 1e-10 and abs(b_new - b) < 1e-10
        a, b = a_new, b_new
        if done:
            break
    return Params(a, b, n_matches, int(pp.size))


def log_loss(p: NDArray[np.float64], y: NDArray[np.float64]) -> NDArray[np.float64]:
    """The binary log loss of each probability given what happened (kept off 0 and 1)."""
    q = np.clip(np.asarray(p, dtype=np.float64), 1e-6, 1.0 - 1e-6)
    yy = np.asarray(y, dtype=np.float64)
    return np.asarray(-(yy * np.log(q) + (1.0 - yy) * np.log(1.0 - q)), dtype=np.float64)


def rps(pmf: NDArray[np.float64], observed: int) -> float:
    """The ranked probability score of a count distribution: the sum over k of (P(X <= k) - [observed <= k])^2 (lower is better)."""
    cdf = 1.0 - survival(pmf)
    k = np.arange(cdf.size)
    return float(((cdf - (observed <= k).astype(np.float64)) ** 2).sum())


def ece(p: NDArray[np.float64], y: NDArray[np.float64], bins: int = 10) -> float:
    """Expected calibration error with ``bins`` equal-width bins of the probability (as ``fbi.families.evaluate.ece``)."""
    pp, yy = np.asarray(p, dtype=np.float64), np.asarray(y, dtype=np.float64)
    if pp.size == 0:
        return float("nan")
    which = np.clip(np.digitize(pp, np.linspace(0.0, 1.0, bins + 1)) - 1, 0, bins - 1)
    total = 0.0
    for b in range(bins):
        mask = which == b
        if mask.any():
            total += float(mask.sum()) * abs(float(pp[mask].mean()) - float(yy[mask].mean()))
    return total / pp.size
