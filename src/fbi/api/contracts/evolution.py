"""The evolution loop in the Admin Console: proposals for the owner, and what was learned."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

HypothesisStatus = Literal["PROPOSED", "ACCEPTED", "REJECTED", "RUNNING", "DONE"]


class Hypothesis(Contract):
    id: int
    proposed_by: Literal["ai", "owner", "system"]
    title: str
    hypothesis: str
    rationale: str
    evidence: dict[str, Any]
    status: HypothesisStatus
    experiment_ids: list[int]
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None = Field(description="The deciding account's email.")
    decision_note: str | None


class MemoryEntry(Contract):
    id: int
    topic: str
    finding: str
    evidence: dict[str, Any]
    source: Literal["research_v2", "prospective", "audit", "owner"]
    created_at: datetime
    versions: int = Field(description="How many findings this topic has had, this one included.")


class LastRun(Contract):
    name: str
    code_version: str | None
    finished_at: datetime | None


class EvolutionOverview(Contract):
    loop: list[str]
    hypotheses: list[Hypothesis]
    memory: list[MemoryEntry] = Field(description="Each topic's current finding; earlier ones are kept, superseded.")
    last_monitor: datetime | None
    last_v2: LastRun | None
    v2_due: str | None = Field(description="Why the weekly research-V2 job would run now, or null.")


class HypothesisIn(Contract):
    title: str = Field(min_length=5, max_length=160)
    hypothesis: str = Field(min_length=5, max_length=600)
    rationale: str = Field(min_length=5, max_length=1000)


class DecisionIn(Contract):
    decision: Literal["accept", "reject"]
    note: str | None = Field(default=None, max_length=500)
