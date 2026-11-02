"""WHICH THE FAMILIES ARE and which settlement rule grades a bet on each of their markets (plan F10.17 and F11.11): the few facts of the families that
the readers of the API share.

They live here, apart from the page of the families in shadow (``fbi.api.services.families``), on purpose. That page reads the post-mortems and the
memory the families made of their decisions - the future of a match - and ``tests/unit/test_postmortem_isolation.py`` lists, file by file, who may
import it. What is said BEFORE a kick-off may not: the Admin Console's preview of the forecast names the family of a market and the rule that grades it,
and nothing more, so it reads them from this module, which names no table at all.

Like the page, this module imports nothing of ``fbi.families`` or ``fbi.familydecisions`` (``tests/unit/test_architecture.py`` holds the import cycle
at eight packages): the facts are written here and held equal to the code by ``tests/unit/test_api_families.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from fbi.market.rules import RULES_BY_MEASURE, Rule

FAMILIES: Final = ("GOALS_HALF", "CORNERS", "CARDS", "YELLOW")
"""The families that decide, in the order the console shows them (the keys of ``fbi.familydecisions.decide.SPECS``: held equal by a test)."""
MEASURES: Final[Mapping[str, tuple[str, ...]]] = {
    "GOALS_HALF": ("goals_1h", "goals_2h", "goals_halves"), "CORNERS": ("corners_ft",), "CARDS": ("cards_lines_ft",), "YELLOW": ("yellow_ft",)}
"""The measures of the settlement rules (``fbi.market.rules``) that grade the bets of each family."""
HALVES: Final = frozenset({"HTFT", "HSH", "HSH_HOME", "HSH_AWAY"})
"""The market keys that read both halves of the goals (``fbi.families.score.HALVES_KEYS``: held equal by a test)."""


def measure_of(key: str) -> str | None:
    """The measure of the settlement rules that grades a market key of the families, or None for a key none of them bets on
    (``fbi.families.score.measure_of`` without the exception: held equal by a test over every key the catalogue can make)."""
    if key.startswith("CORNERS_"):
        return "corners_ft"
    if key.startswith("CARDS_"):
        return "cards_lines_ft"
    if key.startswith("YELLOW_"):
        return "yellow_ft"
    if key in HALVES:
        return "goals_halves"
    if key.endswith("_1H"):
        return "goals_1h"
    if key.endswith("_2H"):
        return "goals_2h"
    return None


def rule_of(key: str) -> Rule | None:
    """The settlement rule that grades a bet on this market key, or None when none can."""
    measure = measure_of(key)
    return None if measure is None else RULES_BY_MEASURE.get(measure)
