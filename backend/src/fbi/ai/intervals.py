"""How sure a proportion is (IA-027, R3 of the audit of 10 Nov 2026): the interval beside every rate a report shows.

A gate of the plan reads a rate (invalid answers of an agent, attributed matches, the coverage of research v2) and compares it with its
threshold. The rate alone hides how many cases it stands on: 0 invalid of 35 and 0 of 3,500 print the same «0 %», and 4 invalid of 44
(9.1 %) is compatible with anything from 3.6 % to 21.2 %. This module says, for each rate, how many cases were judged, how many were
of each kind, the rate, its 95 % interval and where that interval sits against the threshold.

It INFORMS and decides nothing: no gate reads ``Proportion.relation`` to pass or fail (the rules of approval are the owner's and stay
as they are; using the bound to decide would be a new version of a gate, never an edit). Two intervals, both standard:

    wilson   the Wilson score interval: honest at 0 and at n, never outside [0, 1]; the one shown first.
    exact    Clopper-Pearson, from the binomial itself (no approximation): wider, it never covers less than 95 %.

Pure arithmetic: no database, no clock, no numpy or scipy (the worker's image carries neither by default)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final, Literal

Z95: Final = 1.959963984540054
"""The two-sided 95 % normal quantile."""
CONFIDENCE: Final = 0.95

Kind = Literal["max", "min"]
"""``max``: the rate must not exceed the threshold (invalid answers); ``min``: it must reach it (attribution, coverage)."""
Relation = Literal["below", "above", "straddles", "no_threshold", "no_cases"]


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """The Wilson score interval of ``k`` successes in ``n`` trials, or None without trials."""
    _check(k, n)
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def _log_pmf(i: int, n: int, p: float) -> float:
    return math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p)


def _upper_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p), 0 < p < 1."""
    return min(1.0, sum(math.exp(_log_pmf(i, n, p)) for i in range(k, n + 1)))


def _lower_tail(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p), 0 < p < 1."""
    return min(1.0, sum(math.exp(_log_pmf(i, n, p)) for i in range(0, k + 1)))


def _bisect(f: Any, target: float, lo: float = 0.0, hi: float = 1.0, *, increasing: bool) -> float:
    for _ in range(80):
        mid = (lo + hi) / 2
        if (f(mid) < target) == increasing:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def exact(k: int, n: int, confidence: float = CONFIDENCE) -> tuple[float, float] | None:
    """The Clopper-Pearson interval: the lower end is the p at which P(X >= k) = alpha/2, the upper the p at which P(X <= k) = alpha/2."""
    _check(k, n)
    if n == 0:
        return None
    alpha = (1 - confidence) / 2
    low = 0.0 if k == 0 else _bisect(lambda p: _upper_tail(k, n, p), alpha, increasing=True)
    high = 1.0 if k == n else _bisect(lambda p: _lower_tail(k, n, p), alpha, increasing=False)
    return low, high


def _check(k: int, n: int) -> None:
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"a proportion needs 0 <= k <= n (k={k}, n={n})")


def _pct(x: float | Decimal | None) -> str | None:
    if x is None:
        return None
    return str((Decimal(str(x)) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class Proportion:
    """``k`` of ``n`` cases, read against an optional threshold. ``k`` counts the cases the rate is OF (the invalid answers, the
    attributed matches, the facts found)."""

    k: int
    n: int
    threshold: Decimal | None = None
    kind: Kind = "max"

    def __post_init__(self) -> None:
        _check(self.k, self.n)

    @property
    def rate(self) -> float | None:
        return None if self.n == 0 else self.k / self.n

    @property
    def wilson(self) -> tuple[float, float] | None:
        return wilson(self.k, self.n)

    @property
    def exact(self) -> tuple[float, float] | None:
        return exact(self.k, self.n)

    @property
    def relation(self) -> Relation:
        """Where the Wilson interval sits against the threshold: wholly ``below`` it, wholly ``above`` it, or ``straddles`` it (the cases
        do not tell). Information, never a verdict."""
        if self.n == 0:
            return "no_cases"
        if self.threshold is None:
            return "no_threshold"
        interval = self.wilson
        assert interval is not None
        t = float(self.threshold)
        if self.kind == "max":
            return "below" if interval[1] <= t else "above" if interval[0] > t else "straddles"
        return "above" if interval[0] >= t else "below" if interval[1] < t else "straddles"

    def as_json(self) -> dict[str, Any]:
        w, e = self.wilson, self.exact
        return {"cases": self.n, "counted": self.k, "others": self.n - self.k, "pct": _pct(self.rate),
                "ci95_wilson_pct": None if w is None else [_pct(w[0]), _pct(w[1])],
                "ci95_exact_pct": None if e is None else [_pct(e[0]), _pct(e[1])],
                "threshold_pct": _pct(self.threshold), "threshold_kind": self.kind if self.threshold is not None else None,
                "interval_vs_threshold": self.relation, "decides": False}

    def text(self) -> str:
        """One line for a report: «9/116 · 7.8 % · IC95 4.1-14.1 % · umbral ≤ 3.0 % · el intervalo queda por encima»."""
        if self.n == 0:
            return "0 casos"
        w = self.wilson
        assert w is not None
        out = f"{self.k}/{self.n} · {_pct(self.rate)} % · IC95 {_pct(w[0])}-{_pct(w[1])} %"
        if self.threshold is not None:
            sign = "≤" if self.kind == "max" else "≥"
            words = {"below": "por debajo", "above": "por encima", "straddles": "a ambos lados"}[self.relation]
            out += f" · umbral {sign} {_pct(self.threshold)} % · el intervalo queda {words}"
        return out
