"""Plan Maestro IA, Phase 0, at the provider: the prompt cache's marks and what a write and a read cost, structured outputs,
a spent limit that is never asked again, and the Message Batches API - all against recorded shapes of the API (no network,
no key). The earlier shapes (a forced tool call, effort, 429 retried once) are pinned by ``test_ai_providers.py``."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from typing import Any

import httpx
import pytest

from fbi.ai.pricing import token_cost
from fbi.ai.providers import AnthropicProvider, ProviderError
from fbi.ai.providers import anthropic as anth
from fbi.ai.providers.anthropic import (
    AnthropicBatches,
    build_body,
    limit_kind,
    read_message,
    read_usage,
)
from fbi.ai.providers.base import JsonRequest

SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["decision"],
    "properties": {"decision": {"type": "string", "enum": ["APPROVE", "REJECT"]}},
}
REQ = JsonRequest(system="You review.", user='{"candidate": 1}', schema=SCHEMA, schema_name="submit_review",
                  max_tokens=900, timeout_s=5)


def answer(decision: str = "APPROVE", **usage: Any) -> dict[str, Any]:
    return {"model": "claude-sonnet-5-5", "stop_reason": "tool_use",
            "content": [{"type": "tool_use", "name": "submit_review", "input": {"decision": decision}}],
            "usage": usage or {"input_tokens": 10, "output_tokens": 5}}


def native_answer(text: str, **usage: Any) -> dict[str, Any]:
    return {"model": "claude-sonnet-5-5", "stop_reason": "end_turn",
            "content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": text}],
            "usage": usage or {"input_tokens": 10, "output_tokens": 5}}


def sequence(replies: list[httpx.Response], seen: list[httpx.Request]) -> httpx.MockTransport:
    it = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(it)

    return httpx.MockTransport(handler)


# ── the prompt cache ─────────────────────────────────────────────────────────

def test_the_cache_only_marks_blocks_the_prompt_is_the_same_text() -> None:
    plain = build_body("claude-sonnet-5-5", REQ, forced=True, effort=None, native=False)
    shared = replace(REQ, shared='{"match": "the common block"}', user='{"candidate": 1, "now": "10:00"}', cache=True)
    cached = build_body("claude-sonnet-5-5", shared, forced=True, effort=None, native=False, cache=True)
    # one hour on the system block, five minutes on the match block, nothing on what varies
    assert cached["system"] == [{"type": "text", "text": REQ.system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    first, last = cached["messages"][0]["content"]
    assert first == {"type": "text", "text": '{"match": "the common block"}', "cache_control": {"type": "ephemeral"}}
    assert last == {"type": "text", "text": '{"candidate": 1, "now": "10:00"}'} and "cache_control" not in last
    # the tools come before the system in the cache's hierarchy, so they are part of what is cached
    assert cached["tools"] == plain["tools"] and cached["tool_choice"] == plain["tool_choice"]
    # a call without the cache or a match block is byte for byte what it always was
    assert plain["system"] == REQ.system and plain["messages"] == [{"role": "user", "content": REQ.user}]
    # a model that refused the one-hour entry is asked for five minutes
    short = build_body("m", shared, forced=True, effort=None, native=False, cache=True, long_ttl=False)
    assert short["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_the_cache_is_asked_only_when_the_request_asks_and_a_refusing_model_is_remembered() -> None:
    seen: list[httpx.Request] = []
    refused = httpx.Response(400, json={"error": {"type": "invalid_request_error",
                                                  "message": "system.0.cache_control: Extra inputs are not permitted"}})
    p = AnthropicProvider("k", "https://api.example",
                          transport=sequence([refused, httpx.Response(200, json=answer()),
                                              httpx.Response(200, json=answer())], seen))
    out = p.complete_json("claude-test-no-cache", replace(REQ, cache=True))
    first, second = (json.loads(r.content) for r in seen)
    assert isinstance(first["system"], list) and second["system"] == REQ.system, "asked again without the cache"
    assert out.data == {"decision": "APPROVE"}
    p.complete_json("claude-test-no-cache", replace(REQ, cache=True))
    assert len(seen) == 3 and json.loads(seen[2].content)["system"] == REQ.system, "remembered: no refused attempt first"


def test_a_model_that_refuses_the_one_hour_entry_is_asked_for_five_minutes() -> None:
    seen: list[httpx.Request] = []
    refused = httpx.Response(400, json={"error": {"type": "invalid_request_error",
                                                  "message": "system.0.cache_control.ttl: Extra inputs are not permitted"}})
    p = AnthropicProvider("k", "https://api.example",
                          transport=sequence([refused, httpx.Response(200, json=answer())], seen))
    p.complete_json("claude-test-no-ttl", replace(REQ, cache=True))
    first, second = (json.loads(r.content) for r in seen)
    assert first["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert second["system"][0]["cache_control"] == {"type": "ephemeral"}, "the cache stays, only its time shrinks"


def test_a_write_is_read_per_ttl_priced_dearer_and_a_read_cheaper() -> None:
    usage = read_usage({"input_tokens": 2_000, "output_tokens": 900, "cache_read_input_tokens": 6_000,
                        "cache_creation_input_tokens": 2_000,
                        "cache_creation": {"ephemeral_5m_input_tokens": 1_500, "ephemeral_1h_input_tokens": 500},
                        "output_tokens_details": {"thinking_tokens": 400}}, long_ttl_asked=True)
    assert (usage.input_tokens, usage.cached_tokens, usage.cache_write_5m_tokens, usage.cache_write_1h_tokens) \
        == (10_000, 6_000, 1_500, 500)
    assert (usage.cache_write_tokens, usage.cache_ttl, usage.thinking_tokens, usage.output_tokens) == (2_000, "mixed", 400, 900)
    cost = token_cost("anthropic", "claude-sonnet-5-5", input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                      cached_tokens=usage.cached_tokens, cache_write_5m_tokens=usage.cache_write_5m_tokens,
                      cache_write_1h_tokens=usage.cache_write_1h_tokens)
    # 2,000 fresh x 2 + 6,000 read x 0.10 + 1,500 written x 2 x 1.25 + 500 written x 2 x 2 + 900 out x 10 (USD per 1M)
    assert cost == Decimal("0.019350")
    # an API that gives only the total of the tokens written: billed as the dearer entry that was asked for
    only_total = {"input_tokens": 100, "cache_creation_input_tokens": 300}
    assert read_usage(only_total, long_ttl_asked=True).cache_write_1h_tokens == 300
    assert read_usage(only_total, long_ttl_asked=False).cache_write_5m_tokens == 300
    assert read_usage({}, long_ttl_asked=True).cache_ttl is None


def test_a_cached_call_reads_the_cache_counters_of_the_live_answer() -> None:
    seen: list[httpx.Request] = []
    reply = httpx.Response(200, json=answer(input_tokens=300, output_tokens=120, cache_read_input_tokens=9_000,
                                            cache_creation_input_tokens=1_000,
                                            cache_creation={"ephemeral_1h_input_tokens": 1_000}))
    p = AnthropicProvider("k", "https://api.example", transport=sequence([reply], seen))
    out = p.complete_json("claude-sonnet-5-5", replace(REQ, cache=True, shared="common"))
    assert out.usage.input_tokens == 10_300 and out.usage.cached_tokens == 9_000
    assert out.usage.cache_write_1h_tokens == 1_000 and out.usage.cache_write_5m_tokens == 0
    body = json.loads(seen[0].content)
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}


# ── structured outputs ───────────────────────────────────────────────────────

def test_structured_outputs_move_the_schema_out_of_the_tools_and_keep_the_effort() -> None:
    seen: list[httpx.Request] = []
    p = AnthropicProvider("k", "https://api.example",
                          transport=sequence([httpx.Response(200, json=native_answer('{"decision": "REJECT"}'))], seen))
    out = p.complete_json("claude-test-native", replace(REQ, native_schema=True, effort="medium"))
    body = json.loads(seen[0].content)
    assert "tools" not in body and "tool_choice" not in body, "the answer is the text, not a call"
    assert body["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert body["system"] == REQ.system, "the prompt is the same text: only the transport of the answer changed"
    assert out.data == {"decision": "REJECT"} and out.extra["stop_reason"] == "end_turn"


@pytest.mark.parametrize(("content", "stop", "code"), [
    ([{"type": "text", "text": '{"decision": "APPR'}], "max_tokens", "invalid_output"),
    ([{"type": "text", "text": "I would rather not."}], "end_turn", "invalid_output"),
    ([{"type": "thinking", "thinking": "..."}], "end_turn", "invalid_output"),
    ([{"type": "text", "text": ""}], "refusal", "refused"),
])
def test_a_native_answer_that_cannot_be_used_is_still_billed(content: list[dict[str, Any]], stop: str, code: str) -> None:
    out = {"model": "m", "stop_reason": stop, "content": content,
           "usage": {"input_tokens": 700, "output_tokens": 300, "cache_read_input_tokens": 100}}
    with pytest.raises(ProviderError) as e:
        read_message(out, replace(REQ, native_schema=True), "m", native=True, latency_ms=1, request_id=None,
                     long_ttl_asked=False)
    assert e.value.code == code and e.value.usage is not None
    assert (e.value.usage.input_tokens, e.value.usage.output_tokens, e.value.usage.cached_tokens) == (800, 300, 100)


def test_a_model_that_refuses_structured_outputs_is_asked_again_through_the_tool_and_remembered() -> None:
    seen: list[httpx.Request] = []
    refused = httpx.Response(400, json={"error": {"type": "invalid_request_error",
                                                  "message": "output_config.format: Extra inputs are not permitted"}})
    p = AnthropicProvider("k", "https://api.example",
                          transport=sequence([refused, httpx.Response(200, json=answer()),
                                              httpx.Response(200, json=answer())], seen))
    req = replace(REQ, native_schema=True)
    p.complete_json("claude-test-no-native", req)
    first, second = (json.loads(r.content) for r in seen)
    assert "tools" not in first and "output_config" in first
    assert second["tools"][0]["input_schema"] == SCHEMA and "format" not in second.get("output_config", {})
    p.complete_json("claude-test-no-native", req)
    assert len(seen) == 3 and "tools" in json.loads(seen[2].content)


# ── a spent limit ────────────────────────────────────────────────────────────

WORKSPACE_LIMIT = httpx.Response(400, headers={"request-id": "req_lim"}, json={"type": "error", "error": {
    "type": "invalid_request_error",
    "message": "You have reached your specified workspace API usage limits. You will regain access on 2026-11-01."}})
TIER_CAP = httpx.Response(429, json={"type": "error", "error": {
    "type": "rate_limit_error", "message": "SECRET-PROMPT-ECHO", "error_code": "enforced_spend_limit_reached"}})


@pytest.mark.parametrize(("reply", "kind"), [(WORKSPACE_LIMIT, "workspace_limit"), (TIER_CAP, "tier_cap")])
def test_a_spent_limit_is_limit_reached_at_once_never_asked_again_and_never_echoes_the_body(
        reply: httpx.Response, kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr(anth, "_sleep", waits.append)
    seen: list[httpx.Request] = []
    p = AnthropicProvider("k", "https://api.example", transport=sequence([reply, reply], seen))
    with pytest.raises(ProviderError) as e:
        p.complete_json("claude-test-limit", REQ)
    assert e.value.code == "limit_reached" and e.value.limit_kind == kind and e.value.status == reply.status_code
    assert len(seen) == 1 and waits == [], "a limit does not pass in seconds: no second attempt, no wait"
    assert "SECRET" not in str(e.value) and "regain" not in str(e.value)


def test_only_a_spent_limit_is_a_limit_an_ordinary_429_or_400_is_not() -> None:
    plain_429 = httpx.Response(429, json={"error": {"type": "rate_limit_error", "message": "Number of request tokens"}})
    other_400 = httpx.Response(400, json={"error": {"type": "invalid_request_error", "message": "max_tokens: too large"}})
    not_json = httpx.Response(429, content=b"<html>busy</html>")
    assert [limit_kind(r) for r in (plain_429, other_400, not_json, httpx.Response(200, json={}))] == [None] * 4
    assert limit_kind(WORKSPACE_LIMIT) == "workspace_limit" and limit_kind(TIER_CAP) == "tier_cap"
    # and an ordinary 429 is still asked once more
    seen: list[httpx.Request] = []
    p = AnthropicProvider("k", "https://api.example", transport=sequence([plain_429, plain_429], seen))
    anth._sleep = lambda _s: None
    try:
        with pytest.raises(ProviderError) as e:
            p.complete_json("claude-test-429", REQ)
    finally:
        import time
        anth._sleep = time.sleep
    assert e.value.code == "rate_limited" and len(seen) == 2


# ── Message Batches ──────────────────────────────────────────────────────────

def test_a_batch_item_is_the_body_of_a_live_call_with_the_tool_left_to_the_model() -> None:
    item = AnthropicBatches.item("a" * 64, "claude-sonnet-5-5", replace(REQ, cache=True, shared="common", effort="low"))
    assert item["custom_id"] == "a" * 64
    params = item["params"]
    assert params["model"] == "claude-sonnet-5-5" and params["max_tokens"] == 900
    assert params["tool_choice"] == {"type": "auto"} and params["output_config"] == {"effort": "low"}
    assert params["system"][0]["text"].startswith(REQ.system) and "exactly once" in params["system"][0]["text"]
    assert params["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    native = AnthropicBatches.item("b", "claude-sonnet-5-5", replace(REQ, native_schema=True))["params"]
    assert "tools" not in native and native["output_config"]["format"]["schema"] == SCHEMA, \
        "structured outputs inside a batch: the same request body"


def batch_reply(status: str = "in_progress", **counts: int) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "msgbatch_01", "type": "message_batch", "processing_status": status,
        "request_counts": {"processing": 2, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0} | counts,
        "created_at": "2026-10-26T00:05:00Z", "expires_at": "2026-10-27T00:05:00Z", "ended_at": None,
        "results_url": None})


def test_a_batch_is_created_polled_and_its_four_kinds_of_result_are_read() -> None:
    lines = [
        {"custom_id": "ok", "result": {"type": "succeeded", "message": answer("APPROVE")}},
        {"custom_id": "bad", "result": {"type": "errored", "error": {"type": "error", "error": {
            "type": "invalid_request_error", "message": "SECRET-PROMPT-ECHO"}}}},
        {"custom_id": "cut", "result": {"type": "canceled"}},
        {"custom_id": "late", "result": {"type": "expired"}},
    ]
    seen: list[httpx.Request] = []
    replies = [batch_reply(), batch_reply("ended", succeeded=1, errored=1, canceled=1, expired=1, processing=0),
               httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode() + b"\n")]
    api = AnthropicBatches("k", "https://api.example", transport=sequence(replies, seen))
    created = api.create([AnthropicBatches.item("ok", "claude-sonnet-5-5", REQ)])
    assert created["id"] == "msgbatch_01" and seen[0].method == "POST" and seen[0].url.path == "/v1/messages/batches"
    assert json.loads(seen[0].content)["requests"][0]["custom_id"] == "ok"
    assert seen[0].headers["x-api-key"] == "k" and seen[0].headers["anthropic-version"] == "2023-06-01"
    assert api.get("msgbatch_01")["processing_status"] == "ended" and seen[1].url.path == "/v1/messages/batches/msgbatch_01"
    results = {r.custom_id: r for r in api.results("msgbatch_01")}
    assert seen[2].url.path == "/v1/messages/batches/msgbatch_01/results"
    assert [results[k].kind for k in ("ok", "bad", "cut", "late")] == ["succeeded", "errored", "canceled", "expired"]
    assert results["bad"].error_type == "invalid_request_error", "the code, never the message (it can echo the prompt)"
    msg = results["ok"].message
    assert msg is not None
    live = read_message(msg, REQ, "claude-sonnet-5-5", native=False, latency_ms=0, request_id=None, long_ttl_asked=True)
    assert live.data == {"decision": "APPROVE"}, "a batch result reads like a live answer"


def test_a_batch_in_a_spent_workspace_is_limit_reached_and_a_bad_line_is_invalid() -> None:
    api = AnthropicBatches("k", "https://api.example", transport=sequence([WORKSPACE_LIMIT], []))
    with pytest.raises(ProviderError) as e:
        api.create([])
    assert e.value.code == "limit_reached" and e.value.limit_kind == "workspace_limit"
    for text in ("not json", json.dumps({"custom_id": "x"}), json.dumps({"custom_id": "x", "result": {"type": "weird"}})):
        broken = AnthropicBatches("k", "https://api.example", transport=sequence([httpx.Response(200, content=text.encode())], []))
        with pytest.raises(ProviderError) as e2:
            broken.results("msgbatch_01")
        assert e2.value.code == "invalid_output"
    with pytest.raises(ProviderError) as e3:
        AnthropicBatches("", "https://api.example")
    assert e3.value.code == "not_configured"
