"""The day's selection funnel, for the Admin Console (REVIEW PREDIGOL B1): how many candidates reached each stage of
the daily set's rule, why the others stopped, what the next build would choose and what nearly made it."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.product import CompetitionBadge, TeamBadge


class FunnelStage(Contract):
    key: Literal["data", "market", "model", "calibration", "value", "risk", "context", "selection"]
    entered: int
    passed: int
    reasons: dict[str, int] = Field(description="Why the ones that stopped here stopped, by reason code.")


class FunnelItem(Contract):
    day: date | None = Field(default=None, description="The product day whose set it would enter.")
    stage: str | None = Field(default=None, description="Where it stopped; null for a selection the build chooses.")
    reason: str | None = None
    pick_id: int
    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    market_key: str
    selection: str
    line: Decimal
    odds: Decimal
    bookmaker: str | None
    p_model: Decimal
    p_low: Decimal
    p_market: Decimal
    ev: Decimal
    growth: Decimal = Field(description="Expected log growth of a 1% stake at p_low: what the set ranks by.")
    ai_decision: str | None = Field(default=None, description="The newest review's decision (null: not reviewed).")
    evidence: dict[str, int] = Field(default_factory=dict, description="Outside evidence about the match by status.")


class SelectionFunnel(Contract):
    at: datetime
    source: Literal["qualified", "evaluation"]
    rule_version: str
    risk_version: str
    max_odds: Decimal | None
    context_version: str
    ai_mode: str
    ai_enforced: bool
    candidates: int = Field(description="Candidate rows read: the picks of the next 24 hours.")
    selections: int = Field(description="Distinct selections among them (match, market, selection, line).")
    stages: list[FunnelStage]
    chosen: list[FunnelItem]
    near: list[FunnelItem] = Field(description="The best selections that passed value and stopped later, and why.")
    in_set: dict[str, int] = Field(description="Items already in each day's set (product day -> count).")
