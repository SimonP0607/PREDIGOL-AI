"""The schema that structured outputs take (``fbi.ai.providers.structured``).

Why this file exists: the equivalence experiment of 26 Oct 2026 sent the review schema to ``output_config.format`` as it is, and the API
refused all 210 of those asks (``invalid_request_error``): structured outputs take a SUBSET of JSON Schema (no ``minimum``, ``maximum``,
``maxLength``, ``maxItems``...), and every schema PrediGol asks for uses some of them. These tests hold three things: what ``accepted`` does,
that the original schema is never touched, and that EVERY schema the platform sends to a model comes out acceptable - so a change to one
of them that the API would refuse fails here, not in production.
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

import pytest

from fbi.ai import patterns, prompts
from fbi.ai.claims import REVIEW_SCHEMA
from fbi.ai.contracts import schema_of
from fbi.ai.contracts.base import CLAIM
from fbi.ai.lab import PROBE_SCHEMA
from fbi.ai.providers import structured
from fbi.ai.providers.anthropic import AnthropicBatches, build_body
from fbi.ai.providers.base import JsonRequest

EVERY_SCHEMA: dict[str, dict[str, Any]] = {
    "review": REVIEW_SCHEMA, "extract (v1)": prompts.EXTRACT_SCHEMA, "brief": prompts.BRIEF_SCHEMA,
    "postmortem": prompts.POSTMORTEM_SCHEMA, "pick postmortem": prompts.PICK_PM_SCHEMA, "learning": prompts.LEARNING_SCHEMA,
    "patterns": patterns.AI_SCHEMA, "probe": PROBE_SCHEMA, "claims (research v2)": schema_of(CLAIM),
}


def test_a_schema_with_nothing_to_move_comes_out_equal_and_new() -> None:
    plain = {"type": "object", "additionalProperties": False, "required": ["decision"],
             "properties": {"decision": {"type": "string", "enum": ["APPROVE", "REJECT"]},
                            "notes": {"type": "array", "minItems": 1, "items": {"type": "string"}}}}
    out = structured.accepted(plain)
    assert out == plain and out is not plain and out["properties"] is not plain["properties"]
    assert structured.problems(plain) == []


def test_what_the_api_refuses_moves_into_the_description_and_the_original_is_not_touched() -> None:
    original = {"type": "object", "additionalProperties": False, "required": ["score", "reason", "items"],
                "properties": {
                    "score": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string", "maxLength": 400, "description": "Why."},
                    "items": {"type": "array", "maxItems": 8, "minItems": 2, "items": {"type": "integer", "minimum": 0}}}}
    before = copy.deepcopy(original)
    out = structured.accepted(original)
    assert original == before, "the schema that validates the answer is the original one"
    props = out["properties"]
    assert props["score"] == {"type": "number", "description": "{minimum: 0, maximum: 1}"}
    assert props["reason"] == {"type": "string", "description": "Why. {maxLength: 400}"}
    assert props["items"]["description"] == "{maxItems: 8, minItems: 2}" and "maxItems" not in props["items"]
    assert props["items"]["items"] == {"type": "integer", "description": "{minimum: 0}"}
    assert structured.problems(original) != [] and structured.problems(out) == []


def test_min_items_of_zero_or_one_is_supported_and_stays() -> None:
    out = structured.accepted({"type": "array", "minItems": 1, "items": {"type": "string"}})
    assert out["minItems"] == 1 and "description" not in out
    out = structured.accepted({"type": "array", "minItems": 0, "items": {"type": "string"}})
    assert out["minItems"] == 0
    assert structured.accepted({"type": "array", "minItems": 3, "items": {"type": "string"}}) == {
        "type": "array", "items": {"type": "string"}, "description": "{minItems: 3}"}


def test_a_property_named_like_a_keyword_is_a_name_and_not_a_constraint() -> None:
    schema = {"type": "object", "additionalProperties": False, "required": ["minimum", "maxItems"],
              "properties": {"minimum": {"type": "number", "maximum": 5}, "maxItems": {"type": "string"}}}
    out = structured.accepted(schema)
    assert set(out["properties"]) == {"minimum", "maxItems"}
    assert out["properties"]["minimum"] == {"type": "number", "description": "{maximum: 5}"}
    assert out["properties"]["maxItems"] == {"type": "string"}
    assert structured.problems(out) == []


def test_an_object_is_closed_when_the_schema_forgot_to_close_it() -> None:
    out = structured.accepted({"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}})
    assert out["additionalProperties"] is False
    open_object = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
    assert any("additionalProperties" in p for p in structured.problems(open_object))


def test_the_limits_of_a_request_are_counted() -> None:
    many = {f"p{i}": {"type": "string"} for i in range(structured.MAX_OPTIONAL + 1)}
    over = {"type": "object", "additionalProperties": False, "required": [], "properties": many}
    assert any("optional parameters" in p for p in structured.problems(over))
    unions = {f"u{i}": {"type": ["string", "null"]} for i in range(structured.MAX_UNIONS + 1)}
    wide = {"type": "object", "additionalProperties": False, "required": list(unions), "properties": unions}
    assert any("union type" in p for p in structured.problems(wide))
    ok = {"type": "object", "additionalProperties": False, "required": list(unions)[: structured.MAX_UNIONS],
          "properties": dict(list(unions.items())[: structured.MAX_UNIONS])}
    assert structured.problems(ok) == []


@pytest.mark.parametrize("name", sorted(EVERY_SCHEMA))
def test_every_schema_the_platform_asks_for_is_accepted_once_simplified(name: str) -> None:
    schema = EVERY_SCHEMA[name]
    before = copy.deepcopy(schema)
    out = structured.accepted(schema)
    assert structured.problems(out) == [], f"{name}: the API would refuse it"
    assert schema == before
    # nothing but descriptions changed: the same properties, the same required fields, the same enums
    assert json.dumps(_skeleton(out), sort_keys=True) == json.dumps(_skeleton(schema), sort_keys=True)


def test_the_review_schema_is_the_one_the_experiment_got_refused() -> None:
    """The very schema of the 210 refused asks: it did carry what the API does not take, and it does not once simplified."""
    raw = structured.problems(REVIEW_SCHEMA)
    assert any("'minimum'" in p for p in raw) and any("'maxItems'" in p for p in raw) and any("'maxLength'" in p for p in raw)
    assert structured.problems(structured.accepted(REVIEW_SCHEMA)) == []


def test_a_native_request_carries_the_simplified_schema_and_a_tool_request_the_original() -> None:
    req = JsonRequest(system="You review.", user="{}", schema=REVIEW_SCHEMA, schema_name="submit_review", max_tokens=900,
                      timeout_s=5)
    native = build_body("claude-sonnet-5-5", replace(req, native_schema=True), forced=True, effort=None, native=True)
    assert native["output_config"]["format"]["schema"] == structured.accepted(REVIEW_SCHEMA)
    assert structured.problems(native["output_config"]["format"]["schema"]) == []
    tool = build_body("claude-sonnet-5-5", req, forced=True, effort=None, native=False)
    assert tool["tools"][0]["input_schema"] == REVIEW_SCHEMA, "a forced tool call takes the whole schema, as it always did"
    item = AnthropicBatches.item("c" * 64, "claude-sonnet-5-5", replace(req, native_schema=True))["params"]
    assert structured.problems(item["output_config"]["format"]["schema"]) == [], "inside a batch too"


def _skeleton(node: Any) -> Any:
    """The schema without descriptions and without the constraints that move: what must survive the simplification."""
    if isinstance(node, list):
        return [_skeleton(n) for n in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "description" or key in structured.MOVED or (key == "minItems" and value not in (0, 1)):
            continue
        out[key] = {n: _skeleton(s) for n, s in value.items()} if key in ("properties", "$defs", "definitions") else _skeleton(value)
    return out


def test_the_batch_fake_ends_an_ask_with_a_schema_the_api_refuses_as_the_real_api_did() -> None:
    from fbi.ai.providers.fake import FakeBatches

    req = JsonRequest(system="You review.", user="{}", schema=REVIEW_SCHEMA, schema_name="submit_review", max_tokens=900,
                      timeout_s=5, native_schema=True)
    raw = {"custom_id": "a" * 64, "params": {
        "model": "claude-sonnet-5-5", "max_tokens": 900, "system": "You review.", "messages": [{"role": "user", "content": "{}"}],
        "output_config": {"format": {"type": "json_schema", "schema": REVIEW_SCHEMA}}}}
    good = AnthropicBatches.item("b" * 64, "claude-sonnet-5-5", req)
    fake = FakeBatches(lambda r: {"decision": "REJECT"})
    ref = fake.create([raw, good])["id"]
    fake.end(ref)
    results = {r.custom_id: r for r in fake.results(ref)}
    assert results["a" * 64].kind == "errored" and results["a" * 64].error_type == "invalid_request_error"
    assert results["b" * 64].kind == "succeeded"
