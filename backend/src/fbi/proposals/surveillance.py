"""Surveillance of what was promoted (RP-8.4, tranche 2): the rule the calibrators already had, said once for any promoted version.

A calibrator that is in force is retired when, over its last 14 days and at least 500 selections, its probabilities are worse than the raw model's or badly
calibrated (``fbi.intel.calibration``, ``RETIRE_*``: never because of one day). This module states that rule for ANY promoted version so every ledger of the registry
(``fbi.governance.promotions``) can be watched with the same words:

* a **reading** is what a version did on the matches after its promotion: how many observations, its loss, the loss of what it replaced or of the raw figure it
  corrects (the reference) and, when the version is a probability, its calibration error;
* the **verdict** is ``mantiene``, ``degrada`` (enough observations and worse than the reference by more than the margin, or too far from calibrated) or
  ``insuficiente`` (not enough observations: nothing is said, and nothing is withdrawn on a small sample);
* the **finding** of a version that degrades becomes a ``retirada`` proposal with the way back (the previous version) and the evidence that made it, for the owner's
  signature. Where a ledger already withdraws by itself under this same rule (the calibrators) the existing withdrawal stands and this module only reports;
  nothing here writes a promotion, lowers a threshold or names a probability (``fbi.proposals.problems`` refuses both). Pure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from fbi.proposals import Proposal

VERSION: Final = "surveillance-v1"
WINDOW_DAYS: Final = 14
MIN_N: Final = 500
MARGIN: Final = 0.0
"""How much worse than its reference a version may be before it counts as degraded: none, the rule the calibrators have had since the first one."""
MAX_ECE: Final = 0.05
KEEPS: Final = "mantiene"
DEGRADES: Final = "degrada"
SHORT: Final = "insuficiente"


@dataclass(frozen=True, slots=True)
class Reading:
    """What a promoted version did since it was promoted, on the observations of the window."""

    n: int
    loss: float | None
    reference_loss: float | None
    ece: float | None = None


@dataclass(frozen=True, slots=True)
class Verdict:
    state: str
    reasons: tuple[str, ...]


def judge(reading: Reading | None, *, min_n: int = MIN_N, margin: float = MARGIN, max_ece: float = MAX_ECE) -> Verdict:
    """The rule: with ``min_n`` observations, a version degrades if its loss is above its reference's by more than ``margin`` or its calibration error is above ``max_ece``."""
    if reading is None or reading.n < min_n or reading.loss is None or reading.reference_loss is None:
        n = 0 if reading is None else reading.n
        return Verdict(SHORT, (f"{n} observaciones de las {min_n} que hacen falta",))
    reasons: list[str] = []
    if reading.loss > reading.reference_loss + margin:
        reasons.append(f"peor que su referencia: {reading.loss:.4f} frente a {reading.reference_loss:.4f}")
    if reading.ece is not None and reading.ece > max_ece:
        reasons.append(f"error de calibración {reading.ece:.4f} por encima de {max_ece}")
    return Verdict(DEGRADES if reasons else KEEPS, tuple(reasons))


@dataclass(frozen=True, slots=True)
class Finding:
    """One promoted version, what it was read as and what to do."""

    entity_type: str
    key: str
    version: str
    since: datetime
    previous: str | None
    reading: Reading | None
    verdict: Verdict
    automatic: bool = False
    """True when the ledger of this kind already withdraws by itself under this rule: the finding is reported, not proposed."""

    def as_json(self) -> dict[str, Any]:
        r = self.reading
        return {"entity_type": self.entity_type, "key": self.key, "version": self.version, "since": self.since.isoformat(), "previous": self.previous,
                "n": None if r is None else r.n, "loss": None if r is None else r.loss, "reference_loss": None if r is None else r.reference_loss,
                "ece": None if r is None else r.ece, "state": self.verdict.state, "reasons": list(self.verdict.reasons), "automatic": self.automatic}


def withdrawal(finding: Finding) -> Proposal | None:
    """The ``retirada`` proposal of a version that degrades (None for any other state, or when its ledger withdraws by itself). It names the way back: the previous version."""
    if finding.verdict.state != DEGRADES or finding.automatic:
        return None
    r = finding.reading
    assert r is not None  # a degrading verdict has a reading
    evidence = {"entity_type": finding.entity_type, "key": finding.key, "version": finding.version, "since": finding.since.isoformat(), "window_days": WINDOW_DAYS,
                "n": r.n, "loss": r.loss, "reference_loss": r.reference_loss, "ece": r.ece, "min_n": MIN_N, "margin": MARGIN, "max_ece": MAX_ECE,
                "rule": VERSION}
    refs: tuple[Mapping[str, Any], ...] = ({"table": "intel.promotions", "entity": finding.entity_type, "key": finding.key},)
    back = finding.previous or "sin-version-anterior"
    return Proposal("retirada", f"store:promotion/{finding.entity_type}/{finding.key}", finding.version, back,
                    {"withdraws": finding.version, "returns_to": back, "keeps": "la promoción y sus filas, legibles"},
                    evidence, tuple(dict(x) for x in refs),
                    f"{finding.entity_type} {finding.key} ({finding.version}) degrada en {WINDOW_DAYS} días: " + "; ".join(finding.verdict.reasons)
                    + ". La firma del dueño decide; la vuelta es a " + back)


__all__ = ["DEGRADES", "KEEPS", "MARGIN", "MAX_ECE", "MIN_N", "SHORT", "VERSION", "WINDOW_DAYS", "Finding", "Reading", "Verdict", "judge", "withdrawal"]
