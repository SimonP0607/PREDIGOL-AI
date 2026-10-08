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


class FakeProvider:
    def __init__(self, script: Script, *, name: str = "fake", fail: str | None = None,
                 output_tokens: int | None = None) -> None:
        self.name = name
        self._script = script
        self._fail = fail
        self._output_tokens = output_tokens
        self.requests: list[JsonRequest] = []

    def complete_json(self, model: str, request: JsonRequest) -> LlmResult:
        self.requests.append(request)
        if self._fail is not None:
            raise ProviderError(self._fail, f"scripted failure: {self._fail}")  # type: ignore[arg-type]
        data = self._script(request)
        text_in = request.system + request.user + json.dumps(request.schema)
        out_tokens = self._output_tokens if self._output_tokens is not None else approx_tokens(json.dumps(data))
        return LlmResult(data, LlmUsage(input_tokens=approx_tokens(text_in), output_tokens=out_tokens),
                         self.name, model, latency_ms=0)
