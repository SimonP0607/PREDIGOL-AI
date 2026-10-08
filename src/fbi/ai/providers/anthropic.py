"""Claude through the Messages API: the JSON answer is a call of one tool whose input schema is the output schema
(the same technique ``fbi.analyst`` uses), so the answer arrives as an object.

The call is forced (``tool_choice: tool``) where the model allows it. Claude 5.5 refuses a forced tool choice
("tool_choice: type "tool" and "any" are not supported for this model", HTTP 400 - seen on 8 Oct 2026 with the
first real calls): such a model is asked with ``tool_choice: auto`` and the instruction to answer only through the
tool, and is remembered, so the refused attempt (which costs nothing) is made once per process. An answer without
the tool call is still ``invalid_output``: the review then abstains, as for any failure."""

from __future__ import annotations

import time
from typing import Any

import httpx

from fbi.ai.providers.base import JsonRequest, LlmResult, LlmUsage, ProviderError, status_error

ANTHROPIC_VERSION = "2023-06-01"

AUTO_ONLY: set[str] = set()
"""Models that refused a forced tool choice in this process."""

ANSWER_THROUGH_TOOL = ("\n\nAnswer only by calling the tool `{name}` exactly once, with the complete answer as its "
                       "input. Write nothing outside that call.")


class _ForcedChoiceRefusedError(Exception):
    pass


def _forced_choice_refused(r: httpx.Response) -> bool:
    """A 400 that says the model does not take a forced tool choice. Only the error's type and message are read,
    to classify it; they are never logged or raised (a body can echo the prompt)."""
    if r.status_code != 400:
        return False
    try:
        err = (r.json() or {}).get("error") or {}
    except ValueError:
        return False
    message = str(err.get("message") or "")
    return "tool_choice" in message and "not supported" in message


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        if not api_key:
            raise ProviderError("not_configured", "no Anthropic key")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._transport = transport

    def complete_json(self, model: str, request: JsonRequest) -> LlmResult:
        if model not in AUTO_ONLY:
            try:
                return self._complete(model, request, forced=True)
            except _ForcedChoiceRefusedError:
                AUTO_ONLY.add(model)
        return self._complete(model, request, forced=False)

    def _complete(self, model: str, request: JsonRequest, *, forced: bool) -> LlmResult:
        body: dict[str, Any] = {
            "model": model, "max_tokens": request.max_tokens,
            "system": request.system if forced else request.system + ANSWER_THROUGH_TOOL.format(name=request.schema_name),
            "messages": [{"role": "user", "content": request.user}],
            "tools": [{"name": request.schema_name, "description": "Submit the answer. Call exactly once.",
                       "input_schema": request.schema}],
            "tool_choice": {"type": "tool", "name": request.schema_name} if forced else {"type": "auto"},
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
            if forced and _forced_choice_refused(r):
                raise _ForcedChoiceRefusedError
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
