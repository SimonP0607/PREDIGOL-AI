"""A provider that never leaves the machine: tests, and dry runs that measure how many tokens a real
model would read and write (``fbi.ai.costs.simulate``). It answers with a scripted function of the
request, and counts tokens the way the planning estimate does (about four characters a token)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fbi.ai.pricing import approx_tokens
from fbi.ai.providers.base import JsonRequest, LlmResult, LlmUsage, ProviderError

Script = Callable[[JsonRequest], dict[str, Any]]
UsageScript = Callable[[JsonRequest, LlmUsage], LlmUsage]
"""Given the request and the usage counted by the estimate, the usage the "provider" bills: to script cache writes and reads,
thinking tokens - what a real API reports and the estimate cannot know."""


class FakeProvider:
    def __init__(self, script: Script, *, name: str = "fake", fail: str | None = None,
                 output_tokens: int | None = None, usage: UsageScript | None = None,
                 limit: str | None = None) -> None:
        self.name = name
        self._script = script
        self._fail = fail
        self._output_tokens = output_tokens
        self._usage = usage
        self._limit = limit
        self.requests: list[JsonRequest] = []

    def complete_json(self, model: str, request: JsonRequest) -> LlmResult:
        self.requests.append(request)
        if self._limit is not None:  # a spent workspace limit ("workspace_limit") or tier cap ("tier_cap")
            raise ProviderError("limit_reached", "scripted spend limit", status=400 if self._limit == "workspace_limit" else 429,
                                limit_kind=self._limit, request_id="req_fake")
        if self._fail is not None:
            raise ProviderError(self._fail, f"scripted failure: {self._fail}")  # type: ignore[arg-type]
        data = self._script(request)
        text_in = request.system + request.user_text + json.dumps(request.schema)
        out_tokens = self._output_tokens if self._output_tokens is not None else approx_tokens(json.dumps(data))
        counted = LlmUsage(input_tokens=approx_tokens(text_in), output_tokens=out_tokens)
        return LlmResult(data, counted if self._usage is None else self._usage(request, counted),
                         self.name, model, latency_ms=0)
