"""Does a context factor move the result beyond what the market already says? The residual test, reusable (plan RP-4.5, finding H18, ``factor-residual-v1``).

THE QUESTION
------------
A context factor (rest, what a side plays for, the referee...) is a reason to move a probability only if, among the matches where it is present, the
outcome differs from what the market's price already said. The residual of a match is ``outcome - market probability`` of the event the group is about
(1 or 0 for the outcome; the market's probability without margin); the mean residual of a group of matches is its «effect», in probability points. The audit of
24-nov measured two of them this way and found both inside their error: a local side with 4 days of rest or fewer against a visitor with 6 or more, 204 matches,
+3.1 points with a standard error of 3.2; the table position, nine groups and 1,870 matches, none beyond 1.5 standard errors. This module is that measurement as a
function, so that the next factor is measured the same way and the registry's state comes from it and not from a reading of a table.

HOW IT IS COUNTED
-----------------
* The standard error is clustered by DAY: the matches of one day share a weekend, a referee pool and a market that moves together, so they are not independent
  (the same rule as ``fbi.research.exp_protocol``). ``se`` is the cluster-robust error of the mean (with the ``C / (C - 1)`` correction for ``C`` days) and ``low`` /
  ``high`` the interval by resampling whole days (``exp_protocol.day_bootstrap_ci``).
* A group says «inside the error» when ``|z| <= NOTABLE_Z`` (1.5, the audit's own line); the p-value is the two-sided normal one from ``z`` and is adjusted
  by Holm over the groups with enough matches.
* ``judge`` turns the lines into a state of the registry, or into none: ``TESTED_EFFECT`` only if a group is significant after Holm AND its two halves in time
  lie on the same side (a result that flips between halves is not an effect); ``TESTED_NO_EFFECT`` only if every group has at least ``MIN_MATCHES`` matches AND
  the effect it could have shown is at most ``MAX_DETECTABLE`` points (``1.96 * se``): «no effect» from a sample too small to see a real one is NOT said, it is
  «not enough evidence yet» (no state). 204 matches with an error of 3.2 points, the audit's group, therefore gives no state: it could not have shown less than
  6.3 points.

It decides and writes nothing. The caller records the state with ``fbi.intel.factors.record_test`` and the name of the experiment.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from fbi.intel import factors
from fbi.research import exp_protocol

VERSION: Final = "factor-residual-v1"
NOTABLE_Z: Final = 1.5
"""The audit's line for «beyond the error»: 1.5 standard errors."""
ALPHA: Final = 0.05
MIN_MATCHES: Final = 200
"""Fewer matches than this in a group: the group is reported but says nothing (the audit's own floor for a segment)."""
MAX_DETECTABLE: Final = 0.05
"""«No effect» needs a test that could have seen an effect of this many probability points (5) at 95 %: ``1.96 * se <= MAX_DETECTABLE``."""
DRAWS: Final = 1000
SEED: Final = 20261126


@dataclass(frozen=True, slots=True)
class Obs:
    """One match in one group: the day, the group it belongs to, whether the event happened (1.0 / 0.0) and the market's probability of it, without margin."""

    day: date
    group: str
    outcome: float
    market: float


@dataclass(frozen=True, slots=True)
class Line:
    """The residual of one group, in probability points as fractions (0.031 is +3.1 points)."""

    group: str
    n: int
    days: int
    mean: float
    se: float | None
    z: float | None
    low: float
    high: float
    p: float | None
    inside_error: bool | None
    detectable: float | None
    halves_agree: bool
    enough: bool

    def as_json(self) -> dict[str, Any]:
        return {"group": self.group, "n": self.n, "days": self.days, "mean": self.mean, "se": self.se, "z": self.z, "low": self.low, "high": self.high,
                "p": self.p, "inside_error": self.inside_error, "detectable": self.detectable, "halves_agree": self.halves_agree, "enough": self.enough}


@dataclass(frozen=True, slots=True)
class Verdict:
    """The state the measurement supports (a state of the registry) or None, and why."""

    state: str | None
    reason: str
    adjusted: Mapping[str, float]

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "state": self.state, "reason": self.reason, "adjusted_p": dict(self.adjusted)}


def _check(o: Obs) -> None:
    if o.outcome not in (0.0, 1.0):
        raise ValueError("the outcome of an event is 1 or 0")
    if not 0.0 < o.market < 1.0:
        raise ValueError("a market probability lies strictly between 0 and 1")


def cluster_se(residuals: Sequence[float], days: Sequence[date]) -> float | None:
    """The standard error of the mean of ``residuals`` with the matches of a day as one cluster (None with fewer than two days)."""
    if len(residuals) != len(days):
        raise ValueError("one day per residual")
    n = len(residuals)
    by_day: dict[date, float] = defaultdict(float)
    mean = sum(residuals) / n
    for e, d in zip(residuals, days, strict=True):
        by_day[d] += e - mean
    c = len(by_day)
    if c < 2:
        return None
    return math.sqrt(c / (c - 1) * sum(v * v for v in by_day.values())) / n


def two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def lines(observations: Sequence[Obs], *, draws: int = DRAWS, seed: int = SEED) -> list[Line]:
    """The residual of every group, in the order the groups first appear."""
    groups: dict[str, list[Obs]] = {}
    for o in observations:
        _check(o)
        groups.setdefault(o.group, []).append(o)
    out: list[Line] = []
    for name, rows in groups.items():
        e = [o.outcome - o.market for o in rows]
        d = [o.day for o in rows]
        mean, low, high = exp_protocol.day_bootstrap_ci(e, d, seed=seed, draws=draws)
        se = cluster_se(e, d)
        z = None if not se else mean / se
        out.append(Line(name, len(rows), len(set(d)), mean, se, z, low, high, None if z is None else two_sided_p(z),
                        None if z is None else abs(z) <= NOTABLE_Z, None if se is None else 1.96 * se,
                        exp_protocol.same_sign_in_halves(e, d), len(rows) >= MIN_MATCHES and se is not None))
    return out


def judge(found: Sequence[Line]) -> Verdict:
    """The state of the registry that the lines support: ``TESTED_EFFECT``, ``TESTED_NO_EFFECT`` or None (not enough evidence)."""
    usable = [ln for ln in found if ln.enough and ln.p is not None]
    if not usable:
        return Verdict(None, f"ningún grupo llega a {MIN_MATCHES} partidos con error medible: aún no hay evidencia", {})
    adjusted = exp_protocol.holm({ln.group: float(ln.p) for ln in usable if ln.p is not None})
    significant = [ln for ln in usable if adjusted[ln.group] < ALPHA]
    if significant:
        steady = [ln for ln in significant if ln.halves_agree]
        if steady:
            names = ", ".join(ln.group for ln in steady)
            return Verdict(factors.TESTED_EFFECT, f"efecto fuera del error tras Holm y del mismo signo en las dos mitades: {names}", adjusted)
        return Verdict(None, "hay un grupo fuera del error, pero su signo cambia entre las dos mitades: no se declara efecto", adjusted)
    blind = [ln.group for ln in usable if ln.detectable is None or ln.detectable > MAX_DETECTABLE]
    if blind or len(usable) < len(found):
        why = (f"ningún grupo se sale del error, pero {', '.join(blind)} no habría visto un efecto de {MAX_DETECTABLE * 100:.0f} puntos"
               if blind else f"ningún grupo se sale del error, pero hay grupos con menos de {MIN_MATCHES} partidos")
        return Verdict(None, why + ": «sin efecto» no se dice con una muestra que no lo habría visto", adjusted)
    return Verdict(factors.TESTED_NO_EFFECT, f"ningún grupo se sale del error y todos habrían visto un efecto de {MAX_DETECTABLE * 100:.0f} puntos", adjusted)


def report(observations: Sequence[Obs]) -> dict[str, Any]:
    """The lines and the verdict as one JSON object: the result an experiment hands to the registry (``factors.record_test``)."""
    found = lines(observations)
    return {"version": VERSION, "matches": len(observations), "groups": [ln.as_json() for ln in found], "verdict": judge(found).as_json(),
            "rule": {"notable_z": NOTABLE_Z, "alpha": ALPHA, "min_matches": MIN_MATCHES, "max_detectable": MAX_DETECTABLE}}


__all__ = ["ALPHA", "MAX_DETECTABLE", "MIN_MATCHES", "NOTABLE_Z", "VERSION", "Line", "Obs", "Verdict", "cluster_se", "judge", "lines", "report",
           "two_sided_p"]
