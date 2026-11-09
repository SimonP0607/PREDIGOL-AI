"""The registry of the agents (``fbi.ai.agents.registry``, Plan Maestro IA, phase 1, sections 11 and 25): held to the code, so that an agent cannot
change without a new version, and a prompt label cannot name two texts. No database, no model.

The first tests are the gate, run against the code as it is. The rest build a registry out of the real one plus ONE defect (or a synthetic agent
whose prompt can be edited in the test) and say which finding it makes - and which it does not."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from fbi.ai import prompts, router
from fbi.ai.agents import registry as rg
from fbi.ai.agents.registry import (
    AGENTS,
    LEDGER,
    PLANNED,
    POSTPONED,
    REGISTRY,
    AgentSpec,
    BuiltTask,
    Definition,
    Part,
    PlannedAgent,
    PlannedTask,
    PostponedAgent,
    Registration,
    Registry,
    RegistryError,
)
from fbi.ai.contracts.base import OUTPUTS
from fbi.ai.contracts.mcp import SLICE_NAMES
from fbi.ai.idempotency import changed_fields, idem_key
from fbi.ai.usage import TIER_EFFORT

AT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
REASON = "a reason a person can look back on, longer than the forty characters the registry asks for"
HASH = "a" * 64
SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "required": ["a"], "properties": {"a": {"type": "string"}}}


def codes(registry: Registry, **kw: Any) -> set[str]:
    return {p.code for p in registry.problems(**kw)}


def with_(**changes: Any) -> Registry:
    return replace(REGISTRY, **changes)


# -- the gate: the registry against the code as it is ---------------------------------------------------------------------------------

def test_the_registry_holds_to_the_code_as_it_is() -> None:
    problems = REGISTRY.problems()
    assert not problems, "the registry and the code disagree:\n" + "\n".join(str(p) for p in problems)


def test_the_versions_of_the_prompts_are_the_upper_case_text_constants_that_end_in_version() -> None:
    module = SimpleNamespace(BRIEF_VERSION="brief-v8", REVIEW_VERSION="review-v2", lower_version="x-v1", VERSION_OF_NOTHING="x-v1",
                             SOME_VERSION=5, OTHER=1, EMPTY_VERSION=None, MAX_VERSION=("a",), Mixed_VERSION="x-v2")
    assert rg.live_prompt_versions(module) == {"BRIEF_VERSION": "brief-v8", "REVIEW_VERSION": "review-v2"}
    assert rg.live_prompt_versions() == rg.live_prompt_versions(prompts)


def test_every_prompt_of_the_code_belongs_to_an_agent_of_the_registry() -> None:
    labels = rg.live_prompt_versions()
    assert set(labels) >= {"BRIEF_VERSION", "REVIEW_VERSION", "EXTRACT_VERSION", "POSTMORTEM_VERSION", "PICK_PM_VERSION", "LEARNING_VERSION"}
    used = {p.prompt_version for s in AGENTS for p in rg.live_parts(s).values()}
    assert set(labels.values()) <= used
    assert used <= set(labels.values()), "and the registry names no prompt that the code does not have"


def test_the_agents_of_the_old_route_run_at_the_effort_its_guard_gives_their_tier() -> None:
    for spec in AGENTS:
        for t in spec.tasks:
            if t.tier is not None:
                assert TIER_EFFORT[t.tier] == t.effort, f"{spec.agent}/{t.task}: the tier {t.tier} is asked at {TIER_EFFORT[t.tier]}"


APART = {"stats": {"stats-assess-v3"}, "player": {"player-assess-v1"}}
"""The agents whose version (``stats-v3``) is not the label of their one prompt (``stats-assess-v3``): phase 4's Statistics Agent and IA-017's Player
Agent (``player-v1``, ``player-assess-v1``)."""
OWN_PROMPTS = {"council": ("council-opus-v1",)}
"""The agents whose version is the label of their main prompt and that run one more task with a prompt of its own (the Council's Opus)."""


def test_the_version_of_an_agent_is_the_label_of_its_prompt() -> None:
    for spec in AGENTS:
        version = REGISTRY.in_force(spec.agent).version
        labels = {p.prompt_version for p in rg.live_parts(spec).values()}
        if spec.agent in OWN_PROMPTS:  # the Council: the version is the label of its main prompt and Opus has a prompt of its own
            assert labels == {version, *OWN_PROMPTS[spec.agent]}, spec.agent
        elif spec.agent in APART:  # the Match and the Statistics Agents: the version of the agent is not the label of its prompt
            assert version not in labels and labels == APART[spec.agent], spec.agent
        elif len(labels) == 1:
            assert labels == {version}, spec.agent
        else:  # an agent of the plan with a prompt of its own for each task (``match-v3``: match-context-v3 and match-assess-v3)
            assert len(labels) == len(spec.tasks) and version not in labels, spec.agent
        schemas = {p.schema_version for p in rg.live_parts(spec).values()}
        if spec.contract is None:
            assert schemas == {version}, "the AI that runs today versions its schema with its prompt"
        else:
            assert schemas == {spec.contract}, "an agent of the plan answers in a contract, and the contract is the label of its schema"


def test_what_the_plan_builds_is_what_the_router_and_the_contracts_can_run() -> None:
    for plan in PLANNED:
        assert plan.contract in OUTPUTS
        assert plan.reads is None or plan.reads in SLICE_NAMES or plan.reads in rg.VIEWS
        for t in plan.tasks:
            spec = router.SPECS[t.task]
            assert t.model == router.MODELS[spec.level], f"{plan.agent}/{t.task}"
            assert t.effort == spec.effort, f"{plan.agent}/{t.task}"


def test_the_plan_gives_each_agent_its_phase_and_its_prompts() -> None:
    by_agent = {(p.agent, p.version): p for p in PLANNED}
    assert {k: v.phase for k, v in by_agent.items()} == {
        }, "phases 2 to 5 are built: the extractor, the Match Agent, the Council, the Statistics Agent and the two agents of the learning left the plan for the code"
    assert {(p.agent, p.contract) for p in PLANNED} == set()
    assert {p.agent: p.replaces for p in PLANNED if p.replaces} == {}


def test_the_council_judges_with_sonnet_and_opus_only_by_escalation_and_the_match_agent_reads_with_haiku() -> None:
    models = {(p.agent, t.task): t.model for p in PLANNED for t in p.tasks} | {(s.agent, t.task): t.model for s in AGENTS for t in s.tasks if t.model}
    assert models[("council", "council")] == "claude-sonnet-5-5"
    assert models[("council", "escalation")] == "claude-opus-5-5"
    assert models[("match", "context")] == models[("match", "evaluation")] == models[("stats", "evaluation")] == "claude-haiku-5-5"
    assert models[("la", "analyst")] == "claude-sonnet-5-5"
    assert models[("pmr", "narrative")] == "claude-haiku-5-5" and models[("pmr", "loss_review")] == "claude-sonnet-5-5"
    assert "claude-fable-5-1" not in set(models.values()), "Fable is the owner's own research: no agent runs on it"


def test_the_player_agent_is_built_off_in_shadow_and_nothing_is_postponed() -> None:
    """IA-017 moved the Player Agent from POSTPONED to AGENTS (``player-v1``); what its gate F-Player still holds back is said in its purpose."""
    assert POSTPONED == ()
    spec = REGISTRY.spec("player")
    assert spec.contract == "pa-v1" and spec.reads == "player" and "F-Player" in spec.purpose and "OFF by default" in spec.purpose
    assert "player" not in {p.agent for p in PLANNED}


BASELINE_AGENTS = ("brief", "reviewer", "extractor", "postmortem", "post_match_reviewer", "learning_analyst")
"""The AI that was already in force when the registry was started (phase 1). Every other agent of the code was born later, as a challenger."""


def test_the_ledger_starts_every_agent_of_today_as_a_baseline_champion() -> None:
    baselines = [r for r in LEDGER if r.baseline]
    assert [r.agent for r in baselines] == list(BASELINE_AGENTS)
    for r in baselines:
        assert r.born_as == "CHAMPION" and r.decided_by == "system", r.agent
        assert rg.FINGERPRINT.fullmatch(r.fingerprint)
        assert "after the fact" in r.reason, "a baseline says it was recorded afterwards"
        assert REGISTRY.history(r.agent)[0] is r, "and it is the first entry of its agent"


def test_an_agent_built_after_the_baseline_is_born_a_challenger_with_a_reason_and_replaces_one_of_the_registry() -> None:
    """Phase 2 builds the claim extractor beside the extractor of today: the same registry holds both, the switch of the phase decides which runs,
    and only a row the owner signs in ``intel.promotions`` makes the new one the champion. Phase 3 builds the Match Agent and the Council, born
    the same way; neither replaces an agent of the registry. Phase 4 builds the Statistics Agent, born a challenger too. Phase 5 builds the Post-Match
    Reviewer (``pmr``) and the Learning Analyst (``la``) beside the two of today (``post_match_reviewer``, ``learning_analyst``): the registry holds one
    version of an agent - the one the code has - and the code still has pick-postmortem-v4 and learning-v2 until the owner signs, so the new versions
    are agents of their own that REPLACE the old ones."""
    built = {s.agent for s in AGENTS} - set(BASELINE_AGENTS)
    assert built == {"claim_extractor", "match", "council", "stats", "pmr", "la", "player"}
    for agent in built:
        entry = REGISTRY.history(agent)[0]
        assert not entry.baseline and entry.born_as == "CHALLENGER" and entry.decided_by in rg.DECIDERS
        assert len(entry.reason) >= rg.MIN_REASON
        assert entry.phase == {"claim_extractor": "IA-2", "match": "IA-3", "council": "IA-3", "stats": "IA-4", "pmr": "IA-5", "la": "IA-5",
                               "player": "IA-017"}[agent]
        for later in REGISTRY.history(agent)[1:]:  # a later version is born the same way: a challenger, never promoted by the code
            assert not later.baseline and later.born_as == "CHALLENGER" and len(later.reason) >= rg.MIN_REASON
    assert {a: [r.version for r in REGISTRY.history(a)] for a in built if len(REGISTRY.history(a)) > 1} == {
        "match": ["match-v1", "match-v2", "match-v3", "match-v4"], "stats": ["stats-v1", "stats-v2", "stats-v3"],
        "claim_extractor": ["extract-v2", "extract-v3"]}, (
        "IA-009: the prompts of aa-v1 with their output checklist; IA-014: the Match Agent's v3 with the references of the package; IA-018: the "
        "Statistics Agent's v3 with the closed checklist and the Match Agent's CONTEXT prompt v4; IA-021: the Claim Extractor's v3 names the player in his quote")
    assert {s.agent: s.replaces for s in AGENTS if s.replaces} == {
        "claim_extractor": "extractor", "pmr": "post_match_reviewer", "la": "learning_analyst"}
    assert (REGISTRY.in_force("pmr").version, REGISTRY.in_force("la").version) == ("pmr-v1", "la-v1")
    assert (REGISTRY.in_force("post_match_reviewer").version, REGISTRY.in_force("learning_analyst").version) == ("pick-postmortem-v4", "learning-v2")
    assert REGISTRY.spec("claim_extractor").contract == "claim-v1"
    assert REGISTRY.in_force("claim_extractor").version == "extract-v3" and REGISTRY.in_force("extractor").version == "extract-v1"


# -- the fingerprint ------------------------------------------------------------------------------------------------------------------

def definition(text: str = "the prompt", *, schema: dict[str, Any] | None = None, label: str = "x-v1", schema_label: str | None = None) -> Definition:
    return Definition(label, text, schema_label or label, SCHEMA if schema is None else schema)


def agent(box: dict[str, Any] | None = None, **kw: Any) -> AgentSpec:
    """A synthetic agent whose live definition is read from ``box`` when asked, so that a test can edit its prompt as a developer would."""
    state = box if box is not None else {}
    tasks = kw.pop("tasks", None) or (BuiltTask("t", "low", lambda: definition(**state), tier="bulk"),)
    return AgentSpec(kw.pop("name", "x"), kw.pop("purpose", "a synthetic agent"), tasks, **kw)


def entry(spec: AgentSpec, version: str = "x-v1", *, at: datetime = AT, baseline: bool = False, **kw: Any) -> Registration:
    parts = rg.live_parts(spec)
    return Registration(spec.agent, version, at, "owner", "IA-1", REASON, rg.fingerprint_of(spec, parts), parts,
                        born_as="CHAMPION" if baseline else "CHALLENGER", baseline=baseline, **kw)


def lone(spec: AgentSpec, *ledger: Registration) -> Registry:
    """A registry of one agent. It has no plan, so coverage findings are expected and left out of what the tests look at."""
    return Registry(agents=(spec,), planned=(), postponed=(), ledger=ledger or (entry(spec, baseline=True),))


COVERAGE = {"task_unserved", "contract_unwritten"}


def own(registry: Registry, **kw: Any) -> set[str]:
    return codes(registry, prompt_versions={"X_VERSION": "x-v1"} | kw.pop("labels", {})) - COVERAGE


def test_the_fingerprint_follows_everything_that_makes_an_agent_what_it_is() -> None:
    base = rg.live_fingerprint(agent())
    assert rg.FINGERPRINT.fullmatch(base)
    assert rg.live_fingerprint(agent()) == base, "the same code, the same fingerprint"
    t = BuiltTask("t", "low", lambda: definition(), tier="bulk")
    changed = {
        "the text of the prompt": agent({"text": "the prompt, edited"}),
        "the schema": agent({"schema": {**SCHEMA, "required": []}}),
        "the label of the prompt": agent({"label": "x-v2"}),
        "the label of the schema": agent({"schema_label": "y-v1"}),
        "the effort": agent(tasks=(replace(t, effort="medium"),)),
        "the tier": agent(tasks=(replace(t, tier="analysis"),)),
        "a model instead of a tier": agent(tasks=(replace(t, tier=None, model="claude-haiku-5-5"),)),
        "the name of the task": agent(tasks=(replace(t, task="u"),)),
        "another task": agent(tasks=(t, replace(t, task="u"))),
        "the contract": agent(contract="aa-v1"),
        "what it reads": agent(reads="match"),
        "the name of the agent": agent(name="y"),
    }
    for what, spec in changed.items():
        assert rg.live_fingerprint(spec) != base, f"{what} must make a new fingerprint"
    assert len({rg.live_fingerprint(s) for s in changed.values()}) == len(changed), "and each a different one"


def test_the_fingerprint_ignores_what_does_not_change_the_agent() -> None:
    base = rg.live_fingerprint(agent())
    assert rg.live_fingerprint(agent(purpose="said another way")) == base
    assert rg.live_fingerprint(agent(retire_phase=9)) == base, "when the plan retires an agent is not what the agent is"
    a = BuiltTask("a", "low", lambda: definition("one"), tier="bulk")
    b = BuiltTask("b", "medium", lambda: definition("two", label="y-v1"), tier="analysis")
    assert rg.live_fingerprint(agent(tasks=(a, b))) == rg.live_fingerprint(agent(tasks=(b, a))), "tasks are named, not ordered"


GOLDEN_TEXT = ('{"agent":"golden","contract":"aa-v1","method":"agent-fp-v1","reads":"match","tasks":{"t":{"effort":"medium","model":"claude-haiku-5-5",'
               '"prompt":["golden-v1","a98310efb4de"],"schema":["golden-v1","968e40317188"],"tier":null}}}')
GOLDEN = "ag3c9997ac51"


def test_the_method_of_the_fingerprint_has_a_golden_value() -> None:
    """If this fails and the gate does not, the METHOD changed: every entry of the ledger has to be written again with the new one."""
    spec = AgentSpec("golden", "p", (BuiltTask("t", "medium", lambda: definition("a prompt", label="golden-v1"), model="claude-haiku-5-5"),),
                     contract="aa-v1", reads="match")
    assert rg.FINGERPRINT_VERSION == "agent-fp-v1"
    assert rg.canonical(rg.fingerprint_body(spec, rg.live_parts(spec))) == GOLDEN_TEXT
    assert rg.live_fingerprint(spec) == GOLDEN, "ag + the first ten hex digits of the sha256 of the text above (checked with sha256sum)"


def test_a_text_is_hashed_as_utf8_in_twelve_hex_digits() -> None:
    assert rg.sha12("abc") == "ba7816bf8f01"
    assert rg.sha12("sí") != rg.sha12("si")
    assert rg.canonical({"b": 1, "a": [1, "é"]}) == '{"a":[1,"\\u00e9"],"b":1}'


# -- the findings ----------------------------------------------------------------------------------------------------------------------

def test_a_synthetic_registry_of_one_agent_is_clean() -> None:
    spec = agent()
    assert own(lone(spec)) == set()


def test_an_agent_the_ledger_does_not_have_says_what_to_add() -> None:
    spec = agent()
    registry = Registry(agents=(spec,), planned=(), postponed=(), ledger=())
    found = [p for p in registry.problems(prompt_versions={"X_VERSION": "x-v1"}) if p.code == "unregistered"]
    assert len(found) == 1 and found[0].subject == "x"
    assert 'Registration(agent="x", version="<version>"' in found[0].text and 'Part("x-v1", "' in found[0].text
    assert rg.fingerprint_of(spec, rg.live_parts(spec)) in found[0].text


def test_a_prompt_edited_without_a_new_version_fails_the_gate_with_the_entry_to_add() -> None:
    box: dict[str, Any] = {"text": "the prompt"}
    spec = agent(box)
    registry = lone(spec)
    assert own(registry) == set()
    box["text"] = "the prompt, edited in place"
    found = registry.problems(prompt_versions={"X_VERSION": "x-v1"})
    assert {p.code for p in found} - COVERAGE == {"fingerprint", "label_text"}
    gate = next(p for p in found if p.code == "fingerprint")
    assert rg.live_fingerprint(spec) in gate.text and registry.in_force("x").fingerprint in gate.text
    assert "Registration(" in gate.text and "bump the label" in gate.text


def test_a_new_version_with_a_new_label_is_clean_and_the_old_label_keeps_its_text() -> None:
    box: dict[str, Any] = {"text": "the prompt"}
    spec = agent(box)
    first = entry(spec, "x-v1", baseline=True)
    box.update(text="a better prompt", label="x-v2")
    second = entry(spec, "x-v2", at=AT + timedelta(days=1))
    assert own(lone(spec, first, second), labels={"X_VERSION": "x-v2"}) == set()
    assert rg.live_parts(spec)["t"].prompt_sha != first.parts["t"].prompt_sha


def test_a_new_entry_without_a_new_label_is_still_an_edit_in_place() -> None:
    box: dict[str, Any] = {"text": "the prompt"}
    spec = agent(box)
    first = entry(spec, "x-v1", baseline=True)
    box["text"] = "edited, and registered, but the label stayed"
    second = entry(spec, "x-v2", at=AT + timedelta(days=1))
    found = lone(spec, first, second).problems(prompt_versions={"X_VERSION": "x-v1"})
    label = [p for p in found if p.code == "label_text"]
    assert [p.subject for p in label] == ["x-v1"], "the prompt label names two texts; the schema label, untouched, names one"
    assert "prompt label 'x-v1' names 2 different texts" in label[0].text and "edited in place" in label[0].text
    assert {p.code for p in found} - COVERAGE == {"label_text"}, "the entry is there, so the gate itself is satisfied: the label is what is wrong"


def test_a_schema_edited_in_place_is_found_as_well() -> None:
    box: dict[str, Any] = {}
    spec = agent(box)
    first = entry(spec, "x-v1", baseline=True)
    box["schema"] = {**SCHEMA, "required": []}
    second = entry(spec, "x-v2", at=AT + timedelta(days=1))
    found = [p for p in lone(spec, first, second).problems(prompt_versions={"X_VERSION": "x-v1"}) if p.code == "label_text"]
    assert found and "schema label" in found[0].text and "names 2 different texts" in found[0].text


def test_a_model_or_an_effort_that_changes_is_a_new_version_but_not_an_edit_in_place() -> None:
    t = BuiltTask("t", "low", lambda: definition(), model="claude-haiku-5-5")
    spec = agent(tasks=(t,))
    first = entry(spec, "x-v1", baseline=True)
    moved = agent(tasks=(replace(t, effort="medium"),))
    assert "fingerprint" in own(lone(moved, first))
    second = entry(moved, "x-v2", at=AT + timedelta(days=1))
    assert own(lone(moved, first, second)) == set(), "the labels name the same texts: only the way they are asked changed"


def first_entry(**changes: Any) -> Registry:
    return with_(ledger=(replace(LEDGER[0], **changes), *LEDGER[1:]))


@pytest.mark.parametrize(("registry", "expected"), [
    (with_(ledger=(*LEDGER, replace(LEDGER[0], agent="ghost"))), {"orphan"}),
    (first_entry(version="Brief 8"), {"version_label"}),
    (first_entry(fingerprint="ag12"), {"fingerprint_form", "fingerprint"}),
    (first_entry(registered_at=datetime(2026, 10, 25)), {"registered_at"}),  # noqa: DTZ001 - a moment with no zone is the defect
    (first_entry(decided_by="claude"), {"decided_by"}),
    (first_entry(phase=" "), {"phase"}),
    (first_entry(reason="short"), {"reason"}),
    (first_entry(born_as="CHALLENGER"), {"born_as"}),
    (first_entry(baseline=False), {"born_as"}),
    (first_entry(parts={}), {"parts"}),
    (first_entry(parts={"context": Part("brief-v8", "xyz", "brief-v8", "b8cc54533409")}), {"sha", "label_text"}),
    (first_entry(parts={"context": Part("brief-v8", "f19c03954c60", "brief-v8", "B8CC54533409")}), {"sha", "label_text"}),
    (first_entry(reason="x" * 39), {"reason"}),
    (first_entry(reason="x" * 40), set()),
    (first_entry(phase="IA-1 "), set()),
], ids=["orphan", "version", "fingerprint", "zone", "decider", "phase", "reason", "champion-not-baseline", "baseline-not-champion", "no-parts", "sha",
        "schema-sha", "reason-39", "reason-40", "phase-spaced"])
def test_a_ledger_entry_that_is_not_well_formed_is_found(registry: Registry, expected: set[str]) -> None:
    assert codes(REGISTRY) == set()
    assert codes(registry) == expected


def test_two_entries_of_one_agent_are_ordered_unique_and_only_the_first_is_the_baseline() -> None:
    spec = agent()
    first = entry(spec, "x-v1", baseline=True)
    again = entry(spec, "x-v1", at=AT + timedelta(days=1))
    assert "duplicate_version" in own(lone(spec, first, again))
    same_moment = entry(spec, "x-v2", at=AT)
    assert "order" in own(lone(spec, first, same_moment))
    earlier = entry(spec, "x-v2", at=AT - timedelta(days=1))
    assert "order" in own(lone(spec, first, earlier))
    second_baseline = entry(spec, "x-v2", at=AT + timedelta(days=1), baseline=True)
    assert "baseline" in own(lone(spec, first, second_baseline))
    assert own(lone(spec, first, entry(spec, "x-v2", at=AT + timedelta(days=1)))) == set()


def test_a_moment_with_no_zone_is_said_and_does_not_stop_the_ordering_of_the_rest() -> None:
    spec = agent()
    first = entry(spec, "x-v1", at=datetime(2026, 11, 1, 12, 0), baseline=True)  # noqa: DTZ001 - the defect
    second = entry(spec, "x-v2", at=AT + timedelta(days=1))
    assert own(lone(spec, first, second)) == {"registered_at"}, "found, and not a crash for comparing a naive moment with an aware one"


def test_an_agent_has_one_name_a_task_each_and_a_model_or_a_tier() -> None:
    spec = agent()
    t = spec.tasks[0]
    assert "duplicate_agent" in codes(replace(lone(spec), agents=(spec, spec)), prompt_versions={"X_VERSION": "x-v1"})
    assert "agent_id" in own(lone(agent(name="Bad Name")))
    assert "tasks" in own(lone(agent(tasks=(t, t))))
    nothing = AgentSpec("x", "an agent that does nothing", ())
    assert "tasks" in codes(Registry(agents=(nothing,), planned=(), postponed=(), ledger=()), prompt_versions={})
    assert "task_runs_on" in own(lone(agent(tasks=(replace(t, tier=None),))))
    assert "task_runs_on" in own(lone(agent(tasks=(replace(t, model="claude-haiku-5-5"),))))
    assert "model" in own(lone(agent(tasks=(replace(t, tier=None, model="claude-haiku-9-9"),))))
    assert "tier" in own(lone(agent(tasks=(replace(t, tier="cheap"),))))  # type: ignore[arg-type]
    assert "effort" in own(lone(agent(tasks=(replace(t, effort="high"),))))  # type: ignore[arg-type]
    assert "contract" in own(lone(agent(contract="zz-v9")))
    assert "reads" in own(lone(agent(reads="everything")))
    assert own(lone(agent(contract="aa-v1", reads="stats"))) == set()
    assert own(lone(agent(reads="council_view"))) == set()


def test_an_agent_replaces_only_another_agent_the_code_has() -> None:
    spec = agent()
    assert "replaces" in own(lone(replace(spec, replaces="nobody")))
    assert "replaces" in own(lone(replace(spec, replaces=spec.agent))), "not itself"
    two = replace(agent(name="newer"), replaces=spec.agent)
    registry = replace(lone(spec), agents=(spec, two))
    assert "replaces" not in codes(registry, prompt_versions={"X_VERSION": "x-v1"})
    real = replace(REGISTRY, agents=tuple(replace(s, replaces="nobody") if s.agent == "claim_extractor" else s for s in AGENTS))
    assert "replaces" in codes(real), "and the real registry is held to it as well"


def test_a_definition_that_cannot_be_read_is_a_finding_and_not_a_crash() -> None:
    def broken() -> Definition:
        raise AttributeError("module 'fbi.ai.prompts' has no attribute 'X_SYSTEM'")

    spec = AgentSpec("x", "p", (BuiltTask("t", "low", broken, tier="bulk"),))
    registry = Registry(agents=(spec,), planned=(), postponed=(), ledger=())
    found = [p for p in registry.problems(prompt_versions={}) if p.code == "definition"]
    assert len(found) == 1 and "AttributeError" in found[0].text and "X_SYSTEM" in found[0].text
    assert "unregistered" not in {p.code for p in registry.problems(prompt_versions={})}, "nothing else is said of what cannot be read"


def test_the_entry_to_add_lists_the_tasks_by_name_with_their_labels_and_hashes() -> None:
    spec = next(s for s in AGENTS if s.agent == "post_match_reviewer")
    assert [t.task for t in spec.tasks] == ["narrative", "loss_review"], "declared in this order"
    text = rg.stub(spec, "pick-postmortem-v5")
    assert text.index('"loss_review"') < text.index('"narrative"'), "and listed by name"
    assert 'version="pick-postmortem-v5"' in text and f'fingerprint="{rg.live_fingerprint(spec)}"' in text and 'agent="post_match_reviewer"' in text
    parts = rg.live_parts(spec)["loss_review"]
    assert f'"loss_review": Part("{parts.prompt_version}", "{parts.prompt_sha}", "{parts.schema_version}", "{parts.schema_sha}"),' in text
    assert text.endswith("}),")


def test_a_prompt_the_code_declares_and_no_agent_uses_is_found() -> None:
    labels = rg.live_prompt_versions()
    assert codes(REGISTRY, prompt_versions=labels) == set()
    found = REGISTRY.problems(prompt_versions=labels | {"NEW_VERSION": "new-v1"})
    assert [(p.code, p.subject) for p in found] == [("prompt_unregistered", "NEW_VERSION")]
    assert "outside the registry" in found[0].text


def test_every_task_of_the_router_and_every_contract_has_an_agent_that_runs_or_will_run_it() -> None:
    assert codes(REGISTRY) == set()
    without = with_(agents=tuple(s for s in AGENTS if s.agent != "council"), ledger=tuple(r for r in LEDGER if r.agent != "council"))
    assert {"task_unserved", "contract_unwritten"} <= codes(without)
    served = {t.task for s in AGENTS for t in s.tasks} | {t.task for p in PLANNED for t in p.tasks}
    assert set(router.TASKS) - served == rg.UNSERVED_TASKS == {"owner_research"}
    assert set(OUTPUTS) == {s.contract for s in AGENTS if s.contract} | {p.contract for p in PLANNED}


def test_the_prompt_the_code_declares_is_the_prompt_of_a_task_and_not_its_schema() -> None:
    t = BuiltTask("t", "low", lambda: definition(label="x-v1", schema_label="aa-v1"), tier="bulk")
    registry = lone(agent(tasks=(t,)))
    assert own(registry) == set()
    assert own(registry, labels={"Y_VERSION": "aa-v1"}) == {"prompt_unregistered"}, "a schema label is not a prompt"


def test_a_built_agent_counts_for_the_contract_it_answers_in() -> None:
    registry = lone(agent(contract="aa-v1"))
    unwritten = {p.subject for p in registry.problems(prompt_versions={}) if p.code == "contract_unwritten"}
    assert unwritten == set(OUTPUTS) - {"aa-v1"}


def plan(**kw: Any) -> PlannedAgent:
    base = PlannedAgent("scout", "scout-v1", "p", 4, "aa-v1", (PlannedTask("evaluation", "claude-haiku-5-5", "medium", "scout-assess-v1"),),
                        reads="stats")
    return replace(base, **kw)


def planned_with(**kw: Any) -> Registry:
    return with_(planned=(*tuple(p for p in PLANNED if p.agent != "scout"), plan(**kw)))


@pytest.mark.parametrize(("change", "code"), [
    ({"agent": "Match Agent"}, "agent_id"),
    ({"version": "scout-1"}, "version_label"),
    ({"phase": 1}, "phase"),
    ({"phase": 11}, "phase"),
    ({"contract": "zz-v9"}, "contract"),
    ({"contract": "mcp-v1"}, "contract"),
    ({"reads": "the-world"}, "reads"),
    ({"replaces": "scout-v0"}, "replaces"),
    ({"tasks": ()}, "tasks"),
    ({"tasks": (PlannedTask("evaluation", "claude-haiku-5-5", "medium", "scout-assess-v1"),) * 2}, "tasks"),
    ({"tasks": (PlannedTask("dreaming", "claude-haiku-5-5", "medium", "scout-assess-v1"),)}, "task"),
    ({"tasks": (PlannedTask("evaluation", "claude-sonnet-5-5", "medium", "scout-assess-v1"),)}, "model"),
    ({"tasks": (PlannedTask("evaluation", "claude-haiku-9-9", "medium", "scout-assess-v1"),)}, "model"),
    ({"tasks": (PlannedTask("evaluation", "claude-haiku-5-5", "low", "scout-assess-v1"),)}, "effort"),
    ({"tasks": (PlannedTask("evaluation", "claude-haiku-5-5", "medium", "assess"),)}, "prompt_label"),
])
def test_a_plan_that_the_router_the_contracts_or_the_price_list_cannot_run_is_found(change: dict[str, Any], code: str) -> None:
    assert codes(planned_with()) == set(), "the same plan without a defect is clean"
    assert code in codes(planned_with(**change))


def test_two_planned_agents_never_share_a_prompt_label() -> None:
    other = replace(plan(), agent="other", version="other-v1")
    assert "planned_label" in codes(with_(planned=(*PLANNED, plan(), other)))


def test_the_phases_of_the_plan_run_from_the_second_to_the_tenth() -> None:
    assert codes(planned_with(phase=2)) == set()
    assert codes(planned_with(phase=10)) == set()
    assert codes(planned_with(phase=0)) == {"phase"}


def test_a_planned_agent_that_has_become_code_must_move_to_the_ledger() -> None:
    labels = rg.live_prompt_versions()
    assert [p for p in REGISTRY.problems(prompt_versions=labels) if p.code == "planned_is_built"] == [], "the plan of today builds nothing the code has"
    fake = with_(planned=(*PLANNED, plan()))
    said = fake.problems(prompt_versions=labels | {"SCOUT_ASSESS_VERSION": "scout-assess-v1"})
    assert [(p.code, p.subject) for p in said if p.code == "planned_is_built"] == [("planned_is_built", "scout/scout-v1/evaluation")]
    registered = replace(LEDGER[0], agent="scout", version="scout-v1")
    assert "planned_is_built" in codes(with_(planned=(*PLANNED, plan()), ledger=(*LEDGER, registered)))


def test_a_postponed_agent_with_code_or_a_phase_is_not_postponed() -> None:
    assert codes(with_(postponed=(*POSTPONED, PostponedAgent("match", "p", "a gate")))) == {"postponed_is_built"}
    assert codes(with_(postponed=(*POSTPONED, PostponedAgent("brief", "p", "a gate")))) == {"postponed_is_built"}, "built, and with no plan"
    assert codes(with_(postponed=(*POSTPONED, PostponedAgent("Player Two", "p", "a gate")))) == {"postponed"}
    assert codes(with_(postponed=(*POSTPONED, PostponedAgent("coach", "p", " ")))) == {"postponed"}


def test_a_built_agent_that_changes_its_effort_without_an_entry_fails_the_gate() -> None:
    spec = AGENTS[0]
    moved = replace(spec, tasks=(replace(spec.tasks[0], effort="medium"),))
    found = [p for p in with_(agents=(moved, *AGENTS[1:])).problems() if p.code == "fingerprint"]
    assert [p.subject for p in found] == ["brief"]
    assert "ag4aefd93b43" in found[0].text and rg.live_fingerprint(moved) in found[0].text


def test_a_problem_reads_as_its_code_its_subject_and_its_text() -> None:
    assert str(rg.Problem("reason", "brief/brief-v8", "a registration without a reason")) == "[reason] brief/brief-v8: a registration without a reason"


# -- the identity of a task, from the registry -----------------------------------------------------------------------------------------

def pinned() -> tuple[AgentSpec, Registry]:
    t = BuiltTask("t", "medium", lambda: definition(label="x-v1", schema_label="aa-v1"), model="claude-haiku-5-5")
    spec = agent(tasks=(t,), contract="aa-v1", reads="match")
    return spec, lone(spec)


def identity(registry: Registry, **kw: Any) -> Any:
    args: dict[str, Any] = {"workspace": "lab", "input_version": "package-v1", "input_hash": HASH, "pass_kind": "pre", "fixture_id": 7,
                            "candidates": ("c2", "c1")} | kw
    return registry.identity_for("x", "t", **args)


def test_the_identity_of_a_task_is_the_registrys_row_and_nothing_written_by_hand() -> None:
    _, registry = pinned()
    i = identity(registry)
    assert (i.agent, i.agent_version, i.prompt_version, i.schema_version, i.model, i.effort) == (
        "x", "x-v1", "x-v1", "aa-v1", "claude-haiku-5-5", "medium")
    assert (i.workspace, i.input_version, i.input_hash, i.pass_kind, i.fixture_id, i.candidates) == (
        "lab", "package-v1", HASH, "pre", 7, ("c1", "c2")), "the candidates are sorted"
    assert i.key == idem_key(i)


def test_the_key_moves_when_the_registry_says_the_agent_is_another_and_only_then() -> None:
    box: dict[str, Any] = {"label": "x-v1", "schema_label": "aa-v1"}
    t = BuiltTask("t", "medium", lambda: definition(**box), model="claude-haiku-5-5")
    spec = agent(tasks=(t,))
    first = entry(spec, "x-v1", baseline=True)
    registry = lone(spec, first)
    before = identity(registry)
    assert identity(registry).key == before.key, "the same registry, the same key"
    box.update(text="a better prompt", label="x-v2")
    after = identity(lone(spec, first, entry(spec, "x-v2", at=AT + timedelta(days=1))))
    assert changed_fields(before, after) == ("agent_version", "prompt_version")
    moved = agent(tasks=(replace(t, effort="low"),))
    assert changed_fields(identity(lone(moved, entry(moved, "x-v1", baseline=True))), identity(registry)) == ("effort",)
    box["schema"] = {**SCHEMA, "required": []}
    box.update(schema_label="aa-v2", label="x-v1", text="the prompt")
    third = identity(lone(spec, first, entry(spec, "x-v3", at=AT + timedelta(days=2))))
    assert "schema_version" in changed_fields(before, third)


def test_an_arm_that_judges_with_another_model_changes_the_model_and_nothing_else() -> None:
    _, registry = pinned()
    plain, arm = identity(registry), identity(registry, model="claude-sonnet-5-5")
    assert changed_fields(plain, arm) == ("model",)
    assert arm.model == "claude-sonnet-5-5"


def test_the_workspace_input_and_candidates_belong_to_the_call_not_to_the_registry() -> None:
    _, registry = pinned()
    base = identity(registry)
    assert changed_fields(base, identity(registry, workspace="production")) == ("workspace",)
    assert changed_fields(base, identity(registry, input_hash="b" * 64)) == ("input_hash",)
    assert changed_fields(base, identity(registry, input_version="package-v2")) == ("input_version",)
    assert changed_fields(base, identity(registry, pass_kind="final")) == ("pass_kind",)
    assert changed_fields(base, identity(registry, fixture_id=8)) == ("fixture_id",)
    assert changed_fields(base, identity(registry, candidates=("c1",))) == ("candidates",)
    assert changed_fields(base, identity(registry, candidates=("c1", "c2"))) == (), "the order the candidates come in is not a question"


def test_a_task_the_registry_cannot_name_is_refused_with_the_reason() -> None:
    _, registry = pinned()
    with pytest.raises(RegistryError, match="'ghost' is not an agent the code has"):
        registry.identity_for("ghost", "t", workspace="lab", input_version="p-v1", input_hash=HASH, pass_kind="pre", fixture_id=1)
    with pytest.raises(RegistryError, match="does not run a task 'u'"):
        registry.identity_for("x", "u", workspace="lab", input_version="p-v1", input_hash=HASH, pass_kind="pre", fixture_id=1)
    with pytest.raises(RegistryError, match="no entry in the ledger"):
        replace(registry, ledger=()).identity_for("x", "t", workspace="lab", input_version="p-v1", input_hash=HASH, pass_kind="pre", fixture_id=1)
    with pytest.raises(RegistryError, match="not in the price list"):
        identity(registry, model="claude-haiku-9-9")
    tier = BuiltTask("t", "low", lambda: definition(), tier="bulk")
    old = lone(agent(tasks=(tier,)))
    with pytest.raises(RegistryError, match=r"runs on a tier \(bulk\), not on a model"):
        identity(old)
    assert identity(old, model="claude-haiku-5-5").model == "claude-haiku-5-5", "the caller says which model the tier is set to"


def test_the_real_registry_gives_the_identity_of_a_task_of_the_ai_that_runs_today() -> None:
    i = REGISTRY.identity_for("extractor", "extraction", workspace="production", input_version="search-v1", input_hash=HASH, pass_kind="first",
                              fixture_id=3, model="claude-haiku-5-5")
    assert (i.agent, i.agent_version, i.prompt_version, i.schema_version, i.effort) == ("extractor", "extract-v1", "extract-v1", "extract-v1", "low")


# -- the names of the promotions ------------------------------------------------------------------------------------------------------

def test_a_promotion_is_named_by_the_agent_its_version_and_the_versions_it_reads() -> None:
    assert rg.promotion_name("council", "council-v1", ["match-v1"]) == "council@council-v1+match-v1"
    assert rg.promotion_name("match", "match-v1") == "match@match-v1"
    assert rg.promotion_name("council", "council-v1", ["stats-v1", "match-v1", "match-v1"]) == "council@council-v1+match-v1+stats-v1", "sorted, once each"
    assert rg.promotion_name("post_match_reviewer", "pmr-v1") == "post_match_reviewer@pmr-v1"
    assert rg.promotion_name("council", "council-v123", ["match-v100"]) == "council@council-v123+match-v100", "up to three digits of a version"


def test_a_name_of_a_promotion_reads_back() -> None:
    parsed = rg.parse_promotion_name("council@council-v1+match-v1+stats-v1")
    assert parsed == rg.PromotionName("council", "council-v1", ("match-v1", "stats-v1"))
    assert str(parsed) == "council@council-v1+match-v1+stats-v1"
    assert rg.parse_promotion_name("match@match-v1") == rg.PromotionName("match", "match-v1", ())
    assert rg.parse_promotion_name(rg.promotion_name("learning_analyst", "la-v1")).agent == "learning_analyst"


@pytest.mark.parametrize("name", [
    "", "council", "council@", "@council-v1", "Council@council-v1", "council@council", "council@council-v0", "council@council-v1000",
    "council@council-v1+", "council@council-v1+match", "council@council-v1 +match-v1", "council@council-v1+match-v1,stats-v1",
    "council@@council-v1", "coun cil@council-v1", "council@council-v1\n", "council;drop@council-v1", "llm", "council@council-v1+MATCH-v1",
    "council_@council-v1", "_council@council-v1", "coun__cil@council-v1", "council@council-v1+match-v1+", "council@council-v1++match-v1",
])
def test_a_name_that_is_not_an_agent_at_a_version_is_refused(name: str) -> None:
    with pytest.raises(RegistryError):
        rg.parse_promotion_name(name)
    assert rg.PROMOTION_NAME.fullmatch(name) is None


def test_a_name_is_refused_before_it_is_built() -> None:
    with pytest.raises(RegistryError):
        rg.promotion_name("Council", "council-v1")
    with pytest.raises(RegistryError):
        rg.promotion_name("council", "council-v1", ["match"])


# -- what the administrator sees ------------------------------------------------------------------------------------------------------

def test_the_snapshot_lists_what_is_built_then_what_is_planned_then_what_is_postponed() -> None:
    rows = REGISTRY.snapshot()
    assert [(r["agent"], r["status"]) for r in rows] == (
        [(s.agent, "built") for s in AGENTS] + [(p.agent, "planned") for p in PLANNED])
    assert ("player", "built") in [(r["agent"], r["status"]) for r in rows], "IA-017: the Player Agent is built, and nothing is postponed"
    json.dumps(rows)  # plain data, all of it
    built = {r["agent"]: r for r in rows if r["status"] == "built"}
    assert all(r["in_sync"] for r in built.values())
    assert built["brief"]["version"] == "brief-v8" and built["brief"]["retire_phase"] == 9 and built["brief"]["next_version"] is None
    assert built["learning_analyst"]["next_version"] is None and built["la"]["replaces"] == "learning_analyst" and built["la"]["version"] == "la-v1"
    assert built["reviewer"]["tasks"][1] == {"task": "review_final", "prompt_version": "review-v2", "schema_version": "review-v2", "model": None,
                                             "tier": "final", "effort": "medium"}
    assert built["council"]["tasks"][1] == {"task": "escalation", "prompt_version": "council-opus-v1", "schema_version": "cd-v1",
                                            "model": "claude-opus-5-5", "tier": None, "effort": "medium"}
    assert built["pmr"]["replaces"] == "post_match_reviewer" and built["pmr"]["born_as"] == "CHALLENGER" and built["pmr"]["reads"] == "settled_match"


def test_the_snapshot_shows_the_version_in_force_and_the_versions_before_it() -> None:
    box: dict[str, Any] = {"text": "the prompt"}
    spec = agent(box)
    first = entry(spec, "x-v1", baseline=True)
    box.update(text="a better prompt", label="x-v2")
    second = entry(spec, "x-v2", at=AT + timedelta(days=1))
    row = lone(spec, first, second).snapshot()[0]
    assert (row["version"], row["fingerprint"], row["born_as"], row["baseline"]) == ("x-v2", second.fingerprint, "CHALLENGER", False)
    assert row["registered_at"] == (AT + timedelta(days=1)).isoformat()
    assert row["history"] == ["x-v1", "x-v2"] and row["in_sync"] is True
    assert row["tasks"] == [{"task": "t", "prompt_version": "x-v2", "schema_version": "x-v2", "model": None, "tier": "bulk", "effort": "low"}]


def test_the_snapshot_says_when_the_code_has_moved_away_from_its_entry() -> None:
    spec = AGENTS[0]
    moved = replace(spec, tasks=(replace(spec.tasks[0], effort="medium"),))
    rows = with_(agents=(moved, *AGENTS[1:])).snapshot()
    assert [r["in_sync"] for r in rows[:2]] == [False, True]
    assert replace(REGISTRY, ledger=()).snapshot()[0]["version"] is None
    assert replace(REGISTRY, ledger=()).snapshot()[0]["in_sync"] is False
