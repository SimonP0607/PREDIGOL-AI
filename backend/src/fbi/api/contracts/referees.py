"""Referees as people (plan F3): the Admin Console's queue of doubts and the page of a referee.

A referee is a person (``core.referees``); the strings the provider wrote for him are his aliases (``core.referee_aliases``), and
the rules (``fbi.people.referee_identity``) decide which spellings are one person. What they are not sure of waits in the queue as a
pair; a person merges it, says it is two men, or later takes the decision back. Every action is an event that can be read."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

PairStatus = Literal["open", "rejected", "merged"]
RefereeStatus = Literal["active", "merged"]


class RefereeSummary(Contract):
    id: int
    name: str = Field(description="How he is shown: the fullest spelling the provider used, or the name an owner gave him.")
    country: str | None = Field(description="The country he referees from (the scope of his spellings); null when not known.")
    status: RefereeStatus
    merged_into: int | None = Field(description="The referee he was merged into (status `merged`).")
    name_locked: bool = Field(description="An owner chose the name: the rules no longer change it.")
    matches: int = Field(description="The matches he has now (the provider's newest word on each).")
    first_match: datetime | None
    last_match: datetime | None


class RefereeAlias(Contract):
    id: int
    display: str = Field(description="The string the provider wrote, put in order ('Michael Oliver', 'M. Oliver').")
    name_key: str = Field(description="The name compared: lower case, no accents or punctuation.")
    country: str | None = Field(description="The scope of the spelling: the country it names or the competitions it appears in.")
    basis: str = Field(description="Why it is his: identity, extension, initial, visitor, scope or manual.")
    placed_by: str = Field(description="`rules` or `manual`.")
    matches: int
    first: datetime | None
    last: datetime | None


class RefereeMatch(Contract):
    fixture_id: int
    kickoff_at: datetime | None
    home: str
    away: str
    competition: str
    season: int
    spelling: str = Field(description="How the provider wrote his name for this match.")


class RefereeSide(Contract):
    id: int
    name: str
    country: str | None
    matches: int


class RefereePair(Contract):
    """Two referees the rules could not settle (or an owner decided about)."""

    id: int
    a: RefereeSide
    b: RefereeSide
    reason: str = Field(description="Why the rules doubt: the two are one name apart, an initial fits two, they never share a day...")
    score: float
    impact: int = Field(description="Matches the doubt touches (the smaller side's), what the queue is ordered by.")
    evidence: dict[str, Any]
    status: PairStatus
    decided_by: str | None
    decided_at: datetime | None


class RefereeCandidate(Contract):
    """A pair seen from one of its referees."""

    id: int
    other: RefereeSide
    reason: str
    score: float
    impact: int
    evidence: dict[str, Any]
    status: PairStatus
    decided_by: str | None
    decided_at: datetime | None


class RefereeEvent(Contract):
    id: int
    at: datetime
    actor: str = Field(description="`admin:<email>`, `script:referee_identity` or `rules`.")
    action: str = Field(description="merge, undo, split, reject, reopen or rename.")
    referee_id: int | None
    other_id: int | None
    alias_ids: list[int]
    undone_by: int | None = Field(description="The event that took this merge back.")
    detail: dict[str, Any]


class RefereeCounts(Contract):
    referees_active: int
    referees_merged: int
    aliases: int
    fixtures_with_referee: int
    candidates_open: int
    candidates_rejected: int
    candidates_merged: int
    matches_with_a_doubt: int
    settled_share: float = Field(description="Share of the matches with a referee whose referee has no doubt waiting.")
    problems: list[str] = Field(description="Invariants of the tables that do not hold (empty when all is well).")


class RefereeList(Contract):
    items: list[RefereeSummary]
    total: int = Field(description="Active referees (or those matching the search).")
    queue_open: int
    counts: RefereeCounts


class RefereeQueue(Contract):
    items: list[RefereePair]
    total: int
    status: PairStatus
    reason: str | None


class RefereeDetail(Contract):
    referee: RefereeSummary
    aliases: list[RefereeAlias]
    recent_matches: list[RefereeMatch]
    candidates: list[RefereeCandidate]
    events: list[RefereeEvent]


class MergeIn(Contract):
    merge_id: int = Field(ge=1, description="The referee that is merged INTO the one in the path.")
    note: str | None = Field(default=None, max_length=500)
    force: bool = Field(default=False, description="Merge even if the two have matches at the same time (they are then two men "
                        "who happen to be recorded for one: use only when the provider's data is wrong).")


class SplitIn(Contract):
    alias_ids: list[int] = Field(min_length=1, max_length=200, description="The spellings that go to a NEW referee.")
    name: str | None = Field(default=None, max_length=120, description="The new referee's name; by default his fullest spelling.")
    note: str | None = Field(default=None, max_length=500)


class PairIn(Contract):
    other_id: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


class RenameIn(Contract):
    name: str | None = Field(max_length=120, description="The name to show; null gives the naming back to the rules.")


class ActionResult(Contract):
    action: Literal["merge", "undo", "split", "reject", "reopen", "rename"]
    event_id: int | None = Field(description="The event the action wrote (what `undo` of a merge takes).")
    referee_id: int = Field(description="The referee the action leaves in front: the one kept, the new one, the one renamed...")
    other_id: int | None
    referee: RefereeSummary
