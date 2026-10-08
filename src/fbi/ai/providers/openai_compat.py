"""Every provider that speaks the OpenAI Chat Completions dialect: OpenAI itself, Google Gemini (its
OpenAI-compatible endpoint), Mistral, DeepSeek, Together, Groq and DeepInfra.

JSON is forced with ``response_format``: a strict JSON schema where the provider supports one, JSON
mode (``json_object``) where it only has that - then the schema travels in the system message and the
answer is validated here like any other. Usage comes from ``usage.prompt_tokens`` /
``completion_tokens`` / ``prompt_tokens_details.cached_tokens``.

Portability: the schema sent as ``json_schema`` drops the string-length keywords some providers' strict
mode rejects (the answer is validated again here, with them, by Pydantic); and a provider that refuses
the schema itself (HTTP 400) is asked once more in JSON mode, the schema in the system message.

Untested against the live services (no keys on this host): the request shapes follow each provider's
published API reference and are pinned by contract tests (``tests/unit/test_ai_providers.py``).
"""

from __future__ import annotations

import json
import time
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

JSON_SCHEMA = frozenset({"openai", "gemini", "mistral", "together", "groq"})
"""Providers whose chat completions accept ``response_format: {type: json_schema}``."""
COMPLETION_TOKENS_FIELD = {"openai": "max_completion_tokens"}
"""OpenAI's reasoning models take ``max_completion_tokens``; the others ``max_tokens``."""
NOT_PORTABLE = frozenset({"minLength", "maxLength"})
Mode = Literal["json_schema", "json_object"]


def portable(schema: Any) -> Any:
    """The schema without the keywords a strict structured-output mode may refuse. Only schema nodes (a dict
    whose ``type`` is a string or a list) lose them: a property that happens to be NAMED like a keyword stays."""
    if isinstance(schema, dict):
        node = isinstance(schema.get("type"), str | list)
        return {k: portable(v) for k, v in schema.items() if not (node and k in NOT_PORTABLE)}
    if isinstance(schema, list):
        return [portable(x) for x in schema]
    return schema


class OpenAICompatibleProvider:
    def __init__(self, name: str, api_key: str, base_url: str, *,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not api_key:
            raise ProviderError("not_configured", f"no {name} key")
        self.name = name
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._transport = transport

    def mode(self) -> Mode:
        return "json_schema" if self.name in JSON_SCHEMA else "json_object"

    def body(self, model: str, request: JsonRequest, mode: Mode | None = None) -> dict[str, Any]:
        system = request.system
        if (mode or self.mode()) == "json_schema":
            response_format: dict[str, Any] = {"type": "json_schema", "json_schema": {
                "name": request.schema_name, "schema": portable(request.schema), "strict": True}}
        else:
            response_format = {"type": "json_object"}
            system = (system + "\n\nAnswer with ONE JSON object that validates against this JSON schema, and "
                      "nothing else:\n" + json.dumps(request.schema, separators=(",", ":")))
        return {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": request.user}],
            "response_format": response_format,
            COMPLETION_TOKENS_FIELD.get(self.name, "max_tokens"): request.max_tokens,
        }

    def complete_json(self, model: str, request: JsonRequest) -> LlmResult:
        mode = self.mode()
        try:
            return self._complete(model, request, mode)
        except ProviderError as exc:
            if mode == "json_schema" and exc.code == "refused" and exc.status == 400:
                return self._complete(model, request, "json_object")
            raise

    def _complete(self, model: str, request: JsonRequest, mode: Mode) -> LlmResult:
        started = time.monotonic()
        try:
            with httpx.Client(base_url=self._base, timeout=request.timeout_s, transport=self._transport) as http:
                r = http.post("/chat/completions", json=self.body(model, request, mode),
                              headers={"authorization": f"Bearer {self._key}", "content-type": "application/json"})
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "the provider did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"the provider could not be reached ({type(exc).__name__})") from exc
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code != 200:
            raise status_error(r.status_code)
        out = r.json()
        choices = out.get("choices") or []
        if not choices:
            raise ProviderError("invalid_output", "the provider returned no answer")
        message = choices[0].get("message") or {}
        if message.get("refusal"):
            raise ProviderError("refused", "the model refused to answer")
        content = message.get("content")
        if isinstance(content, list):  # some providers return content parts
            content = "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("invalid_output", "the answer is empty")
        u = out.get("usage") or {}
        details = u.get("prompt_tokens_details") or {}
        usage = LlmUsage(input_tokens=int(u.get("prompt_tokens") or 0), output_tokens=int(u.get("completion_tokens") or 0),
                         cached_tokens=int(details.get("cached_tokens") or u.get("prompt_cache_hit_tokens") or 0))
        return LlmResult(parse_json_object(content), usage, self.name, str(out.get("model") or model), latency,
                         request_id=str(out.get("id")) if out.get("id") else None)
