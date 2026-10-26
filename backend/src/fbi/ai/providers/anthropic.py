"""Claude through the Messages API: the JSON answer is a call of one tool whose input schema is the output schema
(the same technique ``fbi.analyst`` uses), so the answer arrives as an object - or, once its evidence has passed
(``fbi.ai.gates``), STRUCTURED OUTPUTS (``output_config.format``), where the answer is the JSON text itself.

What Claude 5.5 changed (seen with the first real calls, 8 Oct 2026):

* A forced tool choice is refused ("tool_choice: type "tool" and "any" are not supported for this model", HTTP 400).
  Such a model is asked with ``tool_choice: auto`` and the instruction to answer only through the tool.
* The model thinks before it answers (adaptive thinking, billed as output and counted in ``max_tokens``). How much is
  set with ``output_config.effort`` (``JsonRequest.effort``, from the tier); ``max_tokens`` must leave room for it.

Each adjustment is made once per model and process: the refused attempt costs nothing, and the model is remembered.
A rate limit (429) or an overload (503/529) bills nothing and usually passes in seconds: the request is made once
more after the ``retry-after`` the API sends (at most ``RETRY_MAX_S``), so a busy minute at the day's first pass
does not cost the pass; a second refusal is the error. A SPENT LIMIT is different (Plan Maestro IA, phase 0): a 400 saying the
workspace's usage limits are reached, or a 429 ``enforced_spend_limit_reached`` (no ``retry-after``), cannot pass in seconds -
it is ``limit_reached`` at once, never asked again, and the budget treats the workspace as EXHAUSTED.
An answer without the tool call is ``invalid_output`` (the review then abstains); a cut answer keeps its
``stop_reason`` in ``LlmResult.extra`` so the caller can say why it did not validate.

PROMPT CACHE (``JsonRequest.cache``, plan section 28): the system block is marked for one hour and ``JsonRequest.shared``
- the part of the user message that is the same for every call about a match - for five minutes; what varies goes last
and is never cached. A write is billed 1.25 (five minutes) or 2 (one hour) times the input, a read 0.1 or 0.05 times
(``fbi.ai.pricing``); the usage the API returns says how many tokens of each were written and read, and the ledger
records them. A model that refuses ``cache_control`` (or its ``ttl``) is asked again without and remembered.

MESSAGE BATCHES (``AnthropicBatches``, plan section 29): the same request body, sent later at half the price. A batch is
created with a ``custom_id`` per request (the task's idempotency key), polled, and its results read when it has ended.
The tool choice is ``auto`` in a batch (a failure cannot be discovered request by request): the answer is asked for
through the tool by the instruction, or through ``output_config.format`` when the native schema is on."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from fbi.ai.providers.base import (
    JsonRequest,
    LlmResult,
    LlmUsage,
    ProviderError,
    parse_json_object,
    status_error,
)

ANTHROPIC_VERSION = "2023-06-01"

AUTO_ONLY: set[str] = set()
"""Models that refused a forced tool choice in this process."""
NO_EFFORT: set[str] = set()
"""Models that refused ``output_config.effort`` in this process (older models)."""
NO_NATIVE: set[str] = set()
"""Models that refused ``output_config.format`` (structured outputs) in this process."""
NO_CACHE: set[str] = set()
"""Models that refused ``cache_control`` in this process."""
NO_TTL: set[str] = set()
"""Models that refused the one-hour ``ttl`` of ``cache_control`` in this process: they are asked with the 5-minute entry."""

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


def _error_message(r: httpx.Response) -> tuple[str, str]:
    """The API error's message (lower case) and its ``error_code``, only to CLASSIFY it: neither is ever logged or raised
    (a body can echo the prompt)."""
    try:
        body = r.json()
    except ValueError:
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    err = body.get("error")
    err = err if isinstance(err, dict) else {}
    return str(err.get("message") or "").lower(), str(err.get("error_code") or body.get("error_code") or "")


def limit_kind(r: httpx.Response) -> Literal["workspace_limit", "tier_cap"] | None:
    """Whether the response says a SPEND LIMIT is spent: HTTP 400 "You have reached your specified workspace API usage
    limits" (the workspace's own limit), or HTTP 429 with ``enforced_spend_limit_reached`` (the account's tier cap; it sends
    no ``retry-after``). Anything else is an ordinary rate limit or refusal."""
    if r.status_code not in (400, 429):
        return None
    message, code = _error_message(r)
    if r.status_code == 429 and (code == "enforced_spend_limit_reached" or "spend limit" in message):
        return "tier_cap"
    if r.status_code == 400 and "workspace" in message and ("usage limit" in message or "spend limit" in message):
        return "workspace_limit"
    return None


def _limit_error(r: httpx.Response, kind: str) -> ProviderError:
    return ProviderError("limit_reached", f"the provider says a spend limit is reached (HTTP {r.status_code}, {kind})",
                         status=r.status_code, limit_kind=kind, request_id=r.headers.get("request-id"))


def _unsupported(r: httpx.Response) -> str | None:
    """Which request option a 400 refuses, if it is one we can drop: 'tool_choice', 'format', 'cache', 'ttl' or 'effort'. Only
    the error's message is read, to classify it; it is never logged or raised (a body can echo the prompt)."""
    if r.status_code != 400:
        return None
    message, _code = _error_message(r)
    if "tool_choice" in message and "not supported" in message:
        return "tool_choice"
    if "output_config.format" in message or "json_schema" in message or ("format" in message and "output_config" in message):
        return "format"
    if "ttl" in message:
        return "ttl"
    if "cache_control" in message:
        return "cache"
    if "output_config" in message or "effort" in message:
        return "effort"
    return None


def _cache_control(ttl: Literal["5m", "1h"]) -> dict[str, str]:
    return {"type": "ephemeral", "ttl": "1h"} if ttl == "1h" else {"type": "ephemeral"}


def build_body(model: str, request: JsonRequest, *, forced: bool, effort: str | None, native: bool, cache: bool = False,
               long_ttl: bool = True) -> dict[str, Any]:
    """The Messages API body of a request. The text sent is the request's: ``cache`` only MARKS blocks (so a cached call and
    an uncached one read the same prompt), ``native`` moves the schema from a tool to ``output_config.format``."""
    system = request.system if (forced or native) else request.system + ANSWER_THROUGH_TOOL.format(name=request.schema_name)
    body: dict[str, Any] = {"model": model, "max_tokens": request.max_tokens}
    body["system"] = ([{"type": "text", "text": system, "cache_control": _cache_control("1h" if long_ttl else "5m")}]
                      if cache else system)
    if request.shared:
        shared: dict[str, Any] = {"type": "text", "text": request.shared}
        if cache:
            shared["cache_control"] = _cache_control("5m")
        body["messages"] = [{"role": "user", "content": [shared, {"type": "text", "text": request.user}]}]
    else:
        body["messages"] = [{"role": "user", "content": request.user}]
    config: dict[str, Any] = {}
    if effort is not None:
        config["effort"] = effort
    if native:
        config["format"] = {"type": "json_schema", "schema": request.schema}
    else:
        body["tools"] = [{"name": request.schema_name, "description": "Submit the answer. Call exactly once.",
                          "input_schema": request.schema}]
        body["tool_choice"] = {"type": "tool", "name": request.schema_name} if forced else {"type": "auto"}
    if config:
        body["output_config"] = config
    return body


def read_usage(u: dict[str, Any], *, long_ttl_asked: bool) -> LlmUsage:
    """The usage the API returns. ``input_tokens`` is the fresh input; the cache has its own counters (read, and written per
    TTL in ``cache_creation``). A total of written tokens without the per-TTL breakdown is billed as the dearer entry the
    request asked for, so a gap can only over-count the cost, never hide it."""
    cached = int(u.get("cache_read_input_tokens") or 0)
    created = u.get("cache_creation")
    created = created if isinstance(created, dict) else {}
    w5 = int(created.get("ephemeral_5m_input_tokens") or 0)
    w1 = int(created.get("ephemeral_1h_input_tokens") or 0)
    rest = int(u.get("cache_creation_input_tokens") or 0) - (w5 + w1)
    if rest > 0:
        if long_ttl_asked:
            w1 += rest
        else:
            w5 += rest
    details = u.get("output_tokens_details")
    thinking = int((details.get("thinking_tokens") if isinstance(details, dict) else 0) or 0)
    return LlmUsage(input_tokens=int(u.get("input_tokens") or 0) + cached + w5 + w1,
                    output_tokens=int(u.get("output_tokens") or 0), cached_tokens=cached,
                    cache_write_5m_tokens=w5, cache_write_1h_tokens=w1, thinking_tokens=thinking)


def read_message(out: dict[str, Any], request: JsonRequest, model: str, *, native: bool, latency_ms: int,
                 request_id: str | None, long_ttl_asked: bool) -> LlmResult:
    """The result of a Messages API response (a live one, or the message of a batch result): the answer object and the usage,
    or a ``ProviderError`` that still carries what was billed."""
    u = out.get("usage")
    usage = read_usage(u if isinstance(u, dict) else {}, long_ttl_asked=long_ttl_asked)
    if native:
        if out.get("stop_reason") == "refusal":
            raise ProviderError("refused", "the model refused to answer", usage=usage)
        text = "".join(str(c.get("text") or "") for c in out.get("content") or [] if c.get("type") == "text")
        if not text.strip():
            raise ProviderError("invalid_output", "the model did not submit the answer", usage=usage)
        try:
            data = parse_json_object(text)
        except ProviderError as exc:
            raise ProviderError("invalid_output", str(exc), usage=usage) from None
    else:
        uses = [c for c in out.get("content") or [] if c.get("type") == "tool_use"
                and c.get("name") == request.schema_name]
        if not uses or not isinstance(uses[0].get("input"), dict):
            raise ProviderError("invalid_output", "the model did not submit the answer", usage=usage)
        data = dict(uses[0]["input"])
    extra: dict[str, Any] = {"stop_reason": out.get("stop_reason"), "thinking_tokens": usage.thinking_tokens}
    if request.shared:  # said only when it is so: an answer to the usual layout carries what it always carried
        extra["layout"] = "shared"
    return LlmResult(data, usage, "anthropic", str(out.get("model") or model), latency_ms, request_id=request_id, extra=extra)


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
        for _ in range(7):
            forced = model not in AUTO_ONLY
            effort = None if model in NO_EFFORT else request.effort
            native = request.native_schema and model not in NO_NATIVE
            cache = request.cache and model not in NO_CACHE
            long_ttl = model not in NO_TTL
            try:
                return self._complete(model, request, forced=forced, effort=effort, native=native, cache=cache,
                                      long_ttl=long_ttl)
            except _RetryError as exc:
                if retried:
                    raise status_error(exc.status) from None
                retried = True
                _sleep(exc.wait)
            except _UnsupportedError as exc:
                if exc.what == "tool_choice" and forced and not native:
                    AUTO_ONLY.add(model)
                elif exc.what == "effort" and effort is not None:
                    NO_EFFORT.add(model)
                elif exc.what == "format" and native:
                    NO_NATIVE.add(model)
                elif exc.what == "ttl" and cache and long_ttl:
                    NO_TTL.add(model)
                elif exc.what == "cache" and cache:
                    NO_CACHE.add(model)
                else:
                    raise status_error(400) from None
        raise status_error(400)

    def _complete(self, model: str, request: JsonRequest, *, forced: bool, effort: str | None, native: bool,
                  cache: bool, long_ttl: bool) -> LlmResult:
        body = build_body(model, request, forced=forced, effort=effort, native=native, cache=cache, long_ttl=long_ttl)
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
        if (kind := limit_kind(r)) is not None:  # before the retry: a spent limit does not pass in seconds
            raise _limit_error(r, kind)
        if r.status_code in RETRYABLE:
            raise _RetryError(r.status_code, _retry_after(r))
        if r.status_code != 200:
            what = _unsupported(r)
            if what is not None:
                raise _UnsupportedError(what)
            raise status_error(r.status_code)
        return read_message(r.json(), request, model, native=native, latency_ms=latency,
                            request_id=r.headers.get("request-id"), long_ttl_asked=cache and long_ttl)


# ── Message Batches ──────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class BatchResult:
    """One line of a batch's results."""

    custom_id: str
    kind: Literal["succeeded", "errored", "canceled", "expired"]
    message: dict[str, Any] | None = None
    """For ``succeeded``: the Messages API response."""
    error_type: str | None = None
    """For ``errored``: the error's type (a code, never its message)."""


class AnthropicBatches:
    """The Message Batches API. A batch holds up to 100,000 requests or 256 MB, ends in at most 24 hours (most in under one) and
    its results stay 29 days. It belongs to the workspace of the key that created it."""

    def __init__(self, api_key: str, base_url: str, *, transport: httpx.BaseTransport | None = None,
                 timeout_s: float = 60.0) -> None:
        if not api_key:
            raise ProviderError("not_configured", "no Anthropic key")
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout_s

    @staticmethod
    def item(custom_id: str, model: str, request: JsonRequest) -> dict[str, Any]:
        """One request of a batch: the body of a live call, with ``tool_choice: auto`` (see the module's note)."""
        effort = None if model in NO_EFFORT else request.effort
        native = request.native_schema and model not in NO_NATIVE
        cache = request.cache and model not in NO_CACHE
        return {"custom_id": custom_id,
                "params": build_body(model, request, forced=False, effort=effort, native=native, cache=cache,
                                     long_ttl=model not in NO_TTL)}

    def _send(self, method: str, path: str, payload: dict[str, Any] | None = None) -> httpx.Response:
        try:
            with httpx.Client(base_url=self._base, timeout=self._timeout, transport=self._transport) as http:
                r = http.request(method, path, json=payload, headers={
                    "x-api-key": self._key, "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"})
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "the provider did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"the provider could not be reached ({type(exc).__name__})") from exc
        if (kind := limit_kind(r)) is not None:
            raise _limit_error(r, kind)
        if r.status_code != 200:
            raise status_error(r.status_code)
        return r

    def create(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Create a batch. Returns the provider's batch object (``id``, ``processing_status``, ``request_counts``,
        ``created_at``, ``expires_at``...)."""
        out = self._send("POST", "/v1/messages/batches", {"requests": items}).json()
        if not isinstance(out, dict) or not out.get("id"):
            raise ProviderError("invalid_output", "the provider's answer to a batch has no id")
        return out

    def get(self, batch_ref: str) -> dict[str, Any]:
        out = self._send("GET", f"/v1/messages/batches/{batch_ref}").json()
        if not isinstance(out, dict):
            raise ProviderError("invalid_output", "the provider's batch is not an object")
        return out

    def cancel(self, batch_ref: str) -> dict[str, Any]:
        out = self._send("POST", f"/v1/messages/batches/{batch_ref}/cancel").json()
        return out if isinstance(out, dict) else {}

    def results(self, batch_ref: str) -> list[BatchResult]:
        """The results of an ENDED batch, one per request (in no order: match them by ``custom_id``)."""
        text = self._send("GET", f"/v1/messages/batches/{batch_ref}/results").text
        out: list[BatchResult] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                custom_id = str(row["custom_id"])
                result = row["result"]
                kind = str(result["type"])
            except (ValueError, KeyError, TypeError):
                raise ProviderError("invalid_output", "a line of the batch's results is not readable") from None
            if kind == "succeeded" and isinstance(result.get("message"), dict):
                out.append(BatchResult(custom_id, "succeeded", message=result["message"]))
            elif kind == "errored":
                err = (result.get("error") or {}).get("error") or result.get("error") or {}
                out.append(BatchResult(custom_id, "errored", error_type=str(err.get("type") or "error")[:60]
                                       if isinstance(err, dict) else "error"))
            elif kind in ("canceled", "expired"):
                out.append(BatchResult(custom_id, "canceled" if kind == "canceled" else "expired"))
            else:
                raise ProviderError("invalid_output", "a result of the batch has a type this code does not know")
        return out
