"""Research by entity and topic, for the Admin Console (plan IA, phase 2): what research v2 does and has done, in the words of the plan - one
answer per entity and topic, the class of each source, how fresh an answer is and how often it was reused - beside the week of comparison with
v1 and the gate that decides whether v2 may replace it. Reading only: nothing here searches, calls a model, writes a claim or changes a switch."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.envelope import Section

ResearchWord = Literal["off", "shadow", "on"]


class GateRow(Contract):
    """One row of ``ai.feature_gates`` for the gate ``research_v2`` (append-only: the newest decides)."""

    id: int
    at: datetime
    passed: bool
    decided_by: str
    code_version: str | None = None
    evidence_hash: str


class ResearchSwitch(Contract):
    """The switch ``FBI_AI_RESEARCH_V2`` as the owner set it, as the cycle reads it, and the evidence behind ``on``."""

    asked: ResearchWord = Field(description="The owner's word.")
    mode: ResearchWord = Field(description="What the cycle does: ``on`` holds only while the newest row of the gate passed, otherwise it is ``shadow``.")
    why: str
    typed_visible: bool = Field(description="The typed claims are part of what the system reads and shows: only with ``on`` in force.")
    gate_passed: bool = Field(description="The newest row of the gate says it passed (false also when there is none).")
    gate_at: datetime | None = Field(default=None, description="When the newest row was written; null = the gate never ran.")
    history: list[GateRow] = Field(default_factory=list)


class TopicRow(Contract):
    """One topic of the research and what the cache holds for it."""

    topic: str
    entity: str = Field(description="What an answer is about: TEAM for the first two topics, MATCH for the preview.")
    levels: list[int] = Field(description="The levels of the tiered search that serve the topic.")
    label: str = Field(description="The topic as the code names it for the owner.")
    early_hours: float = Field(description="How long an answer is reused while the nearest kick-off of the entity is farther than the late window.")
    late_hours: float = Field(description="... and inside it.")
    entries: int = Field(description="Answers kept, one per entity.")
    fresh: int
    expired: int
    reuses: int = Field(description="Times an answer was read instead of searched again (``hits``, since each row was first written).")
    newest_at: datetime | None = None
    last_reuse_at: datetime | None = None


class Freshness(Contract):
    late_window_hours: float
    topics: list[TopicRow]
    unreadable: int = Field(description="Rows of the entity scope whose key this code does not read: shown as a count, never guessed at.")


class AnswerRow(Contract):
    """One answer kept for an entity on a topic (``ai.research_cache``, scope ``entity``), the newest first."""

    kind: str
    id: int
    name: str | None = Field(default=None, description="The team, or ``home vs away`` for a match; null for an entity the page cannot name.")
    kickoff_at: datetime | None = None
    topic: str
    level: int | None = None
    results: int | None = Field(default=None, description="Results the search found.")
    standing: bool | None = Field(default=None, description="At least one result came from a source of known standing.")
    tiers: dict[str, int] = Field(default_factory=dict, description="The results by the tier of their domain.")
    fetched_at: datetime
    expires_at: datetime
    fresh: bool
    reuses: int
    last_reuse_at: datetime | None = None
    claims: int = Field(description="Typed claims about the entity (a team's include its players') retrieved in the window.")
    claims_fresh: int = Field(description="... of them, the ones that can still be reused without asking again.")


class ClaimBreakdown(Contract):
    """The typed claims of one class of source (or one type of claim) by status."""

    key: str
    total: int
    fresh: int
    by_status: dict[str, int]


class Claims(Contract):
    """The claims research v2 wrote (``ai.evidence.subject_type`` is not NULL) in the window."""

    total: int
    fresh: int = Field(description="Claims whose ``fresh_until`` has not passed.")
    entity_scoped: int = Field(description="Claims about a team or a player with no match: the next match of the team reads them too.")
    match_scoped: int
    flagged: int = Field(description="Claims read from a page that sounded like an order to a model: they count as an unknown source.")
    by_status: dict[str, int]
    by_class: list[ClaimBreakdown]
    by_type: list[ClaimBreakdown]


class ResearchDay(Contract):
    """One Bogotá day of the cycle's passes: what v1 searched and what research v2 needed, paid, borrowed and reused."""

    day: date
    passes: int
    passes_v2: int = Field(description="Passes that ran research v2 (in shadow or in force).")
    passes_failed: int = Field(description="... in which research v2 failed (the pass went on with v1).")
    passes_cut: int = Field(description="... in which a budget or an outage of the search stopped it.")
    searches: int = Field(description="Searches the passes paid for (v1's; research v2's own when it was in force).")
    demand: int = Field(description="Searches research v2 needed: levels with an entity whose answer was not fresh.")
    paid: int
    shared: int = Field(description="... answered by a search already paid for (v1's, or an earlier pass's).")
    reused: int = Field(description="Entity answers that were still fresh: searches it did not need.")
    pages: int
    pages_known: int = Field(description="Pages not shown to the extractor again: already read for the same subjects.")
    claims: int
    claims_new: int
    exa_v1_usd: Decimal
    exa_v2_usd: Decimal


class PageCache(Contract):
    """The pages research v2 remembers having read (scope ``url``): one key for the page, whatever match asked."""

    remembered: int
    fresh: int
    reuses: int
    read: int = Field(description="Pages shown to the extractor in the window.")
    known: int = Field(description="Pages it did not need to show again.")
    unread: int = Field(description="Pages beyond the cap of one reading: left for the next pass.")
    flagged: int = Field(description="Pages that read like an order to a model.")


class Comparison(Contract):
    """The window of the page, v1 against research v2, over the passes in which both finished. The same arithmetic as the gate's, over days the gate
    may not accept: a reading of how it goes, not evidence of it."""

    first: date
    last: date
    passes_in_shadow: int
    passes_compared: int
    passes_v2_failed: int
    passes_v2_cut_short: int
    searches_v1: int
    searches_v2_alone: int = Field(description="What research v2 would have paid without v1 beside it: what it paid plus what a cache answered.")
    saved: int
    saved_pct: Decimal | None = None
    reuse_pct: Decimal | None = Field(default=None, description="The share of its needs that a fresh answer already satisfied.")
    fixtures: int
    facts_v1: int
    facts_v2: int
    found_by_v2: int
    coverage_pct: Decimal | None = None
    coverage_players_pct: Decimal | None = None
    facts_per_match_v1: float | None = None
    facts_per_match_v2: float | None = None
    missed_examples: list[list[Any]] = Field(default_factory=list, description="Facts of v1 that research v2 did not find: fixture, side, who, class.")
    exa_v1_searches: int
    exa_v1_usd: Decimal
    exa_v2_searches: int
    exa_v2_usd: Decimal
    extractor_calls: int
    extractor_by_status: dict[str, int]
    extractor_invalid_pct: Decimal | None = None


class GateWindow(Contract):
    first: date
    last: date
    days: int
    anchor: date | None = None
    anchored_by: str
    stable_complete_days: int
    eligible_on: date
    complete: bool


class GateCheckRow(Contract):
    id: str
    title: str
    ok: bool | None = Field(description="Null: it cannot be judged yet.")
    mark: str
    detail: dict[str, Any] = Field(default_factory=dict)
    revert: str | None = None


class GateView(Contract):
    """The gate of research v2 evaluated now (``fbi.ai.gate_research``). Evaluating writes nothing: only ``python -m scripts.ia_research_gate evaluate
    --record`` does."""

    verdict: str = Field(description="PASA, NO PASA or PENDIENTE POR TIEMPO REAL.")
    at: datetime
    window: GateWindow
    checks: list[GateCheckRow] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    consequence: str | None = None
    preview: dict[str, Any] = Field(default_factory=dict, description="What the days gone show when the verdict is pending: not evidence of the gate.")


class ResearchOverview(Contract):
    days: int
    since: datetime
    switch: ResearchSwitch
    freshness: Freshness
    answers: list[AnswerRow]
    claims: Claims
    per_day: list[ResearchDay]
    pages: PageCache
    comparison: Section[Comparison | None]
    gate: Section[GateView | None]
