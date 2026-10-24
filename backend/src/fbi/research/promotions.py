"""The promotions of the model's code (plan F12): which fingerprints of the model packages were put in force, by whom and why.

A model version is keyed by the fingerprint of the model packages (``fbi.core.version.model_code_fingerprint``): any change to the code that
decides what a model predicts opens new versions of every model, and the forecast runs with them from its next pass. Until F12 that was a
release like any other - nobody decided it and nothing recorded it. Between 5 and 24 Oct 2026 six fingerprints forecast in production, and one
of them by accident: an intermediate state of F5 had put the forecast writer inside the model packages, so for about an hour on 23 Oct the three
goal models ran as three new versions, and the forecasts they made still fed decisions a day later.

The ledger below is the decision, in the same commit as the change. ``tests/unit/test_model_code_ledger.py`` fails while the fingerprint of the
tree is not the last entry, so model code cannot change without a row that says why. ``python -m scripts.promotion_trace sync`` copies the
entries into ``intel.promotions`` (entity ``model``, an append-only table that already allowed it) when a release carries them to production, and
``show`` measures production against them: every fingerprint that forecast in the window, and the row that covers it.

This module sits outside the fingerprinted packages (it is not model code): adding an entry does not change the fingerprint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

FINGERPRINT: Final = re.compile(r"^mc[0-9a-f]{10}$")
"""How a model version names its code: ``mc`` and the first ten hex digits of ``model_code_fingerprint`` (``...@mc9a7bec97ca``)."""
DECIDERS: Final = ("owner", "system")
GATE_VERSION: Final = "code-gate-v1"
"""What ``intel.promotions.gate_version`` says about a row written from this ledger."""
MIN_REASON: Final = 40
"""A promotion without a reason a person can look back on is not a decision."""


@dataclass(frozen=True, slots=True)
class CodePromotion:
    """One decision: this fingerprint of the model packages is the code production forecasts with, from ``decided_at``."""

    fingerprint: str
    decided_at: datetime
    decided_by: str
    phase: str
    reason: str
    baseline: bool = False
    """True for the entry that starts the ledger: the code already in force, recorded after the fact and said so."""
    evidence: dict[str, Any] = field(default_factory=dict)
    """What the decision rested on: ``hypothesis_id`` (analytics.research_hypotheses), ``experiment_ids`` (analytics.experiments), the
    gate that passed, the release. The ids are checked against the database when the entry is written to it."""


LEDGER: Final[tuple[CodePromotion, ...]] = (
    CodePromotion(
        fingerprint="mc9a7bec97ca",
        decided_at=datetime(2026, 10, 22, 13, 0, tzinfo=UTC),
        decided_by="system",
        phase="F0",
        baseline=True,
        reason=("Baseline of the ledger: the model code in force when it was started (24 Oct 2026). It is the code of plan F0 - the "
                "neutral-venue switch OFF, the forecast spec only by promotion - in production since 22 Oct 2026 13:04 UTC and unchanged by "
                "F3 to F10 (the forecast writer left the model packages on 23 Oct, which returned the fingerprint to this one)."),
        evidence={"gate": "make check green on each release", "deployed": "2026-10-22T13:04Z",
                  "unpromoted_before": "mc034f19d4a9, mcec6b780838, mc1f28a88360, mc118f6f26d7 (5-22 Oct: before the ledger)"},
    ),
)
"""Oldest first; the last entry is the code in force. To change the model code: change it, add the entry below this one, in the same commit."""


def in_force() -> CodePromotion:
    """The promotion of the code the ledger says production forecasts with."""
    return LEDGER[-1]


def find(fingerprint: str) -> CodePromotion | None:
    return next((p for p in LEDGER if p.fingerprint == fingerprint), None)


def label_of(fingerprint: str) -> str:
    """The code part of a model version string for the 12 hex digits ``model_code_fingerprint`` returns: ``mc`` + the first ten."""
    return f"mc{fingerprint[:10]}"
