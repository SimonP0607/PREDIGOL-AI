"""Plan Maestro IA, Phase 0, in the ledger: what a call cost to the cent when part of its input was written to the cache and part
read from it, whose money it was (production's or the LAB's), what happens when the provider says a spend limit is spent, and the
switches of the optimisations (the owner's word, then the evidence in ``ai.feature_gates``).

No network and no key: the "provider" is ``FakeProvider`` and says what a real API would report. One transaction, rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import gates
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.providers.base import JsonRequest, LlmUsage
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, call_json, lab_spent_month, scope_spent, shared, with_switches

AT = datetime(2032, 8, 1, 12, 0, tzinfo=UTC)  # 07:00 in Bogotá
SONNET = TierModel("anthropic", "claude-sonnet-5-5")
SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "required": ["decision"],
                          "properties": {"decision": {"type": "string"}}}
REQ = JsonRequest(system="You review.", user='{"candidate": 1}', schema=SCHEMA, schema_name="submit_review",
                  max_tokens=900, timeout_s=5)


def settings(**kw: Any) -> AiSettings:
    base: dict[str, Any] = {"mode": "shadow", "tiers": {"analysis": SONNET}, "keys": {"anthropic": "k"},
                            "lab_keys": {"anthropic": "kl"}, "monthly_budget": Decimal("185"),
                            "daily_budget": Decimal("6")}
    return AiSettings(**(base | kw))


def provider(**kw: Any) -> FakeProvider:
    return FakeProvider(lambda _r: {"decision": "APPROVE"}, name="anthropic", **kw)


def billed(_request: JsonRequest, _counted: LlmUsage) -> LlmUsage:
    """2,000 fresh + 6,000 read + 1,500 written for 5 minutes + 500 written for an hour; 900 written, 300 of them thinking."""
    return LlmUsage(input_tokens=10_000, output_tokens=900, cached_tokens=6_000, cache_write_5m_tokens=1_500,
                    cache_write_1h_tokens=500, thinking_tokens=300)


def run(db: psycopg.Connection[Any], p: FakeProvider, *, cfg: AiSettings | None = None, lab: bool = False,
        at: datetime = AT, purpose: Any = "pick_review", **kw: Any) -> Any:
    return call_json(db, cfg or settings(), tier="analysis", purpose=purpose, request=REQ, at=at,
                     prompt_version="review-v9", input_hash="h", ledger=UsageLedger(shared(db)),
                     provider=(p, SONNET.model), lab=lab, **kw)


def test_a_call_is_recorded_with_its_cache_writes_per_ttl_and_priced_to_the_cent(db: psycopg.Connection[Any]) -> None:
    out = run(db, provider(usage=billed), agent="match", run_id=7)
    # Sonnet 5.5 (USD per 1M): 2,000 x 2 + 6,000 x 0.10 + 1,500 x 2 x 1.25 + 500 x 2 x 2 + 900 x 10 = 19,350 / 1M
    assert out.cost == Decimal("0.019350") and out.error is None
    row = db.execute("SELECT input_tokens, output_tokens, cached_tokens, cache_write_tokens, cache_write_1h_tokens, "
                     "cache_ttl, thinking_tokens, workspace, key_label, agent, run_id, batch_id, custom_id, cost_usd, "
                     "scope, status FROM ai.usage_scoped WHERE id = %s", (out.usage_id,)).fetchone()
    assert row == (10_000, 900, 6_000, 2_000, 500, "mixed", 300, "PREDIGOL", "worker-prod", "match", 7, None, None,
                   Decimal("0.019350"), "production", "ok")


def test_a_call_that_wrote_no_cache_says_so_and_the_old_cost_is_unchanged(db: psycopg.Connection[Any]) -> None:
    out = run(db, provider(usage=lambda _r, _c: LlmUsage(input_tokens=10_000, output_tokens=1_000)))
    assert out.cost == Decimal("0.030000")  # 10,000 x 2 + 1,000 x 10, per million
    row = db.execute("SELECT cache_write_tokens, cache_write_1h_tokens, cache_ttl, thinking_tokens FROM ai.usage "
                     "WHERE id = %s", (out.usage_id,)).fetchone()
    assert row == (0, 0, None, 0), "a written zero: this call is known to have written nothing (NULL is the rows before 0110)"


def test_the_labs_call_is_the_labs_money_under_its_own_key_name_and_stops_at_its_envelope(
        db: psycopg.Connection[Any]) -> None:
    lab = settings(lab_monthly_budget=Decimal("0.03"))
    first = run(db, provider(usage=billed), cfg=lab, lab=True)
    second = run(db, provider(usage=billed), cfg=lab, lab=True)
    assert first.error is None and second.error is None, "0.0194 spent of 0.03: still inside the envelope"
    row = db.execute("SELECT workspace, key_label, scope FROM ai.usage_scoped WHERE id = %s", (first.usage_id,)).fetchone()
    assert row == ("PREDIGOL-LAB", "worker-lab", "lab")
    assert lab_spent_month(db, AT) == Decimal("0.038700")
    p = provider(usage=billed)
    third = run(db, p, cfg=lab, lab=True)
    assert third.error == "over_budget" and third.result is None and p.requests == [], "spent: no request is made"
    assert scope_spent(db, "production", AT - timedelta(days=1), AT + timedelta(days=1)) == 0, \
        "the LAB's money is never production's"


def test_a_lab_without_an_envelope_makes_no_call(db: psycopg.Connection[Any]) -> None:
    p = provider(usage=billed)
    out = run(db, p, lab=True)  # lab_monthly_budget defaults to 0
    assert out.error == "over_budget" and p.requests == []


def test_a_workspace_limit_is_recorded_once_and_answered_as_over_budget(db: psycopg.Connection[Any]) -> None:
    p = provider(limit="workspace_limit")
    out = run(db, p)
    assert out.error == "over_budget" and out.result is None and len(p.requests) == 1
    usage_row = db.execute("SELECT status, error, workspace, request_id, cost_usd FROM ai.usage WHERE id = %s",
                           (out.usage_id,)).fetchone()
    assert usage_row == ("over_budget", "limit_reached: workspace_limit (HTTP 400)", "PREDIGOL", "req_fake", 0)
    hits = db.execute("SELECT provider, workspace, key_label, kind, http_status, request_id, purpose "
                      "FROM ai.limit_hits").fetchall()
    assert hits == [("anthropic", "PREDIGOL", "worker-prod", "workspace_limit", 400, "req_fake", "pick_review")]


def test_the_tier_cap_of_the_account_is_told_apart_from_the_workspaces_limit(db: psycopg.Connection[Any]) -> None:
    out = run(db, provider(limit="tier_cap"), lab=True, cfg=settings(lab_monthly_budget=Decimal("15")))
    assert out.error == "over_budget"
    assert db.execute("SELECT workspace, kind, http_status FROM ai.limit_hits").fetchall() == [
        ("PREDIGOL-LAB", "tier_cap", 429)], "the LAB's limit is recorded under the LAB's name"


# ── the switches ──────────────────────────────────────────────────────────────────────────────


def test_without_evidence_the_cache_is_on_and_batch_and_structured_outputs_wait(db: psycopg.Connection[Any]) -> None:
    s = settings()
    assert [gates.enabled(db, s, n) for n in ("cache", "brief_material", "budget_v3")] == [True, True, True]
    assert gates.enabled(db, s, "batch") is False and gates.enabled(db, s, "native_schema", model=SONNET.model) is False
    assert gates.enabled(db, s, "no_such_switch") is False, "a typo never switches anything on"
    assert gates.layout_shared(db, s, model=SONNET.model) is False, "the shared block waits for its own gate"


def test_a_gate_decides_by_its_newest_evidence_and_only_for_the_models_it_names(db: psycopg.Connection[Any]) -> None:
    s = settings()
    gates.record_gate(db, gate="native_schema", passed=True, at=AT, code_version="abc",
                      evidence={"packets": 200, "models": [SONNET.model], "verdict_change": 0.01, "baseline": 0.03})
    assert gates.enabled(db, s, "native_schema", model=SONNET.model) is True
    assert gates.enabled(db, s, "native_schema", model="claude-haiku-5-5") is False, "another model is not covered"
    assert gates.enabled(db, s, "native_schema") is False, "no model named, none covered"
    gates.record_gate(db, gate="native_schema", passed=False, at=AT + timedelta(hours=1),
                      evidence={"packets": 200, "models": [SONNET.model], "verdict_change": 0.09, "baseline": 0.03})
    assert gates.enabled(db, s, "native_schema", model=SONNET.model) is False, "a failing re-run switches it off again"
    state = gates.gate_state(db, "native_schema")
    assert (state.passed, state.models) == (False, (SONNET.model,)) and len(state.evidence_hash or "") == 64


def test_evidence_that_names_no_model_covers_every_model_and_the_hash_ignores_key_order(
        db: psycopg.Connection[Any]) -> None:
    assert gates.evidence_hash({"a": 1, "b": [1, 2]}) == gates.evidence_hash({"b": [1, 2], "a": 1})
    assert gates.evidence_hash({"a": 1}) != gates.evidence_hash({"a": 2})
    gates.record_gate(db, gate="batch", passed=True, at=AT, evidence={"probe": "succeeded", "items": 3})
    assert gates.enabled(db, settings(), "batch", model="anything") is True
    with pytest.raises(ValueError):
        gates.record_gate(db, gate="something_else", passed=True, at=AT, evidence={})


def test_the_owner_overrides_the_evidence_both_ways(db: psycopg.Connection[Any]) -> None:
    gates.record_gate(db, gate="batch", passed=True, at=AT, evidence={"probe": "succeeded"})
    assert gates.enabled(db, settings(switches={"batch": "off"}), "batch") is False, "rolled back by the owner"
    assert gates.enabled(db, settings(), "batch") is True, "the evidence is there"
    assert gates.enabled(db, settings(switches={"native_schema": "on"}), "native_schema") is True, "forced on"
    assert gates.enabled(db, settings(switches={"cache": "off"}), "cache") is False
    assert gates.enabled(db, settings(switches={"budget_v3": "off"}), "budget_v3") is False


def test_the_shared_match_block_needs_its_gate_and_a_cache_that_is_not_off(db: psycopg.Connection[Any]) -> None:
    forced = settings(switches={"cache": "on"})
    assert gates.layout_shared(db, forced, model=SONNET.model) is False, "forcing the cache does not skip the gate"
    gates.record_gate(db, gate="cache_layout", passed=True, at=AT, evidence={"packets": 200, "models": [SONNET.model]})
    assert gates.layout_shared(db, settings(), model=SONNET.model) is True
    assert gates.layout_shared(db, forced, model=SONNET.model) is True
    assert gates.layout_shared(db, settings(), model="claude-haiku-5-5") is False, "measured for another model"
    assert gates.layout_shared(db, settings(switches={"cache": "off"}), model=SONNET.model) is False, "rolled back"


def test_a_call_asks_for_the_cache_and_for_structured_outputs_only_when_they_are_in_force(
        db: psycopg.Connection[Any]) -> None:
    p = provider()
    run(db, p)
    assert (p.requests[0].cache, p.requests[0].native_schema) == (True, False)
    gates.record_gate(db, gate="native_schema", passed=True, at=AT, evidence={"models": [SONNET.model]})
    q = provider()
    run(db, q)
    assert (q.requests[0].cache, q.requests[0].native_schema) == (True, True)
    r = provider()
    run(db, r, cfg=settings(switches={"cache": "off", "native_schema": "off"}))
    assert (r.requests[0].cache, r.requests[0].native_schema) == (False, False), "both rolled back by the owner"


def test_a_request_keeps_what_its_caller_asked_for(db: psycopg.Connection[Any]) -> None:
    asked = JsonRequest(system="s", user="u", schema=SCHEMA, schema_name="x", cache=True, native_schema=True)
    assert with_switches(db, settings(switches={"cache": "off", "native_schema": "off"}), asked, SONNET.model) is asked
    plain = JsonRequest(system="s", user="u", schema=SCHEMA, schema_name="x")
    assert with_switches(db, settings(switches={"cache": "off"}), plain, SONNET.model) is plain, "nothing to change"


def test_the_panel_says_what_each_optimisation_is_doing_and_why(db: psycopg.Connection[Any]) -> None:
    gates.record_gate(db, gate="batch", passed=True, at=AT, evidence={"probe": "succeeded"})
    d = gates.describe(db, settings(switches={"brief_material": "off", "native_schema": "on"}))
    assert d["batch"]["on"] is True and d["batch"]["why"] == "the batch gate passed"
    assert d["native_schema"]["on"] is True and d["native_schema"]["why"] == "forced on by the owner"
    assert d["brief_material"]["on"] is False and "FBI_AI_BRIEF_MATERIAL=0" in d["brief_material"]["why"]
    assert d["cache"]["on"] is True and d["cache_layout"]["on"] is False
    assert d["gates"]["batch"]["passed"] is True and d["gates"]["gate_a"]["passed"] is False
