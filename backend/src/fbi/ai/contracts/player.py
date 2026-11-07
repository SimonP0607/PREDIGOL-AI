"""``pa-v1``: what the Player Agent writes about a match (IA-017) - a POSITION on each candidate of goals and result, from who plays.

Why not ``aa-v1``. The Match and the Statistics Agents answer in ``aa-v1``, and it cannot carry this agent unchanged: its ``agent`` enum is
``match`` or ``stats``, and every signal has a ``strength`` - a magnitude the owner's rule for this agent does not allow (a direction, never
how much). ``aa-v1`` is never edited in place (the registry holds the hash of its schema, and the two agents that write it would change
version), so this is a new contract, and the smallest one: ``aa-v1`` NARROWED, never widened.

    from aa-v1   contract, agent, mode, data_quality, signals, candidates - the same names, the same caps, the same typed references
    taken out    a signal's ``strength`` (no magnitude), ``research`` (this agent never asks for one), the CONTEXT mode (it only evaluates)
    narrowed     the signal codes and the drivers to the five that are about players (``PLAYER_SIGNAL_CODES``) and the risks to the seven that
                 are about information on players (``PLAYER_RISK_CODES``): a code about a price, a model or a referee is not this agent's

A position is made of CODES: a stance (``SUPPORT``, ``NEUTRAL``, ``CONCERN``, ``REJECT_SIGNAL``), the signal codes it rests on, the risks it
sees and the references of ITS package (``E:<id>`` of its evidence, ``P:<path>`` of its slice). No sentence, no number, no probability, no
price, no stake, no market, no URL, no query: there is no field for any of them (``extra="forbid"``) and ``FORBIDDEN_WORDS`` holds the names.

``check`` is ``contracts.assessment.check`` for this contract: a stance that rests on nothing becomes NEUTRAL (and the change is said), an answer
about a candidate that was not asked, one missing for a candidate that was, or one that cites a reference the package does not have is invalid
as a whole - the agent abstains and the Council reads the others.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Final, Literal, get_args

from pydantic import Field, field_validator, model_validator

from fbi.ai.contracts.assessment import (
    CANDIDATES_MAX,
    DRIVERS_MAX,
    REFS_MAX,
    RISKS_MAX,
    SIGNALS_MAX,
    Change,
    refs_are_well_formed,
)
from fbi.ai.contracts.base import (
    CANDIDATE,
    Contract,
    Direction,
    Quality,
    Stance,
    check_refs,
    parse_ref,
)

PlayerSignalCode = Literal["ABSENCES", "LINEUP", "FORM", "NEWS", "DATA_QUALITY"]
"""What a position can point at: who is out or doubtful, the line-up and its rotation, the form of the players (their minutes, starts and
goals), news about a player that is not about who plays, and the quality of the data about players. Five of the codes of ``aa-v1``."""
PLAYER_SIGNAL_CODES: Final = get_args(PlayerSignalCode)
PlayerRiskCode = Literal["LINEUP_UNCONFIRMED", "KEY_ABSENCE_OPEN", "CONTRADICTORY_NEWS", "RUMOUR_ONLY", "ROTATION", "LATE_CHANGE", "DATA_GAP"]
"""What can make a candidate worse than it looks, as far as the players go. Seven of the risks of ``aa-v1``: the ones about a price, a model,
an interval or the stakes are not this agent's to see (its package has none of them)."""
PLAYER_RISK_CODES: Final = get_args(PlayerRiskCode)


class PlayerSignal(Contract):
    code: PlayerSignalCode
    direction: Direction
    refs: list[str] = Field(max_length=REFS_MAX)

    _refs = field_validator("refs")(refs_are_well_formed)


class PlayerPosition(Contract):
    candidate: str
    stance: Stance
    drivers: list[PlayerSignalCode] = Field(max_length=DRIVERS_MAX)
    risks: list[PlayerRiskCode] = Field(max_length=RISKS_MAX)
    refs: list[str] = Field(max_length=REFS_MAX)

    _refs = field_validator("refs")(refs_are_well_formed)

    @field_validator("candidate")
    @classmethod
    def _a_candidate_key(cls, v: str) -> str:
        if CANDIDATE.match(v) is None:
            raise ValueError("a candidate is named c1, c2... as the package names it")
        return v


class PlayerAssessmentOut(Contract):
    contract: Literal["pa-v1"]
    agent: Literal["player"]
    mode: Literal["EVALUATION"]
    data_quality: Quality
    signals: list[PlayerSignal] = Field(max_length=SIGNALS_MAX)
    candidates: list[PlayerPosition] = Field(max_length=CANDIDATES_MAX)

    @model_validator(mode="after")
    def _once_each(self) -> PlayerAssessmentOut:
        keys = [c.candidate for c in self.candidates]
        if len(set(keys)) != len(keys):
            raise ValueError("a candidate is assessed once")
        pairs = [(s.code, s.direction) for s in self.signals]
        if len(set(pairs)) != len(pairs):
            raise ValueError("a signal (code and direction) is written once")
        return self


@dataclass(frozen=True, slots=True)
class PlayerVerified:
    """The answer as the server keeps it: the positions after ``check``, what changed and what is wrong (empty when nothing is)."""

    assessment: PlayerAssessmentOut
    changes: tuple[Change, ...] = ()
    problems: tuple[str, ...] = ()
    unknown_refs: tuple[str, ...] = field(default=())

    @property
    def valid(self) -> bool:
        return not self.problems


def check(out: PlayerAssessmentOut, *, asked: Collection[str], evidence_ids: Collection[int], paths: Collection[str]) -> PlayerVerified:
    """What the server makes of an answer, as ``contracts.assessment.check`` does for ``aa-v1``: ``asked`` are the candidates it asked about,
    ``evidence_ids`` and ``paths`` what the slice has. Invalid as a whole: a candidate that was not asked about, one that was and is missing,
    nothing asked at all, a reference that does not exist. A stance that rests on nothing becomes NEUTRAL, and a SUPPORT without a driver."""
    problems: list[str] = []
    asked_set = set(asked)
    for c in out.candidates:
        if c.candidate not in asked_set:
            problems.append(f"candidate_not_asked:{c.candidate}")
    for key in sorted(asked_set - {c.candidate for c in out.candidates}):
        problems.append(f"candidate_missing:{key}")
    if not asked_set:
        problems.append("mode_evaluation_without_candidates")
    every = [r for s in out.signals for r in s.refs] + [r for c in out.candidates for r in c.refs]
    unknown = check_refs(every, evidence_ids=evidence_ids, paths=paths)
    if unknown:
        problems.append("reference_not_in_the_package")
    changes: list[Change] = []
    candidates: list[PlayerPosition] = []
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
    return PlayerVerified(out.model_copy(update={"candidates": candidates}), tuple(changes), tuple(problems), tuple(unknown))


__all__ = ["PLAYER_RISK_CODES", "PLAYER_SIGNAL_CODES", "PlayerAssessmentOut", "PlayerPosition", "PlayerRiskCode", "PlayerSignal", "PlayerSignalCode",
           "PlayerVerified", "check"]
