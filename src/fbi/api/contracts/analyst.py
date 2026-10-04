from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from fbi.api.contracts.common import Contract


class ToolSpec(Contract):
    name: str
    description: str
    parameters: dict[str, Any]
    endpoint: str


class AnalystStatus(Contract):
    configured: bool
    missing: list[str] = Field(description="Environment variables still to set on the API host. Never values.")
    tools: list[ToolSpec]
    rules: list[str]


class Citation(Contract):
    id: str
    tool: str
    arguments: dict[str, Any]
    ok: bool
    status: str | None
    provenance: dict[str, Any] | None
    error: str | None


class AnalystReply(Contract):
    text: str
    citations: list[Citation]
    unverified_figures: list[str] = Field(description="Numbers in the answer that no tool result contains.")
    rounds: int
    stopped: str | None


class Question(Contract):
    question: str = Field(min_length=1, max_length=1000)


class AiBudget(Contract):
    month: str
    cap_usd: Decimal
    spent_usd: Decimal
    left_usd: Decimal


class AiRunRow(Contract):
    id: int
    kind: str
    model: str | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    tool_calls: int
    error: str | None
    detail: dict[str, Any]


class AiStatus(Contract):
    llm_configured: bool
    model: str | None
    search_configured: bool
    missing: list[str] = Field(description="Environment variables still to set on the API host. Never values.")
    budget: AiBudget
    questions_today: int
    questions_per_day: int
    last_runs: list[AiRunRow] = Field(description="The latest run of each kind.")
    schedule: dict[str, str]


class AiClaimRow(Contract):
    id: int
    fixture_id: int | None
    team_id: int | None
    claim: str
    source_url: str
    also_urls: list[str]
    publisher: str | None
    published_at: datetime | None
    retrieved_at: datetime
    confidence: Literal["CONFIRMED", "REPORTED", "RUMOR"]


class AiReport(Contract):
    id: int
    run_id: int
    day: date
    source: Literal["qualified", "evaluation"]
    markdown: str
    claims: list[AiClaimRow]
    created_at: datetime
    run_status: str
    model: str | None
    cost_usd: Decimal


class AiFlagRow(Contract):
    id: int
    run_id: int
    engine: Literal["rules", "model"]
    set_id: int | None
    rank: int | None
    fixture_id: int
    match: str
    code: str
    severity: Literal["info", "warn", "review"]
    note: str
    claim_ids: list[int]
    created_at: datetime


class AiFlags(Contract):
    day: date
    source: Literal["qualified", "evaluation"]
    set_id: int | None
    flags: list[AiFlagRow]


class RunReportIn(Contract):
    day: date | None = None
    source: Literal["qualified", "evaluation"] | None = None
