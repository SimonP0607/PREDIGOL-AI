"""Whether ONE targeted research round is warranted for a match, and on which topics (``council-research-v1``, part of
``council-protocol-v1``). Pure: it reads the findings of ``council.contradictions`` and the numbers the pass stored, never a clock or a row.

A round is WARRANTED when, for at least one selection of the match, both hold:

    materiality   a MATERIAL finding touches it (``Finding.material``: a contradiction between voices that weigh), or ``contra-v1`` found
                  evidence in conflict on it (C07, which ``fbi.ai.agents.common.REQUIRES`` says needs a research first, whatever weighs)
    value         what is at stake on it clears the decision layer's own bar: its expected value per unit (``ev``) is at least
                  ``MIN_EV`` - or, when the pass stored no expected value, the model's edge is at least ``MIN_EDGE``. A selection that
                  could not become a pick anyway is not worth a search

and the round can still be served: at least ``MIN_MINUTES`` to the kick-off (``router-v1``'s own limit for a research). A match gets ONE
round at most (the second round of the Council, ``router.council_calls``), so the topics are the union over the warranted selections,
from the closed catalogue (``ResearchTopic``: availability, confirmation, preview), in the catalogue's order, at most ``TOPICS_MAX``.

Where a topic comes from: a finding against the market (AK1, AK2) asks who can play (``availability``: a price that moves against a stance
most often knows of an absence); a C07 asks for a ``confirmation``; every other material finding asks the topics of the signals that drove
the stances it involves (``TOPIC_OF_SIGNAL``). A warranted selection whose findings map to no topic of the catalogue asks nothing: the
round is not requested for it (``no_topic_in_the_catalogue``) - a search the catalogue cannot name is not one the server can make.

This decides what the deterministic layer WOULD request. It requests nothing: no search is made, no task is planned.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, get_args

from fbi.ai import router
from fbi.ai.contracts.base import ResearchTopic
from fbi.council.contradictions import Finding, Position, Selection
from fbi.intel import decision

VERSION: Final = "council-research-v1"

TOPICS: Final = get_args(ResearchTopic)
"""The closed catalogue (``fbi.ai.research``), in its own order."""

MIN_EV: Final = Decimal(str(decision.EV_MIN))
"""The expected value per unit a selection must have for a research on it to be worth a search: the decision layer's own minimum for an
approval (``fbi.intel.decision.EV_MIN``). One number, not two: below it the selection is no pick whatever the research finds."""

MIN_EDGE: Final = Decimal(str(decision.EDGE_MIN))
"""The fallback when the pass stored no expected value: the decision layer's minimum calibrated edge (``fbi.intel.decision.EDGE_MIN``)."""

MIN_MINUTES: Final = int(router.PARAMS["research_min_minutes"])
"""The fewest minutes to the kick-off at which a research can still be served (``router-v1``, rule 7)."""

TOPICS_MAX: Final = 2
"""At most two topics in the one round: a TARGETED round, not the whole catalogue. Engineering choice."""

TOPIC_OF_SIGNAL: Final[Mapping[str, str]] = {
    "ABSENCES": "availability", "MARKET_MOVE": "availability",
    "LINEUP": "confirmation", "NEWS": "confirmation",
    "STAKES": "preview", "TACTICS": "preview", "SCHEDULE": "preview"}
"""The topic a signal of ``aa-v1`` asks for when a stance it drove is in a material contradiction. FORM, H2H, VENUE, REFEREE, RATE,
MODEL_MARKET_GAP and DATA_QUALITY are numbers the server already has: no search settles them."""

TOPIC_OF_CODE: Final[Mapping[str, str]] = {"AK1": "availability", "AK2": "availability"}
"""The topic a kind of finding asks for by itself, before its drivers."""

CONFLICT: Final = "C07"
CONFLICT_TOPIC: Final = "confirmation"


@dataclass(frozen=True, slots=True)
class Case:
    """One selection as the rule reads it: its numbers, its findings and the positions they involve."""

    selection: Selection
    findings: tuple[Finding, ...]
    positions: tuple[Position, ...]


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the rule says of one selection."""

    candidate: str
    material: bool
    at_stake: bool
    value: str | None
    value_basis: str | None
    topics: tuple[str, ...]
    warranted: bool
    reasons: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {"candidate": self.candidate, "material": self.material, "at_stake": self.at_stake, "value": self.value,
                "value_basis": self.value_basis, "topics": list(self.topics), "warranted": self.warranted, "reasons": list(self.reasons)}


@dataclass(frozen=True, slots=True)
class Round:
    """The match's one round: requested or not, its topics, the selections that warrant it and why."""

    requested: bool
    topics: tuple[str, ...]
    candidates: tuple[str, ...]
    reasons: tuple[str, ...]
    per_candidate: tuple[Verdict, ...]
    minutes_to_kickoff: int | None
    version: str = VERSION

    def as_json(self) -> dict[str, Any]:
        return {"version": self.version, "requested": self.requested, "topics": list(self.topics), "candidates": list(self.candidates),
                "reasons": list(self.reasons), "minutes_to_kickoff": self.minutes_to_kickoff,
                "per_candidate": [v.as_json() for v in self.per_candidate]}


def _order(topics: set[str]) -> tuple[str, ...]:
    return tuple(t for t in TOPICS if t in topics)


def value_of(sel: Selection) -> tuple[Decimal | None, str | None, bool]:
    """(value, its basis, whether it clears the bar): the expected value first, the edge when there is none."""
    if sel.ev is not None:
        return sel.ev, "ev", sel.ev >= MIN_EV
    edge = sel.value_edge
    if edge is not None:
        return edge, "edge", edge >= MIN_EDGE
    return None, None, False


def topics_of(case: Case) -> tuple[str, ...]:
    """The topics the material findings (and a C07) of one selection ask for, in the catalogue's order."""
    by_run = {p.run_id: p for p in case.positions}
    asked: set[str] = set()
    for f in case.findings:
        if not f.material:
            continue
        if f.code in TOPIC_OF_CODE:
            asked.add(TOPIC_OF_CODE[f.code])
        for run_id in f.run_ids:
            p = by_run.get(run_id)
            if p is not None:
                asked |= {TOPIC_OF_SIGNAL[d] for d in p.drivers if d in TOPIC_OF_SIGNAL}
    if CONFLICT in case.selection.contra:
        asked.add(CONFLICT_TOPIC)
    return _order(asked & set(TOPICS))


def judge(case: Case) -> Verdict:
    """The rule for one selection, before the time to the kick-off is read."""
    material = any(f.material for f in case.findings) or CONFLICT in case.selection.contra
    value, basis, at_stake = value_of(case.selection)
    topics = topics_of(case) if material else ()
    reasons: list[str] = []
    if not material:
        reasons.append("no_material_contradiction")
    if value is None:
        reasons.append("no_value_measure")
    elif not at_stake:
        reasons.append(f"value_below_{basis}_threshold")
    if material and at_stake and not topics:
        reasons.append("no_topic_in_the_catalogue")
    warranted = material and at_stake and bool(topics)
    return Verdict(case.selection.key, material, at_stake, None if value is None else str(value), basis, topics, warranted,
                   tuple(reasons) or ("warranted",))


def decide(cases: Sequence[Case], *, minutes_to_kickoff: int | None) -> Round:
    """The match's round. Pure and deterministic: the cases may come in any order."""
    verdicts = tuple(judge(c) for c in sorted(cases, key=lambda c: (len(c.selection.key), c.selection.key)))
    warranted = [v for v in verdicts if v.warranted]
    reasons: list[str] = []
    if not warranted:
        reasons.append("no_selection_warrants_it")
    if minutes_to_kickoff is None:
        reasons.append("kickoff_unknown")
    elif minutes_to_kickoff < MIN_MINUTES:
        reasons.append("too_close_to_kickoff")
    requested = bool(warranted) and not reasons
    topics: tuple[str, ...] = ()
    if requested:
        count: dict[str, int] = {}
        for v in warranted:
            for t in v.topics:
                count[t] = count.get(t, 0) + 1
        chosen = sorted(count, key=lambda t: (-count[t], TOPICS.index(t)))[:TOPICS_MAX]
        topics = _order(set(chosen))
    return Round(requested, topics, tuple(v.candidate for v in warranted) if requested else (), tuple(reasons) or ("requested",),
                 verdicts, minutes_to_kickoff)


__all__ = ["MIN_EDGE", "MIN_EV", "MIN_MINUTES", "TOPICS", "TOPICS_MAX", "TOPIC_OF_SIGNAL", "VERSION", "Case", "Round", "Verdict", "decide",
           "judge", "topics_of", "value_of"]
