"""The versions of the decisions that exist, in a module that imports nothing (plan F11).

``intel.decisions`` holds the decisions of more than one layer: the pipeline's (``decision-v1``: a selection a shadow rule flagged in
``picks.picks``, judged by ten filters, which can become a pick) and the families' (``decision-fam-v1``: a selection a family of F10 sees
value in, judged by the same filters, in SHADOW - it never becomes a pick, a stake, a parlay or a line a user reads).

The column ``decision_version`` is what tells them apart, so every reader of the table says WHICH layer it reads, in its own SQL
(``tests/unit/test_decision_version_guard.py`` holds every reader to it). A reader that is not about the families binds ``DECISION_CORE``;
the readers of the families bind ``DECISION_FAMILIES``; the nightly audit of leakage reads both, on purpose, and says so.

The constants live in ``fbi.core`` - which imports nothing of ours - and not in the decision layer, so that a page, the memory, the market's matrix or
the research can name the version they read without importing the package that decides (the layer's own modules import this one:
``fbi.intel.decision.VERSION`` is ``DECISION_CORE``). ``fbi.knowledge`` imports nothing of ours at all and keeps a copy that a test holds equal.
"""

from __future__ import annotations

from typing import Final

DECISION_CORE: Final = "decision-v1"
"""The pipeline's decisions: what the picks of the day, the parlays, the learning and every page a user can open are made from."""
DECISION_FAMILIES: Final = "decision-fam-v1"
"""The decisions of the families (corners, cards, the goals of the halves): research in shadow, off unless ``FBI_FAMILY_DECISIONS`` says so."""
OUTCOME_CORE: Final = "outcome-v1"
OUTCOME_FAMILIES: Final = "outcome-fam-v1"
"""The version of the rows of ``intel.decision_outcomes`` of each layer."""

POSTMORTEM_FAMILIES: Final = "pm-fam-v1"
"""The version of what a family learned from one decision of its own, after the match (``fbi.familydecisions.postmortem``)."""
MEMORY_FAMILIES: Final = "memory-fam-v1"
"""The version of what the families remember: those post-mortems added up (``fbi.familydecisions.memory``). Both are named here, as they are in the
record of every run, and no more: this module imports nothing and names no table of what is learned after a match."""

LAYERS: Final = {"core": DECISION_CORE, "families": DECISION_FAMILIES}
"""The layer a reader asks for, by name (the admin's views accept ``core`` and ``families``)."""
