"""``pmr-v1``: what the Post-Match Reviewer writes about a finished match - which signal of which agent hit and which missed, and why.

The ARITHMETIC of the attribution is the server's (``fbi.ai.agents.attribution``, phase 5): whether each signal pointed towards the
result and towards the closing line, whether the model was better or worse calibrated than the market. The reviewer (Haiku 5.5, Batch)
only CLASSIFIES the ambiguous rows into the error classes of the post-mortem ``pm-v6`` (``fbi.intel.pm_questions``: the same words) and
writes a short narrative. The class is measured; the narrative never is, and it is never a reason for anything an agent does next.

A hit has no error class (``NONE``); a miss always has one. ``NORMAL_VARIANCE`` is the class of a good decision that lost: judged by the
closing-line value and the calibration, not by the result - a good decision also loses.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import Field, field_validator, model_validator

from fbi.ai.contracts.assessment import REFS_MAX, refs_are_well_formed
from fbi.ai.contracts.base import CANDIDATE, Contract, Outcome

ROWS_MAX: Final = 40
NARRATIVE_MAX: Final = 900

Attributed = Literal["match", "stats", "council"]
AttributedSignal = Literal[
    "ABSENCES", "LINEUP", "SCHEDULE", "STAKES", "FORM", "H2H", "TACTICS", "VENUE", "REFEREE", "MARKET_MOVE",
    "MODEL_MARKET_GAP", "NEWS", "RATE", "DATA_QUALITY", "VERDICT"]
"""A signal of ``aa-v1``, or ``VERDICT``: the Council's verdict itself (held equal to ``SignalCode`` plus ``VERDICT`` by a test)."""
AttributionClass = Literal["MODEL_ERROR", "CONTEXT_ERROR", "DATA_ERROR", "MARKET_ERROR", "EXECUTION_ERROR", "NORMAL_VARIANCE",
                           "UNKNOWN", "NONE"]


class Attribution(Contract):
    candidate: str
    agent: Attributed
    signal: AttributedSignal
    outcome: Outcome
    error_class: AttributionClass
    refs: list[str] = Field(max_length=REFS_MAX)

    _refs = field_validator("refs")(refs_are_well_formed)

    @field_validator("candidate")
    @classmethod
    def _a_candidate_key(cls, v: str) -> str:
        if CANDIDATE.match(v) is None:
            raise ValueError("a candidate is named c1, c2... as the package names it")
        return v

    @model_validator(mode="after")
    def _a_miss_has_a_class_and_a_hit_has_none(self) -> Attribution:
        if (self.outcome == "MISS") == (self.error_class == "NONE"):
            raise ValueError("a MISS has an error class and a HIT or a VOID has NONE")
        return self


class PostMatchOut(Contract):
    contract: Literal["pmr-v1"]
    attributions: list[Attribution] = Field(max_length=ROWS_MAX)
    narrative: str = Field(max_length=NARRATIVE_MAX)
    """Plain prose for the owner, UNTRUSTED: it is shown, never measured and never read as an instruction."""

    @model_validator(mode="after")
    def _a_signal_is_attributed_once(self) -> PostMatchOut:
        keys = [(a.candidate, a.agent, a.signal) for a in self.attributions]
        if len(set(keys)) != len(keys):
            raise ValueError("a signal of an agent is attributed once per selection")
        return self
