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

ErrorCode = Literal["timeout", "unavailable", "rate_limited", "refused", "invalid_output", "not_configured",
                    "limit_reached"]
"""``limit_reached``: the workspace's spend limit or the account's tier cap is spent (HTTP 400 "workspace API usage
limits", or 429 ``enforced_spend_limit_reached``). Asking again cannot help until the limit is lifted or the month turns:
the layer treats it as EXHAUSTED (``fbi.ai.budget_v3``)."""


class ProviderError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, *, status: int | None = None,
                 usage: LlmUsage | None = None, limit_kind: str | None = None, request_id: str | None = None) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.status = status
        self.usage = usage
        """What the provider billed for an answer that came back but could not be used (``invalid_output``)."""
        self.limit_kind = limit_kind
        """For ``limit_reached``: ``workspace_limit`` (the workspace's own limit) or ``tier_cap`` (the account's)."""
        self.request_id = request_id


@dataclass(frozen=True, slots=True)
class LlmUsage:
    input_tokens: int = 0
    """All input tokens: the fresh ones, the ones read from the cache and the ones written to it."""
    output_tokens: int = 0
    """Everything the model wrote, its thinking included."""
    cached_tokens: int = 0
    """Input read from the cache."""
    searches: int = 0
    vision_items: int = 0
    cache_write_5m_tokens: int = 0
    """Input written to the 5-minute cache entry (billed 1.25 times the input price)."""
    cache_write_1h_tokens: int = 0
    """Input written to the 1-hour cache entry (billed 2 times the input price)."""
    thinking_tokens: int = 0
    """The part of ``output_tokens`` the model spent thinking (already counted in them; recorded to see it)."""

    @property
    def cache_write_tokens(self) -> int:
        return self.cache_write_5m_tokens + self.cache_write_1h_tokens

    @property
    def cache_ttl(self) -> str | None:
        """Which entry this call wrote: '5m', '1h', 'mixed', or None when it wrote none."""
        five, hour = self.cache_write_5m_tokens > 0, self.cache_write_1h_tokens > 0
        return "mixed" if five and hour else "5m" if five else "1h" if hour else None


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
    """A hard limit on everything the model writes - its thinking included, where it thinks."""
    timeout_s: float = 60.0
    effort: str | None = None
    """How much the model may think and write: low | medium | high (Anthropic ``output_config.effort``). Set from
    the tier by ``fbi.ai.usage.with_effort``; a provider without such a control ignores it."""
    shared: str = ""
    """The part of the user message that is the SAME for every call about this match (its block of data): it is sent
    first and, with ``cache``, cached for 5 minutes. What varies - the time, the price, the candidate - goes in ``user``,
    after it. A provider without a prompt cache reads ``user_text``: the two joined."""
    cache: bool = False
    """Mark the system block (1 hour) and ``shared`` (5 minutes) for the prompt cache (Anthropic ``cache_control``)."""
    native_schema: bool = False
    """Ask for the schema through structured outputs (Anthropic ``output_config.format``) instead of a forced tool call."""
    split: tuple[str, str] | None = None
    """The user message in its OTHER layout (plan section 28, cut point 2): ``(shared, variable)`` - the same facts as ``user``, with what
    is the same for every call about the match first and what moves with the clock (time, prices, new evidence) and the candidate last.
    The request is sent as ``user`` says until ``fbi.ai.usage.with_switches`` finds the ``cache_layout`` gate passed for the model; then
    ``shared`` and ``user`` are taken from here. A provider never reads this field."""
    pinned: bool = False
    """The request is exactly what an experiment asked for: ``fbi.ai.usage.with_switches`` leaves it alone, so a switch of production
    can neither add nor take away what is being measured (the cache, the schema route and the layout are set by whoever builds it)."""

    @property
    def user_text(self) -> str:
        return self.shared + self.user if self.shared else self.user


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
