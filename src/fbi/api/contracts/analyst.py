from __future__ import annotations

from typing import Any

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
