"""``aa-v1``: what the Match Agent and the Statistics Agent write about a match - signals, and for each candidate a stance.

An assessment is made of CODES. A signal says what it points at (``SignalCode``), which way (``Direction``), how strongly (``Level``)
and what it rests on (typed references into the package: ``E:`` an evidence, ``P:`` a path). A candidate says what the agent makes of
it: ``SUPPORT``, ``NEUTRAL``, ``CONCERN`` or ``REJECT_SIGNAL``, the signals that drive that (``drivers``) and the risks it sees
(``risks``). There is no sentence in it, no number of the agent's own and no probability: what a page, a name or a note could say
through it is limited to choosing among these words - and a stance that rests on no reference that exists does not stand (``check``).

Two modes with one contract: ``CONTEXT`` (every match with a market, once per pass with a material change: signals and, if something is
missing, one request for the server to look into a topic of the closed list) and ``EVALUATION`` (a match with candidates: one stance
per candidate). The Statistics Agent writes the same thing about corners and cards.

``check`` is what the server does with the answer before anything is stored. It never raises a stance: a stance that rests on nothing
becomes ``NEUTRAL`` and the change is said; an answer about candidates the server did not ask about, or one missing for a candidate it
did, is invalid as a whole (the agent then abstains and the Council reads the others).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Final, Literal

from pydantic import Field, field_validator, model_validator

from fbi.ai.contracts.base import (
    CANDIDATE,
    REF,
    Agent,
    Contract,
    Direction,
    Level,
    Mode,
    Quality,
    ResearchTopic,
    RiskCode,
    Side,
    SignalCode,
    Stance,
    check_refs,
    parse_ref,
)

SIGNALS_MAX: Final = 12
CANDIDATES_MAX: Final = 12
REFS_MAX: Final = 8
DRIVERS_MAX: Final = 4
RISKS_MAX: Final = 4


def refs_are_well_formed(refs: list[str]) -> list[str]:
    for text in refs:
        if REF.match(text) is None:
            raise ValueError(f"{text!r} is not a reference (E:<id>, P:<path> or A:<id>)")
    return refs


class Signal(Contract):
    code: SignalCode
    direction: Direction
    strength: Level
    refs: list[str] = Field(max_length=REFS_MAX)

    _refs = field_validator("refs")(refs_are_well_formed)


class CandidateAssessment(Contract):
    candidate: str
    stance: Stance
    drivers: list[SignalCode] = Field(max_length=DRIVERS_MAX)
    risks: list[RiskCode] = Field(max_length=RISKS_MAX)
    refs: list[str] = Field(max_length=REFS_MAX)

    _refs = field_validator("refs")(refs_are_well_formed)

    @field_validator("candidate")
    @classmethod
    def _a_candidate_key(cls, v: str) -> str:
        if CANDIDATE.match(v) is None:
            raise ValueError("a candidate is named c1, c2... as the package names it")
        return v


class ResearchAsk(Contract):
    """A request for the server to look into a topic of ``fbi.ai.research``'s list - never a query, a name or a number of searches.
    ``refs`` is why: the evidence or the blocks that show what is missing."""

    topic: ResearchTopic
    side: Side
    refs: list[str] = Field(max_length=REFS_MAX)

    _refs = field_validator("refs")(refs_are_well_formed)


class AssessmentOut(Contract):
    contract: Literal["aa-v1"]
    agent: Agent
    mode: Mode
    data_quality: Quality
    signals: list[Signal] = Field(max_length=SIGNALS_MAX)
    candidates: list[CandidateAssessment] = Field(max_length=CANDIDATES_MAX)
    research: list[ResearchAsk] = Field(max_length=1)

    @model_validator(mode="after")
    def _the_shape_of_each_mode(self) -> AssessmentOut:
        if self.mode == "CONTEXT" and self.candidates:
            raise ValueError("a CONTEXT reading has no candidates")
        keys = [c.candidate for c in self.candidates]
        if len(set(keys)) != len(keys):
            raise ValueError("a candidate is assessed once")
        pairs = [(s.code, s.direction) for s in self.signals]
        if len(set(pairs)) != len(pairs):
            raise ValueError("a signal (code and direction) is written once")
        return self


@dataclass(frozen=True, slots=True)
class Change:
    candidate: str
    was: str
    now: str
    why: str


@dataclass(frozen=True, slots=True)
class Verified:
    """The answer as the server keeps it: the stances after ``check``, what changed and what is wrong (empty when nothing is)."""

    assessment: AssessmentOut
    changes: tuple[Change, ...] = ()
    problems: tuple[str, ...] = ()
    unknown_refs: tuple[str, ...] = field(default=())

    @property
    def valid(self) -> bool:
        return not self.problems


def check(out: AssessmentOut, *, asked: Collection[str], evidence_ids: Collection[int], paths: Collection[str],
          assessments: Collection[str] = ()) -> Verified:
    """What the server makes of an answer. ``asked`` are the candidates it asked about (empty in ``CONTEXT``), ``evidence_ids`` and
    ``paths`` what the package has. Invalid as a whole: a candidate that was not asked about, one that was and is missing, a mode that
    is not the one asked, a reference that does not exist anywhere. A stance that rests on nothing becomes ``NEUTRAL``."""
    problems: list[str] = []
    unknown: list[str] = []
    asked_set = set(asked)
    for c in out.candidates:
        if c.candidate not in asked_set:
            problems.append(f"candidate_not_asked:{c.candidate}")
    for key in sorted(asked_set - {c.candidate for c in out.candidates}):
        problems.append(f"candidate_missing:{key}")
    if out.mode == "CONTEXT" and asked_set:
        problems.append("mode_context_with_candidates_asked")
    if out.mode == "EVALUATION" and not asked_set:
        problems.append("mode_evaluation_without_candidates")
    every = [r for s in out.signals for r in s.refs] + [r for c in out.candidates for r in c.refs] + \
        [r for a in out.research for r in a.refs]
    unknown = check_refs(every, evidence_ids=evidence_ids, paths=paths, assessments=assessments)
    if unknown:
        problems.append("reference_not_in_the_package")
    changes: list[Change] = []
    candidates: list[CandidateAssessment] = []
    for c in out.candidates:
        standing = [r for r in c.refs if r not in unknown and parse_ref(r) is not None]
        backed = bool(standing) and bool(c.drivers or c.risks)
        if c.stance in ("SUPPORT", "CONCERN", "REJECT_SIGNAL") and not backed:
            changes.append(Change(c.candidate, c.stance, "NEUTRAL", "no_driver_or_reference_that_stands"))
            candidates.append(c.model_copy(update={"stance": "NEUTRAL"}))
        elif c.stance == "SUPPORT" and not c.drivers:
            changes.append(Change(c.candidate, c.stance, "NEUTRAL", "support_without_a_driver"))
            candidates.append(c.model_copy(update={"stance": "NEUTRAL"}))
        else:
            candidates.append(c)
    return Verified(out.model_copy(update={"candidates": candidates}), tuple(changes), tuple(problems), tuple(unknown))
