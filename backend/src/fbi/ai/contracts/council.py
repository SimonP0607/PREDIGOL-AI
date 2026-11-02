"""``cd-v1``: the Council's verdict on each selection of a match (Sonnet 5.5, Opus 5.5 where ``router-v1`` says so).

One verdict per selection - ``APPROVE``, ``DOWNGRADE``, ``REJECT`` or ``ABSTAIN`` - with how sure the Council is (``Level``), the
signals that drive it and the risks it sees, in CODES, and the references it stands on: ``A:`` the assessments of the agents it was
shown, ``E:`` evidence, ``P:`` blocks of the package. And at most one request for the server to look into a topic of the closed list
(the second round of the Council, which ``router-v1`` admits or not). No sentence, no number of its own, no probability: the server
adds ``p_model`` and ``p_market`` from the package when it stores the verdict.

The escalation to Opus is NOT a field the Council writes. ``router-v1`` decides it from the package and from this very output, by
rules (E1..E7, section 11 of the plan), never because a model asks; the server stores the mark with the run (``Escalation``) and keeps
both verdicts.

``check`` is what the server does before storing: a verdict that rests on nothing that stands becomes ``ABSTAIN`` - as ``fbi.ai.claims``
does today for a review - and the decision layer then goes on with the rules' reviewer. A verdict never raises a state: filter 6
combines as it always did, the most conservative wins.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Final, Literal

from pydantic import Field, field_validator, model_validator

from fbi.ai.contracts.assessment import REFS_MAX, ResearchAsk, refs_are_well_formed
from fbi.ai.contracts.base import (
    CANDIDATE,
    Contract,
    Level,
    RiskCode,
    SignalCode,
    Verdict,
    check_refs,
    parse_ref,
)

VERDICTS_MAX: Final = 12
DRIVERS_MAX: Final = 4
RISKS_MAX: Final = 4

EscalationRule = Literal["E1", "E2", "E3", "E4", "E5", "E6", "E7"]


class SelectionVerdict(Contract):
    candidate: str
    verdict: Verdict
    confidence: Level
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


class CouncilOut(Contract):
    contract: Literal["cd-v1"]
    verdicts: list[SelectionVerdict] = Field(max_length=VERDICTS_MAX)
    research: list[ResearchAsk] = Field(max_length=1)

    @model_validator(mode="after")
    def _one_verdict_each(self) -> CouncilOut:
        keys = [v.candidate for v in self.verdicts]
        if len(set(keys)) != len(keys):
            raise ValueError("a selection has one verdict")
        return self


class Escalation(Contract):
    """What the server stores beside a verdict when ``router-v1`` sent the case to Opus: never written by a model."""

    rule: EscalationRule
    from_run_id: int
    skipped: bool
    """True when Opus' allowance was spent: the selection keeps Sonnet's verdict and is marked ``escalation_skipped``."""


@dataclass(frozen=True, slots=True)
class Change:
    candidate: str
    was: str
    now: str
    why: str


@dataclass(frozen=True, slots=True)
class Verified:
    council: CouncilOut
    changes: tuple[Change, ...] = ()
    problems: tuple[str, ...] = ()
    unknown_refs: tuple[str, ...] = field(default=())

    @property
    def valid(self) -> bool:
        return not self.problems


def check(out: CouncilOut, *, asked: Collection[str], evidence_ids: Collection[int], paths: Collection[str],
          assessments: Collection[str]) -> Verified:
    """The Council's answer as the server keeps it. Invalid as a whole: a selection that was not asked about, one that was and has no
    verdict, a reference that exists nowhere. A verdict that rests on nothing that stands is an ``ABSTAIN``: an ``APPROVE`` needs a
    driver and a reference to an assessment or a block of the package; a ``REJECT`` or ``DOWNGRADE`` needs a driver or a risk and a
    reference that stands."""
    problems: list[str] = []
    asked_set = set(asked)
    for v in out.verdicts:
        if v.candidate not in asked_set:
            problems.append(f"candidate_not_asked:{v.candidate}")
    for key in sorted(asked_set - {v.candidate for v in out.verdicts}):
        problems.append(f"candidate_missing:{key}")
    every = [r for v in out.verdicts for r in v.refs] + [r for a in out.research for r in a.refs]
    unknown = check_refs(every, evidence_ids=evidence_ids, paths=paths, assessments=assessments)
    if unknown:
        problems.append("reference_not_in_the_package")
    changes: list[Change] = []
    verdicts: list[SelectionVerdict] = []
    for v in out.verdicts:
        standing = [r for r in v.refs if r not in unknown]
        kinds = {parsed.kind for r in standing if (parsed := parse_ref(r)) is not None}
        if v.verdict == "APPROVE" and not (v.drivers and kinds & {"A", "P"}):
            changes.append(Change(v.candidate, v.verdict, "ABSTAIN", "approve_without_data_in_its_favour"))
            verdicts.append(v.model_copy(update={"verdict": "ABSTAIN"}))
        elif v.verdict in ("DOWNGRADE", "REJECT") and not ((v.drivers or v.risks) and standing):
            changes.append(Change(v.candidate, v.verdict, "ABSTAIN", "against_without_a_reference_that_stands"))
            verdicts.append(v.model_copy(update={"verdict": "ABSTAIN"}))
        else:
            verdicts.append(v)
    return Verified(out.model_copy(update={"verdicts": verdicts}), tuple(changes), tuple(problems), tuple(unknown))
