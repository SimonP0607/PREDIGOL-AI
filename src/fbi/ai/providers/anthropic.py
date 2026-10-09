"""Claude through the Messages API: the JSON answer is a call of one tool whose input schema is the output schema
(the same technique ``fbi.analyst`` uses), so the answer arrives as an object.

What Claude 5.5 changed (seen with the first real calls, 8 Oct 2026):

* A forced tool choice is refused ("tool_choice: type "tool" and "any" are not supported for this model", HTTP 400).
  Such a model is asked with ``tool_choice: auto`` and the instruction to answer only through the tool.
* The model thinks before it answers (adaptive thinking, billed as output and counted in ``max_tokens``). How much is
  set with ``output_config.effort`` (``JsonRequest.effort``, from the tier); ``max_tokens`` must leave room for it.

Each adjustment is made once per model and process: the refused attempt costs nothing, and the model is remembered.
A rate limit (429) or an overload (503/529) bills nothing and usually passes in seconds: the request is made once
more after the ``retry-after`` the API sends (at most ``RETRY_MAX_S``), so a busy minute at the day's first pass
does not cost the pass; a second refusal is the error.
An answer without the tool call is ``invalid_output`` (the review then abstains); a cut answer keeps its
``stop_reason`` in ``LlmResult.extra`` so the caller can say why it did not validate."""

from __future__ import annotations

import time
from typing import Any

import httpx

from fbi.ai.providers.base import JsonRequest, LlmResult, LlmUsage, ProviderError, status_error

ANTHROPIC_VERSION = "2023-06-01"

AUTO_ONLY: set[str] = set()
"""Models that refused a forced tool choice in this process."""
NO_EFFORT: set[str] = set()
"""Models that refused ``output_config.effort`` in this process (older models)."""

RETRYABLE = {429: 5.0, 503: 3.0, 529: 3.0}
"""Statuses asked once more, with the wait used when the API sends no ``retry-after`` (seconds)."""
RETRY_MAX_S = 20.0
_sleep = time.sleep  # replaced in tests

ANSWER_THROUGH_TOOL = ("\n\nAnswer only by calling the tool `{name}` exactly once, with the complete answer as its "
                       "input. Write nothing outside that call.")


class _RetryError(Exception):
    def __init__(self, status: int, wait: float) -> None:
        super().__init__(status)
        self.status = status
        self.wait = wait


def _retry_after(r: httpx.Response) -> float:
    try:
        wait = float(r.headers.get("retry-after") or RETRYABLE[r.status_code])
    except ValueError:
        wait = RETRYABLE[r.status_code]
    return max(0.0, min(RETRY_MAX_S, wait))


class _UnsupportedError(Exception):
    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


def _unsupported(r: httpx.Response) -> str | None:
    """Which request option a 400 refuses, if it is one we can drop: 'tool_choice' or 'effort'. Only the error's
    message is read, to classify it; it is never logged or raised (a body can echo the prompt)."""
    if r.status_code != 400:
        return None
    try:
        err = (r.json() or {}).get("error") or {}
    except ValueError:
        return None
    message = str(err.get("message") or "")
    if "tool_choice" in message and "not supported" in message:
        return "tool_choice"
    if "output_config" in message or "effort" in message:
        return "effort"
    return None


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, base_url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        if not api_key:
            raise ProviderError("not_configured", "no Anthropic key")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._transport = transport

    def complete_json(self, model: str, request: JsonRequest) -> LlmResult:
        retried = False
        for _ in range(4):
            forced = model not in AUTO_ONLY
            effort = None if model in NO_EFFORT else request.effort
            try:
                return self._complete(model, request, forced=forced, effort=effort)
            except _RetryError as exc:
                if retried:
                    raise status_error(exc.status) from None
                retried = True
                _sleep(exc.wait)
            except _UnsupportedError as exc:
                if exc.what == "tool_choice" and forced:
                    AUTO_ONLY.add(model)
                elif exc.what == "effort" and effort is not None:
                    NO_EFFORT.add(model)
                else:
                    raise status_error(400) from None
        raise status_error(400)

    def _complete(self, model: str, request: JsonRequest, *, forced: bool, effort: str | None) -> LlmResult:
        body: dict[str, Any] = {
            "model": model, "max_tokens": request.max_tokens,
            "system": request.system if forced else request.system + ANSWER_THROUGH_TOOL.format(name=request.schema_name),
            "messages": [{"role": "user", "content": request.user}],
            "tools": [{"name": request.schema_name, "description": "Submit the answer. Call exactly once.",
                       "input_schema": request.schema}],
            "tool_choice": {"type": "tool", "name": request.schema_name} if forced else {"type": "auto"},
        }
        if effort is not None:
            body["output_config"] = {"effort": effort}
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
        if r.status_code in RETRYABLE:
            raise _RetryError(r.status_code, _retry_after(r))
        if r.status_code != 200:
            what = _unsupported(r)
            if what is not None:
                raise _UnsupportedError(what)
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
        thinking = int(((u.get("output_tokens_details") or {}).get("thinking_tokens")) or 0)
        return LlmResult(dict(uses[0]["input"]), usage, self.name, str(out.get("model") or model), latency,
                         request_id=r.headers.get("request-id"),
                         extra={"stop_reason": out.get("stop_reason"), "thinking_tokens": thinking})
