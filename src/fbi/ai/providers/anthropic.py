"""Claude through the Messages API: the JSON answer is a forced call of one tool whose input schema
is the output schema (the same technique ``fbi.analyst`` uses), so the answer arrives as an object."""

from __future__ import annotations

import time
from typing import Any

import httpx

from fbi.ai.providers.base import JsonRequest, LlmResult, LlmUsage, ProviderError, status_error

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        if not api_key:
            raise ProviderError("not_configured", "no Anthropic key")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._transport = transport

    def complete_json(self, model: str, request: JsonRequest) -> LlmResult:
        body: dict[str, Any] = {
            "model": model, "max_tokens": request.max_tokens, "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "tools": [{"name": request.schema_name, "description": "Submit the answer. Call exactly once.",
                       "input_schema": request.schema}],
            "tool_choice": {"type": "tool", "name": request.schema_name},
        }
        started = time.monotonic()
        try:
            with httpx.Client(base_url=self._base, timeout=request.timeout_s, transport=self._transport) as http:
                r = http.post("/v1/messages", json=body, headers={
                    "x-api-key": self._key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"})
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "the provider did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"the provider could not be reached ({type(exc).__name__})") from exc
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code != 200:
            raise status_error(r.status_code)
        out = r.json()
        uses = [c for c in out.get("content") or [] if c.get("type") == "tool_use"
                and c.get("name") == request.schema_name]
        if not uses or not isinstance(uses[0].get("input"), dict):
            raise ProviderError("invalid_output", "the model did not submit the answer")
        u = out.get("usage") or {}
        cached = int(u.get("cache_read_input_tokens") or 0)
        written = int(u.get("cache_creation_input_tokens") or 0)
        usage = LlmUsage(input_tokens=int(u.get("input_tokens") or 0) + cached + written,
                         output_tokens=int(u.get("output_tokens") or 0), cached_tokens=cached)
        return LlmResult(dict(uses[0]["input"]), usage, self.name, str(out.get("model") or model), latency,
                         request_id=r.headers.get("request-id"))
