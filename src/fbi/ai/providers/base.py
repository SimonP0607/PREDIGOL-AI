"""One interface for every language model: send a system and a user message, get back JSON that
validates against a schema, and exactly what it cost.

Providers differ in how they force JSON (Anthropic: a forced tool call; OpenAI-compatible APIs:
``response_format`` with a JSON schema, or JSON mode where only that exists) and in how they count
tokens. They do not differ in what the caller gets: ``LlmResult`` with the parsed object and the
usage, or a ``ProviderError`` with a stable code. The caller validates the object again with a
strict Pydantic model - a provider's promise of schema-valid output is not trusted.

Errors never carry the response body: it can echo the request, and a request can carry the key's
owner or the prompt. Status codes and our own codes only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ErrorCode = Literal["timeout", "unavailable", "rate_limited", "refused", "invalid_output", "not_configured"]


class ProviderError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.status = status


@dataclass(frozen=True, slots=True)
class LlmUsage:
    input_tokens: int = 0
    """All input tokens, cached ones included."""
    output_tokens: int = 0
    cached_tokens: int = 0
    searches: int = 0
    vision_items: int = 0


@dataclass(frozen=True)
class LlmResult:
    data: dict[str, Any]
    usage: LlmUsage
    provider: str
    model: str
    latency_ms: int
    request_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JsonRequest:
    system: str
    user: str
    schema: dict[str, Any]
    schema_name: str
    max_tokens: int = 1500
    timeout_s: float = 60.0


class LlmProvider(Protocol):
    name: str

    def complete_json(self, model: str, request: JsonRequest) -> LlmResult: ...


def parse_json_object(text: str) -> dict[str, Any]:
    """The JSON object in a model's text answer: the whole text, or the outermost {...} in it
    (some JSON modes wrap the object in a code fence)."""
    text = text.strip()
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("invalid_output", "the answer contains no JSON object") from None
        try:
            value = json.loads(text[start:end + 1])
        except ValueError as exc:
            raise ProviderError("invalid_output", "the answer's JSON does not parse") from exc
    if not isinstance(value, dict):
        raise ProviderError("invalid_output", "the answer is JSON but not an object")
    return value


def status_error(status: int) -> ProviderError:
    if status == 429:
        return ProviderError("rate_limited", "the provider is rate limiting (HTTP 429)", status=status)
    if status in (401, 403):
        return ProviderError("refused", f"the provider refused the credentials (HTTP {status})", status=status)
    if 400 <= status < 500:
        return ProviderError("refused", f"the provider refused the request (HTTP {status})", status=status)
    return ProviderError("unavailable", f"the provider failed (HTTP {status})", status=status)
