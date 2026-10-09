"""Contract tests of the language-model providers, against recorded shapes of their APIs (no network, no key).

What is pinned: the request each provider receives (endpoint, headers, how JSON is forced, the token-limit
field), how the answer and the usage are read, and that every failure becomes a stable error code without the
response body (which can echo the prompt)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from fbi.ai.config import AiSettings, TierModel
from fbi.ai.providers import (
    AnthropicProvider,
    OpenAICompatibleProvider,
    ProviderError,
    provider_for,
)
from fbi.ai.providers.base import JsonRequest, parse_json_object
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.providers.openai_compat import portable

SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["decision", "claims"],
    "properties": {"decision": {"type": "string", "enum": ["APPROVE", "REJECT"]},
                   "claims": {"type": "array", "maxItems": 3, "items": {
                       "type": "object", "additionalProperties": False, "required": ["text", "type"],
                       "properties": {"text": {"type": "string", "maxLength": 240},
                                      "type": {"type": "string", "enum": ["DATA", "NEWS"]}}}}},
}
REQ = JsonRequest(system="You review.", user='{"candidate": 1}', schema=SCHEMA, schema_name="submit_review",
                  max_tokens=900, timeout_s=5)


def recorder(reply: httpx.Response | Exception, seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(reply, Exception):
            raise reply
        return reply
    return httpx.MockTransport(handler)


# ── Anthropic ────────────────────────────────────────────────────────────────

def test_anthropic_forces_one_tool_call_and_reads_the_cached_tokens() -> None:
    seen: list[httpx.Request] = []
    reply = httpx.Response(200, headers={"request-id": "req_1"}, json={
        "model": "claude-haiku-5-5", "content": [
            {"type": "text", "text": "thinking aloud"},
            {"type": "tool_use", "name": "submit_review", "input": {"decision": "APPROVE", "claims": []}}],
        "usage": {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 4000,
                  "cache_creation_input_tokens": 100}})
    p = AnthropicProvider("sk-ant-test", "https://api.example", transport=recorder(reply, seen))
    out = p.complete_json("claude-haiku-5-5", REQ)
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/messages" and seen[0].headers["x-api-key"] == "sk-ant-test"
    assert seen[0].headers["anthropic-version"] == "2023-06-01"
    assert body["tool_choice"] == {"type": "tool", "name": "submit_review"}
    assert body["tools"][0]["input_schema"] == SCHEMA and body["max_tokens"] == 900
    assert out.data == {"decision": "APPROVE", "claims": []} and out.request_id == "req_1"
    assert (out.usage.input_tokens, out.usage.cached_tokens, out.usage.output_tokens) == (5300, 4000, 300)


@pytest.mark.parametrize(("status", "code", "asked"), [(429, "rate_limited", 2), (401, "refused", 1),
                                                       (400, "refused", 1), (529, "unavailable", 2),
                                                       (500, "unavailable", 1)])
def test_anthropic_errors_become_stable_codes_without_the_body(status: int, code: str, asked: int,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai.providers import anthropic

    waits: list[float] = []
    monkeypatch.setattr(anthropic, "_sleep", waits.append)
    seen: list[httpx.Request] = []
    reply = httpx.Response(status, json={"error": {"message": "echo of the secret prompt"}})
    p = AnthropicProvider("k", "https://api.example", transport=recorder(reply, seen))
    with pytest.raises(ProviderError) as e:
        p.complete_json("m", REQ)
    assert e.value.code == code and e.value.status == status and "secret prompt" not in str(e.value)
    assert len(seen) == asked, "a rate limit or an overload is asked once more, nothing else is"
    assert len(waits) == asked - 1


def test_a_rate_limit_waits_what_the_api_says_once_and_the_answer_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai.providers import anthropic

    waits: list[float] = []
    monkeypatch.setattr(anthropic, "_sleep", waits.append)
    replies = iter([httpx.Response(429, headers={"retry-after": "7"}, json={}),
                    httpx.Response(200, json={"content": [{"type": "tool_use", "name": "submit_review",
                                                           "input": {"decision": "REJECT", "claims": []}}],
                                              "usage": {"input_tokens": 10, "output_tokens": 5}})])
    p = AnthropicProvider("k", "https://api.example", transport=httpx.MockTransport(lambda _r: next(replies)))
    assert p.complete_json("m", REQ).data["decision"] == "REJECT" and waits == [7.0]
    long_wait = iter([httpx.Response(529, headers={"retry-after": "600"}, json={}),
                      httpx.Response(529, json={})])
    p = AnthropicProvider("k", "https://api.example", transport=httpx.MockTransport(lambda _r: next(long_wait)))
    with pytest.raises(ProviderError) as e:
        p.complete_json("m", REQ)
    assert e.value.code == "unavailable" and waits[-1] == anthropic.RETRY_MAX_S, "never more than the cap"


def test_anthropic_timeout_outage_and_a_missing_answer() -> None:
    for exc, code in ((httpx.ReadTimeout("slow"), "timeout"), (httpx.ConnectError("down"), "unavailable")):
        p = AnthropicProvider("k", "https://api.example", transport=recorder(exc, []))
        with pytest.raises(ProviderError) as e:
            p.complete_json("m", REQ)
        assert e.value.code == code
    text_only = httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}], "usage": {}})
    p = AnthropicProvider("k", "https://api.example", transport=recorder(text_only, []))
    with pytest.raises(ProviderError) as e:
        p.complete_json("m", REQ)
    assert e.value.code == "invalid_output"
    with pytest.raises(ProviderError) as e:
        AnthropicProvider("", "https://api.example")
    assert e.value.code == "not_configured"


def test_a_claude_model_that_refuses_a_forced_tool_is_asked_with_auto_once_and_remembered() -> None:
    # Claude 5.5, 8 Oct 2026: HTTP 400 'tool_choice: type "tool" and "any" are not supported for this model'
    seen: list[httpx.Request] = []
    refused = httpx.Response(400, json={"type": "error", "error": {
        "type": "invalid_request_error",
        "message": 'tool_choice: type "tool" and "any" are not supported for this model.'}})
    answered = httpx.Response(200, json={"model": "claude-sonnet-5-5", "content": [
        {"type": "tool_use", "name": "submit_review", "input": {"decision": "REJECT", "claims": []}}],
        "usage": {"input_tokens": 2106, "output_tokens": 467}})
    replies = iter([refused, answered, answered])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(replies)

    p = AnthropicProvider("k", "https://api.example", transport=httpx.MockTransport(handler))
    out = p.complete_json("claude-test-auto-only", REQ)
    first, second = (json.loads(r.content) for r in seen)
    assert first["tool_choice"] == {"type": "tool", "name": "submit_review"} and first["system"] == REQ.system
    assert second["tool_choice"] == {"type": "auto"}
    assert second["system"].startswith(REQ.system) and "`submit_review` exactly once" in second["system"]
    assert out.data == {"decision": "REJECT", "claims": []} and out.usage.input_tokens == 2106
    p.complete_json("claude-test-auto-only", REQ)  # remembered: straight to auto, no refused attempt first
    assert len(seen) == 3 and json.loads(seen[2].content)["tool_choice"] == {"type": "auto"}


def test_effort_goes_as_output_config_and_a_model_without_it_is_asked_again_without() -> None:
    from dataclasses import replace

    seen: list[httpx.Request] = []
    answered = httpx.Response(200, json={"model": "claude-x", "stop_reason": "tool_use", "content": [
        {"type": "tool_use", "name": "submit_review", "input": {"decision": "APPROVE", "claims": []}}],
        "usage": {"input_tokens": 10, "output_tokens": 900, "output_tokens_details": {"thinking_tokens": 600}}})
    p = AnthropicProvider("k", "https://api.example", transport=recorder(answered, seen))
    out = p.complete_json("claude-test-effort", replace(REQ, effort="medium"))
    assert json.loads(seen[0].content)["output_config"] == {"effort": "medium"}
    assert out.extra == {"stop_reason": "tool_use", "thinking_tokens": 600}

    seen2: list[httpx.Request] = []
    refused = httpx.Response(400, json={"error": {"type": "invalid_request_error",
                                                  "message": "output_config.effort: Extra inputs are not permitted"}})
    replies = iter([refused, answered, answered])

    def handler(request: httpx.Request) -> httpx.Response:
        seen2.append(request)
        return next(replies)

    old = AnthropicProvider("k", "https://api.example", transport=httpx.MockTransport(handler))
    old.complete_json("claude-test-no-effort", replace(REQ, effort="low"))
    old.complete_json("claude-test-no-effort", replace(REQ, effort="low"))
    bodies = [json.loads(r.content) for r in seen2]
    assert "output_config" in bodies[0] and "output_config" not in bodies[1] and "output_config" not in bodies[2]
    assert len(bodies) == 3  # the refused attempt is made once, then the model is remembered


def test_the_tier_sets_the_effort_unless_the_request_already_has_one() -> None:
    from dataclasses import replace

    from fbi.ai.usage import with_effort

    assert with_effort(REQ, "bulk").effort == "low"
    assert with_effort(REQ, "analysis").effort == "medium" and with_effort(REQ, "final").effort == "medium"
    assert with_effort(replace(REQ, effort="high"), "bulk").effort == "high"
    assert with_effort(REQ, None) is REQ


# ── OpenAI-compatible ────────────────────────────────────────────────────────

def chat_reply(content: Any, **usage: Any) -> httpx.Response:
    return httpx.Response(200, json={"id": "chatcmpl-1", "model": "served-model",
                                     "choices": [{"message": {"role": "assistant", "content": content}}],
                                     "usage": usage or {"prompt_tokens": 1000, "completion_tokens": 200}})


def test_openai_uses_a_strict_json_schema_and_max_completion_tokens() -> None:
    seen: list[httpx.Request] = []
    p = OpenAICompatibleProvider("openai", "sk-oa", "https://api.example/v1",
                                 transport=recorder(chat_reply('{"decision":"REJECT","claims":[]}', prompt_tokens=900,
                                                               completion_tokens=120,
                                                               prompt_tokens_details={"cached_tokens": 512}), seen))
    out = p.complete_json("gpt-6-luna", REQ)
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/chat/completions" and seen[0].headers["authorization"] == "Bearer sk-oa"
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"]
    assert body["max_completion_tokens"] == 900 and "max_tokens" not in body
    sent = json.dumps(body["response_format"]["json_schema"]["schema"])
    assert "maxLength" not in sent and "maxItems" in sent, "string lengths are checked here, not by the provider"
    assert out.data["decision"] == "REJECT" and out.usage.cached_tokens == 512 and out.request_id == "chatcmpl-1"


def test_a_provider_that_refuses_the_schema_is_asked_again_in_json_mode() -> None:
    seen: list[httpx.Request] = []
    replies = [httpx.Response(400, json={"error": "schema not supported"}),
               chat_reply('```json\n{"decision": "APPROVE", "claims": []}\n```')]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return replies[len(seen) - 1]
    p = OpenAICompatibleProvider("gemini", "g-key", "https://api.example", transport=httpx.MockTransport(handler))
    out = p.complete_json("gemini-3.8-flash", REQ)
    first, second = (json.loads(r.content) for r in seen)
    assert first["response_format"]["type"] == "json_schema" and second["response_format"] == {"type": "json_object"}
    assert "submit" not in second["messages"][0]["content"] or "JSON schema" in second["messages"][0]["content"]
    assert second["max_tokens"] == 900 and out.data["decision"] == "APPROVE"


def test_json_mode_providers_carry_the_schema_in_the_system_message() -> None:
    seen: list[httpx.Request] = []
    p = OpenAICompatibleProvider("deepseek", "d", "https://api.example",
                                 transport=recorder(chat_reply('{"decision":"APPROVE","claims":[]}',
                                                               prompt_tokens=10, completion_tokens=5,
                                                               prompt_cache_hit_tokens=6), seen))
    out = p.complete_json("deepseek-flash", REQ)
    body = json.loads(seen[0].content)
    assert body["response_format"] == {"type": "json_object"}
    assert '"submit_review"' not in body["messages"][0]["content"]
    assert json.dumps(SCHEMA, separators=(",", ":")) in body["messages"][0]["content"]
    assert out.usage.cached_tokens == 6


@pytest.mark.parametrize("reply", [
    httpx.Response(200, json={"choices": []}),
    chat_reply(""),
    chat_reply("no json here"),
    chat_reply("[1, 2]"),
    httpx.Response(200, json={"choices": [{"message": {"refusal": "I can't help with that"}}]}),
])
def test_openai_compatible_bad_answers_are_refused_or_invalid(reply: httpx.Response) -> None:
    p = OpenAICompatibleProvider("mistral", "m", "https://api.example", transport=recorder(reply, []))
    with pytest.raises(ProviderError) as e:
        p.complete_json("mistral-small", REQ)
    assert e.value.code in ("invalid_output", "refused")


def test_content_parts_are_joined() -> None:
    p = OpenAICompatibleProvider("groq", "q", "https://api.example",
                                 transport=recorder(chat_reply([{"type": "text", "text": '{"decision":'},
                                                                {"type": "text", "text": '"APPROVE","claims":[]}'}]), []))
    assert p.complete_json("openai/gpt-oss-120b", REQ).data["decision"] == "APPROVE"


def test_portable_keeps_a_property_named_like_a_keyword() -> None:
    schema = {"type": "object", "properties": {"maxLength": {"type": "string", "maxLength": 3},
                                               "type": {"type": "string", "minLength": 1}}}
    assert portable(schema) == {"type": "object", "properties": {"maxLength": {"type": "string"},
                                                                 "type": {"type": "string"}}}


def test_parse_json_object_finds_the_object_inside_a_fence() -> None:
    assert parse_json_object('Here:\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ProviderError):
        parse_json_object('{"a": ')


# ── choosing the provider of a tier ──────────────────────────────────────────

def test_a_tier_gets_its_provider_only_with_a_key() -> None:
    s = AiSettings(tiers={"analysis": TierModel("anthropic", "claude-haiku-5-5"),
                          "bulk": TierModel("openai", "gpt-6-luna")},
                   keys={"anthropic": "k"}, base_urls={"anthropic": "https://a", "openai": "https://o"})
    chosen = provider_for(s, "analysis")
    assert chosen is not None and isinstance(chosen[0], AnthropicProvider) and chosen[1] == "claude-haiku-5-5"
    assert provider_for(s, "bulk") is None and provider_for(s, "final") is None


def test_the_fake_provider_counts_like_the_estimate_and_can_fail_on_purpose() -> None:
    fake = FakeProvider(lambda r: {"decision": "APPROVE", "claims": []})
    out = fake.complete_json("m", REQ)
    assert out.usage.input_tokens > 0 and out.usage.output_tokens > 0 and len(fake.requests) == 1
    with pytest.raises(ProviderError) as e:
        FakeProvider(lambda r: {}, fail="timeout").complete_json("m", REQ)
    assert e.value.code == "timeout"
