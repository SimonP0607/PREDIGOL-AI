"""The AI decision layer's contracts: the per-match analysis users read, and the Admin Console's views
(overview, reviews with their full audit trail, packets, evidence, costs, the AI's shadow report, memory)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract

Verdict = Literal["recommended", "caution", "not_recommended", "no_market"]
Decision = Literal["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"]


class Claim(Contract):
    text: str
    type: str
    code: str | None = None
    params: dict[str, Any] | None = None
    refs: list[str] = Field(default_factory=list)


class CardAi(Contract):
    decision: Decision
    review_id: int | None
    confidence: float | None
    reason: str | None
    positives: list[Claim] = Field(default_factory=list)
    risks: list[Claim] = Field(default_factory=list)
    engines: list[str] = Field(default_factory=list)


class AnalysisCard(Contract):
    market: str
    selection: str
    line: Decimal
    kind: Literal["value", "evaluated", "no_market"]
    odds: Decimal | None
    bookmaker: str | None
    p_model: Decimal | None
    p_low: Decimal | None
    p_market: Decimal | None
    fair_odds: Decimal | None
    minimum_odds: Decimal | None = Field(description="The lowest price at which the selection would be worth it "
                                                     "at the model's pessimistic probability.")
    edge: Decimal | None
    ev: Decimal | None
    model: str | None
    qualified: bool
    verdict: Verdict
    verdict_reason: str
    ai: CardAi | None


class MatchAnalysis(Contract):
    fixture_id: int
    built_at: datetime | None
    audience: Literal["user", "evaluation"]
    mode: Literal["off", "shadow", "enforce"]
    enforced: bool = Field(description="True only when the owner enabled enforcement AND the AI's shadow gate passed.")
    market_observed: bool
    engines: list[str]
    analyzed_by_llm: bool = Field(description="A language model reviewed at least one selection of this match.")
    cards: list[AnalysisCard]
    withheld: int = Field(description="Cards a user does not see: their pick is in evaluation (shadow).")
    missing: list[str] = Field(default_factory=list, description="Context blocks the packet could not fill.")


class AiTier(Contract):
    provider: str
    model: str
    key_present: bool


class CycleRow(Contract):
    id: int
    kind: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    mode: str
    budget_state: str
    counts: dict[str, Any]
    cost_usd: Decimal
    error: str | None


class AiOverview(Contract):
    settings: dict[str, Any]
    budget: dict[str, Any]
    enforcement: dict[str, Any]
    last_cycles: list[CycleRow]
    today: dict[str, Any]
    shadow: list[dict[str, Any]]


class ReviewRow(Contract):
    id: int
    reviewed_at: datetime
    fixture_id: int
    match: str
    kickoff_at: datetime
    competition: str
    market_key: str
    selection: str
    line: Decimal
    odds: Decimal | None
    p_model: Decimal | None
    p_market: Decimal | None
    edge: Decimal | None
    decision: Decision
    confidence: Decimal
    engine: str
    engine_version: str
    model: str | None
    reason: str | None
    status: str
    mode: str
    cost_usd: Decimal


class UsageRow(Contract):
    id: int
    at: datetime
    purpose: str
    tier: str
    provider: str
    model: str
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    searches: int
    cost_usd: Decimal
    latency_ms: int | None
    status: str
    error: str | None


class ReviewDetail(Contract):
    review: ReviewRow
    output: dict[str, Any]
    sources: list[Any]
    evidence: list[dict[str, Any]]
    packet: dict[str, Any] | None
    components: list[ReviewRow]
    usage: list[UsageRow]
    input_hash: str


class PacketView(Contract):
    id: int
    fixture_id: int
    packet_version: str
    as_of: datetime
    built_at: datetime
    packet_hash: str
    approx_tokens: int
    missing: list[str]
    content: dict[str, Any]
    sources: list[Any]
    history: list[dict[str, Any]]


class EvidenceRow(Contract):
    id: int
    fixture_id: int | None
    match: str | None
    team: str | None
    kind: str
    claim: str
    origin: str
    source_name: str
    source_url: str | None
    source_tier: str
    published_at: datetime | None
    retrieved_at: datetime
    status: Literal["CONFIRMED", "PROBABLE", "RUMOR", "CONTRADICTORY", "OUTDATED"]
    status_reason: str
    status_history: list[Any]
    attributes: dict[str, Any]


class MemoryEvent(Contract):
    id: int
    created_at: datetime
    kind: str
    entity_type: str
    entity_id: str
    fixture_id: int | None
    hypothesis: str | None
    evidence: dict[str, Any]
    result: str | None
    confidence: Decimal | None
    version: str


class RunIn(Contract):
    kind: Literal["analysis", "learning"] = "analysis"
    fixture_id: int | None = Field(default=None, ge=1)


class RunQueued(Contract):
    id: int
    kind: str
    status: str
    requested_at: datetime


class EvolutionDashboard(Contract):
    day: date
    counts: dict[str, Any]
    findings: list[MemoryEvent]
    errors: list[dict[str, Any]]
    shadow: list[dict[str, Any]]
    cost_usd: Decimal
