"""When the specialist readers speak (IA-123, AD-D09 of the plan of the definitive architecture 2026): ``readers-v1``. Pure.

The three readers of the deliberation - the Match Agent (``match-v6``), the Statistics Agent (``stats-v5``) and the Player Agent
(``player-v2``) - read only their porción of the package, side by side: every request of a pass is built before any of them is asked,
from the same package and the same findings computed WITHOUT assessments (``contra0``), so no reader can see what another said (held by
``tests/unit/test_deliberation_contract.py``). They have no tool, write no query or address and touch no number (``aa-v1``, ``pa-v1``), and
an answer outside its contract is refused before anything of it is kept (``fbi.ai.outputs``, ``enforce`` for the shadow agents: AD-A02).
Each finding they are handed rests only on what their slice has (``fbi.ai.agents.match.PORCION``).

WHEN. The plan's cycle of evaluations (``eval-cycle-v1``, AD-D06) gives the readers ONE moment: E1, from 24 h to 12 h before the kick-off,
when the scenarios, the absences and the estimated starters are laid out. After E1 they speak again only in an E2 - a pass between E1
and E4 - in which the detector found a MATERIAL contradiction (``material``); E3 is code only (the line-up applied to tables computed
before, in under two minutes) and E4 rereads the conditions of the match: no reader in either.

THE SWITCH. ``FBI_AI_READERS`` (``AiSettings.readers``): ``passes`` (the default) keeps today's shadow - the readers speak in every pass
the orchestrator runs (``first``, ``pre``, ``final``); ``e1`` lets them speak only where ``when`` says. Any other word is ``passes``.
With ``e1`` a pass whose moment is not the readers' still runs its Council over the findings with no assessment (the reason is kept in
the pass's ``model_status.readers``): nothing is decided, and nothing reaches a reader of the site, either way.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from fbi.ai.agents.common import Contradiction

VERSION: Final = "readers-v1"
READERS: Final[tuple[str, ...]] = ("match", "stats", "player")
"""The specialist readers of the deliberation, in the order the orchestrator asks them."""
CONTRACTS: Final[dict[str, str]] = {"match": "aa-v1", "stats": "aa-v1", "player": "pa-v1"}

Schedule = Literal["passes", "e1"]
SCHEDULES: Final[tuple[Schedule, ...]] = ("passes", "e1")
DEFAULT: Final[Schedule] = "passes"

Evaluation = Literal["E1", "E2", "E3", "E4", "none"]

E1_FROM: Final = timedelta(hours=24)
E1_UNTIL: Final = timedelta(hours=12)
E4_FROM: Final = timedelta(minutes=20)
"""The windows of the cycle of evaluations (``fbi.evalcycle.clock``: E1 from 24 h to 12 h; the readers' last stretch from 20 min, the
opening of decision-v2's last decision, ``clock.DECIDE_FROM``). Since IA-142 the cycle's E4 verdict is at T-5, but no reading can reach
the last decision after T-20, so the readers stop where they stopped. Copied, because ``fbi.ai`` may not import the cycle (the cycle
imports ``fbi.ai``); ``tests/unit/test_readers.py`` holds them equal."""

MATERIAL_CODES: Final = frozenset({"C01", "C02", "C03", "C06", "C07"})
"""The rules of ``contra-v1`` whose finding is MATERIAL for a second reading (preregistered here, before any E2 is measured): a key player
out (C01) or the first-choice goalkeeper (C02) - only when the evidence that fires it is CONFIRMED -, a rotation judged with the official
line-up (C03), the model against the market beyond the router's gap (C06) and evidence in conflict (C07, which needs a research first).
Nothing at stake for a side (C04) and a lenient referee (C05) are context the readers already had in E1: they never call them back."""


def schedule_of(raw: str | None) -> Schedule:
    """``FBI_AI_READERS``: ``e1`` or ``passes``; anything else is ``passes``."""
    word = (raw or "").strip().lower()
    return "e1" if word == "e1" else "passes"


def material(contradictions: Iterable[Contradiction]) -> tuple[str, ...]:
    """The codes of the material findings (``MATERIAL_CODES``) that touch at least one candidate, sorted and once each."""
    found: set[str] = set()
    for c in contradictions:
        if c.code not in MATERIAL_CODES or not c.candidates:
            continue
        if c.code in ("C01", "C02") and not c.confirmed:
            continue
        if c.code == "C03" and not c.official_lineup:
            continue
        found.add(c.code)
    return tuple(sorted(found))


def evaluation_of(at: datetime, kickoff_at: datetime, *, e1_seen: bool) -> Evaluation:
    """Which evaluation of the cycle a moment of a pass is: E1 in its window; E2 after E1 (one was already run for the match, or its window
    is past) and before E4 opens; E4 from 20 min; ``none`` before E1 opens or once the match started. ``e1_seen`` says whether an earlier
    pass of the match already fell in E1's window (a match first seen at T-6 h has no E1 behind it: its pass is its first reading, E1)."""
    if at.tzinfo is None or kickoff_at.tzinfo is None:
        raise ValueError("the moments of a pass are compared with their zones")
    if at >= kickoff_at:
        return "none"
    if kickoff_at - E4_FROM <= at:
        return "E4"
    if kickoff_at - E1_FROM <= at <= kickoff_at - E1_UNTIL:
        return "E1"
    if at < kickoff_at - E1_FROM:
        return "none"
    return "E2" if e1_seen else "E1"


@dataclass(frozen=True, slots=True)
class Turn:
    """Whether the readers speak in a pass, and why (a closed code)."""

    speak: bool
    evaluation: Evaluation
    reason: str
    material: tuple[str, ...] = ()

    def as_json(self) -> dict[str, object]:
        return {"version": VERSION, "speak": self.speak, "evaluation": self.evaluation, "reason": self.reason, "material": list(self.material)}


def when(schedule: Schedule, evaluation: Evaluation, contradictions: Iterable[Contradiction] = ()) -> Turn:
    """The rule of ``readers-v1``. With ``passes`` the readers speak in every pass (today's shadow); with ``e1`` they speak in E1, in an E2
    with a material finding, and never in E3, E4 or outside the cycle."""
    codes = material(contradictions)
    if schedule == "passes":
        return Turn(True, evaluation, "every_pass", codes)
    if evaluation == "E1":
        return Turn(True, evaluation, "e1", codes)
    if evaluation == "E2":
        return Turn(bool(codes), evaluation, "e2_material" if codes else "e2_without_material_contradiction", codes)
    if evaluation in ("E3", "E4"):
        return Turn(False, evaluation, f"{evaluation.lower()}_is_code_only", codes)
    return Turn(False, evaluation, "outside_the_cycle", codes)


__all__ = ["CONTRACTS", "DEFAULT", "E1_FROM", "E1_UNTIL", "E4_FROM", "MATERIAL_CODES", "READERS", "SCHEDULES", "VERSION", "Evaluation",
           "Schedule", "Turn", "evaluation_of", "material", "schedule_of", "when"]
