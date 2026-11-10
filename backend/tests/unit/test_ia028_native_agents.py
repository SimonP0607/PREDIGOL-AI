"""IA-028 (R1 of the audit of 10 Nov 2026): the Match Agent's v5 and the Statistics Agent's v4 ask for their answer with structured outputs.

The prompts, the contract (``aa-v1``), the reader, the model and the effort are those of match-v4 and stats-v3; what changes is how the answer is asked
(``output_config.format`` instead of the forced tool call), and that is a new version of each agent, born a challenger. The battery measures them as
production asks them, and the Council does not change."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fbi.ai import prompts
from fbi.ai.agents import council, match, stats
from fbi.ai.agents import registry as rg
from fbi.ai.battery import agentworld, corpus
from fbi.ai.battery import run as battery_run
from fbi.ai.providers.anthropic import AnthropicBatches, build_body
from fbi.ai.providers.base import JsonRequest

AT = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def requests() -> dict[str, JsonRequest]:
    return {"match/context": corpus.request_for("match", "m_context"), "match/evaluation": corpus.request_for("match", "m_reject"),
            "stats/evaluation": corpus.request_for("stats", "s_high")}


def test_the_two_agents_ask_natively_and_the_council_does_not() -> None:
    assert (match.VERSION, match.NATIVE, stats.VERSION, stats.NATIVE) == ("match-v5", True, "stats-v4", True)
    for mode, base in (("CONTEXT", "m_context"), ("EVALUATION", "m_reject")):
        own = agentworld.request_of(agentworld.build("match", base))
        assert own.native_schema is True and own.system == match.SYSTEM[mode], mode
    assert agentworld.request_of(agentworld.build("stats", "s_high")).native_schema is True
    assert agentworld.request_of(agentworld.build("council", "k_approve")).native_schema is False, "the Council keeps the tool call (cd-v1 on Sonnet)"
    assert (prompts.MATCH_CONTEXT_VERSION, prompts.MATCH_ASSESS_VERSION, prompts.STATS_ASSESS_VERSION) == (
        "match-context-v4", "match-assess-v3", "stats-assess-v3"), "no prompt changes: the same texts, asked another way"


def test_the_body_puts_the_schema_in_the_output_format_and_offers_no_tool() -> None:
    for name, request in requests().items():
        body = build_body("claude-haiku-5-5", request, forced=False, effort=request.effort, native=request.native_schema)
        assert "tools" not in body and "tool_choice" not in body, name
        assert body["output_config"]["format"]["type"] == "json_schema" and body["output_config"]["effort"] == request.effort, name
        assert body["system"] == request.system, "native: no line asking to answer through a tool"
        item = AnthropicBatches.item("x", "claude-haiku-5-5", request)
        assert "tools" not in item["params"] and item["params"]["output_config"]["format"]["type"] == "json_schema", name


def test_the_registry_holds_v5_and_v4_as_new_challengers_with_the_prompts_of_before() -> None:
    assert not rg.REGISTRY.problems()
    for agent, version, previous in (("match", "match-v5", "match-v4"), ("stats", "stats-v4", "stats-v3")):
        entry, before = rg.REGISTRY.in_force(agent), next(e for e in rg.REGISTRY.history(agent) if e.version == previous)
        assert (entry.version, entry.phase, entry.born_as, entry.baseline, entry.decided_by) == (version, "IA-028", "CHALLENGER", False, "owner")
        assert entry.registered_at > before.registered_at and entry.fingerprint != before.fingerprint
        assert rg.live_fingerprint(rg.REGISTRY.spec(agent)) == entry.fingerprint
        assert {t: replace(p, native=False) for t, p in entry.parts.items()} == dict(before.parts), "the same labels and hashes"
        assert all(p.native for p in entry.parts.values()) and not any(p.native for p in before.parts.values())
        assert "battery-v3" in entry.reason and "CHALLENGER" in entry.reason and "intel.promotions" in entry.reason
        for task in entry.parts:
            now = rg.REGISTRY.identity_for(agent, task, workspace="lab", input_version="mcp-v1", input_hash="a" * 64, pass_kind="pre", fixture_id=7)
            then = replace(now, agent_version=previous)
            assert now.agent_version == version and now.key != then.key, "a question of v5 never reuses an answer of v4"
    assert rg.REGISTRY.in_force("council").version == council.VERSION == "council-v1"


def test_the_battery_asks_as_production_does_and_has_one_route_for_them() -> None:
    for target in ("match", "stats"):
        assert battery_run.run_id(target) == battery_run.run_id(target, native=True), target
        assert corpus.target(target).agent == {"match": match.VERSION, "stats": stats.VERSION}[target]
        assert all(r.native_schema and r.pinned for r in requests().values())
    assert battery_run.run_id("council") != battery_run.run_id("council", native=True)


def test_the_measured_run_is_the_run_of_the_new_versions() -> None:
    """The native round of 10 Nov 2026 (``battery-v3:match:2724a8fcc92b`` and ``battery-v3:stats:b76f3cf39167``, 0 of 55 refused in each) asked the
    very requests v5 and v4 send: the same run, so the gate is recorded from it without asking again."""
    assert battery_run.run_id("match") == "battery-v3:match:2724a8fcc92b"
    assert battery_run.run_id("stats") == "battery-v3:stats:b76f3cf39167"
