"""Is one candidate change ELIGIBLE for automatic promotion? (``autopromo-v1``) - pure: no connection, no clock, no environment.

``evaluate`` checks EVERY condition and returns all the reasons that fail, not only the first, so a NOT_ELIGIBLE verdict says everything that
stands between the candidate and an automatic promotion:

    class            forbidden_class | unknown_class
    signature        no_signed_policy | policy_revoked | policy_invalid
    switch           switch_off
    champion         no_champion (nothing in force: a first promotion is a new model or market in force, never automatic)
                     method_changed (a refit keeps the champion's method) | same_version
                     agent_not_counting (a weight of 0 means the agent does not count yet; starting to count is the owner's)
    metric           metric_missing | sample_below_minimum | not_better_than_champion
    band             value_missing | outside_band | outside_bounds
    reversibility    not_reversible (no champion version to roll back to)
    limit            change_limit_reached

The metric is a loss (lower is better): the candidate must be at most ``champion - margin``. The change limit counts the automatic promotions
of the class in the ``period_days`` that end at the candidate's moment: rows of the registry whose ``gate_version`` is ``autopromo-v1`` and whose
evidence names the class. This version writes none, so today that count is always zero.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal

from fbi.governance.autopromo.policy import (
    SAMPLE_FLOOR,
    VERSION,
    ChangeClass,
    PolicyBook,
    Terms,
    class_of,
    refusal_of,
)
from fbi.governance.promotions import Promotion

Verdict = Literal["ELIGIBLE", "NOT_ELIGIBLE"]

WEIGHT_BOUNDS: Final = (0.5, 1.5)
"""council-weights-v1's floor and ceiling of a promoted agent's weight (``fbi.council.weights``; a test ties them)."""
CREDIBILITY_BOUNDS: Final = (0.0, 1.0)


@dataclass(frozen=True, slots=True)
class Candidate:
    change_class: str
    """The raw word: the enum is applied here, so a candidate of a class the code does not know is refused, not crashed on."""
    key: str
    version: str
    at: datetime
    champion_version: str | None
    """What is in force for ``key`` now: also the version an automatic roll-back returns to."""
    candidate_metric: float | None
    champion_metric: float | None
    n: int
    metric: str = "logloss"
    method: str | None = None
    champion_method: str | None = None
    current_value: float | None = None
    """For a class with a band: the value in force (a weight, a credibility, a window)."""
    proposed_value: float | None = None

    def as_json(self) -> dict[str, Any]:
        return {"change_class": self.change_class, "key": self.key, "version": self.version, "at": self.at.isoformat(),
                "champion_version": self.champion_version, "metric": self.metric, "candidate_metric": self.candidate_metric,
                "champion_metric": self.champion_metric, "n": self.n, "method": self.method, "champion_method": self.champion_method,
                "current_value": self.current_value, "proposed_value": self.proposed_value}


@dataclass(frozen=True, slots=True)
class Assessment:
    candidate: Candidate
    verdict: Verdict
    reasons: tuple[str, ...]
    policy_source: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "verdict": self.verdict, "reasons": list(self.reasons), "policy": self.policy_source,
                "candidate": self.candidate.as_json()}


def _finite(x: float | None) -> bool:
    return x is not None and math.isfinite(x)


def automatic_changes(history: Iterable[Promotion], change_class: ChangeClass, *, at: datetime, period_days: int) -> int:
    """The automatic promotions of a class in the window ``(at - period, at]``."""
    since = at - timedelta(days=period_days)
    return sum(1 for p in history if p.gate_version == VERSION and p.evidence.get("change_class") == change_class.value
               and p.in_force is True and since < p.at <= at)


def _band_reasons(change_class: ChangeClass, c: Candidate, band: float) -> list[str]:
    cur, new = c.current_value, c.proposed_value
    if cur is None or new is None or not (math.isfinite(cur) and math.isfinite(new)):
        return ["value_missing"]
    out: list[str] = []
    if change_class is ChangeClass.COUNCIL_WEIGHTS:
        if cur <= 0:
            out.append("agent_not_counting")
        lo, hi = WEIGHT_BOUNDS
        if not lo <= new <= hi:
            out.append("outside_bounds")
        if abs(new - cur) > band:
            out.append("outside_band")
    elif change_class is ChangeClass.SOURCE_CREDIBILITY:
        lo, hi = CREDIBILITY_BOUNDS
        if not (lo <= new <= hi and lo <= cur <= hi):
            out.append("outside_bounds")
        if abs(new - cur) > band:
            out.append("outside_band")
    else:  # cache windows: relative to the window in force
        if cur <= 0 or new <= 0:
            out.append("outside_bounds")
        elif abs(new - cur) / cur > band:
            out.append("outside_band")
    return out


def _metric_reasons(c: Candidate, terms: Terms | None, floor: int) -> list[str]:
    out: list[str] = []
    if not (_finite(c.candidate_metric) and _finite(c.champion_metric)):
        out.append("metric_missing")
    elif terms is not None:
        assert c.candidate_metric is not None and c.champion_metric is not None
        if c.candidate_metric > c.champion_metric - terms.margin:
            out.append("not_better_than_champion")
    if c.n < max(floor, terms.min_sample if terms is not None else floor):
        out.append("sample_below_minimum")
    return out


def evaluate(candidate: Candidate, book: PolicyBook, *, switch_on: bool, history: Iterable[Promotion] = ()) -> Assessment:
    """ELIGIBLE only when no condition fails. Never writes and never decides anything by itself: it is an answer, not an act."""
    refusal = refusal_of(candidate.change_class)
    if refusal is not None:  # a class the code does not list: nothing else is worth checking
        return Assessment(candidate, "NOT_ELIGIBLE", (refusal,))
    change_class = class_of(candidate.change_class)
    assert change_class is not None
    reasons: list[str] = []
    policy = book.of(change_class)
    terms = policy.terms if policy is not None and policy.status == "AUTHORISED" else None
    if policy is None or policy.signed_at > candidate.at:
        reasons.append("no_signed_policy")
    elif policy.status == "REVOKED":
        reasons.append("policy_revoked")
    elif policy.status == "INVALID":
        reasons.append("policy_invalid")
    if policy is not None and policy.signed_at > candidate.at:
        terms = None
    if not switch_on:
        reasons.append("switch_off")
    if candidate.champion_version is None:
        reasons.append("no_champion")
    elif candidate.champion_version == candidate.version:
        reasons.append("same_version")
    if change_class is ChangeClass.CALIBRATOR_REFIT and candidate.champion_version is not None and (
            candidate.method is None or candidate.method != candidate.champion_method):
        reasons.append("method_changed")
    reasons.extend(_metric_reasons(candidate, terms, SAMPLE_FLOOR[change_class]))
    if change_class is not ChangeClass.CALIBRATOR_REFIT:
        band = terms.band if terms is not None and terms.band is not None else 0.0
        reasons.extend(r for r in _band_reasons(change_class, candidate, band) if terms is not None or r != "outside_band")
    if candidate.champion_version is None or candidate.champion_version == candidate.version:
        reasons.append("not_reversible")
    if terms is not None and automatic_changes(history, change_class, at=candidate.at, period_days=terms.period_days) >= terms.max_changes:
        reasons.append("change_limit_reached")
    unique = tuple(dict.fromkeys(reasons))
    return Assessment(candidate, "NOT_ELIGIBLE" if unique else "ELIGIBLE", unique, None if policy is None else f"intel.promotions#{policy.source_id}")
