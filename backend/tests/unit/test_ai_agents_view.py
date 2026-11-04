"""The agents in the Admin Console (plan IA, phase 1): the registry as the page reads it, and the vocabularies the page counts by.

The registry is the code's own: what the page shows of it is what ``REGISTRY.snapshot()`` says, and a registry that disagrees with the code, or
cannot be read at all, is a finding on the page and not a failure of it. The states of a task, the statuses of an attempt and the rules of the
audit are lists the service counts by; they are held here to the migration and to the audit they come from, so none of them can drift.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from fbi.ai.agents import registry as agents
from fbi.api.contracts.ai_agents import RegistryProblem
from fbi.api.services import ai_agents
from fbi.intel import leakage

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0111_ia_phase1_agent_tasks_runs_state.py"


def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0111_for_the_view", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_agent_of_the_code_is_on_the_page_in_the_order_of_the_code_then_the_planned_then_the_postponed() -> None:
    views, problems = ai_agents.registry()
    assert problems == [], "the code as it is agrees with its registry"
    assert [(v.agent, v.status) for v in views] == (
        [(a.agent, "built") for a in agents.AGENTS] + [(p.agent, "planned") for p in agents.PLANNED]
        + [(p.agent, "postponed") for p in agents.POSTPONED])


def test_a_built_agent_shows_the_version_in_force_and_that_the_code_is_the_one_registered() -> None:
    views, _ = ai_agents.registry()
    built = {v.agent: v for v in views if v.status == "built"}
    assert set(built) == {a.agent for a in agents.AGENTS}
    for spec in agents.AGENTS:
        view = built[spec.agent]
        entry = agents.REGISTRY.in_force(spec.agent)
        assert view.version == entry.version and view.fingerprint == entry.fingerprint
        assert re.fullmatch(r"ag[0-9a-f]{10}", view.fingerprint or "")
        assert view.in_sync is True, f"{spec.agent}: the fingerprint of the code that runs is the one the ledger holds"
        if entry.baseline:
            assert view.baseline is True and view.born_as == "CHAMPION", "the agents that already ran are recorded as the baseline, born champion"
        else:
            assert view.baseline is False and view.born_as == "CHALLENGER", "an agent built later is born a challenger"
        assert view.registered_at == entry.registered_at
        assert view.history == [r.version for r in agents.REGISTRY.history(spec.agent)]
        assert view.purpose == spec.purpose and view.contract == spec.contract and view.reads == spec.reads
        assert [t.task for t in view.tasks] == [t.task for t in spec.tasks]
        assert view.retire_phase == spec.retire_phase


def test_a_task_says_which_prompt_which_schema_and_what_it_runs_on() -> None:
    views, _ = ai_agents.registry()
    reviewer = next(v for v in views if v.agent == "reviewer")
    by_task = {t.task: t for t in reviewer.tasks}
    assert set(by_task) == {"review_analysis", "review_final"}
    assert (by_task["review_analysis"].tier, by_task["review_final"].tier) == ("analysis", "final")
    assert by_task["review_analysis"].model is None, "the old route runs on the deployment's setting, not on a model of its own"
    assert by_task["review_analysis"].prompt_version == "review-v2" and by_task["review_analysis"].schema_version == "review-v2"
    assert by_task["review_final"].effort == "medium"


def test_a_planned_agent_says_in_which_phase_it_is_built_and_what_it_takes_over_from() -> None:
    views, _ = ai_agents.registry()
    planned = {v.agent: v for v in views if v.status == "planned"}
    assert "match" not in planned, "the Match Agent is built (phase 3): it is on the page as built, with the version in force"
    assert "statistics" not in planned and "stats" not in planned, "the Statistics Agent is built (phase 4): it is on the page as built"
    assert planned == {}, "phases 2 to 5 are built: every agent of the plan is on the page as built (only the postponed one is left)"
    built = {v.agent: v for v in views if v.status == "built"}
    assert {t.task: t.model for t in built["council"].tasks} == {"council": "claude-sonnet-5-5", "escalation": "claude-opus-5-5"}
    assert built["learning_analyst"].next_version is None and built["la"].version == "la-v1" and built["la"].replaces == "learning_analyst"
    assert built["pmr"].version == "pmr-v1" and built["pmr"].replaces == "post_match_reviewer" and built["pmr"].born_as == "CHALLENGER"
    assert (built["match"].version, built["match"].contract, built["match"].reads, built["match"].born_as) == ("match-v1", "aa-v1", "match", "CHALLENGER")
    assert built["match"].next_version is None and [t.task for t in built["match"].tasks] == ["context", "evaluation"]
    assert (built["stats"].version, built["stats"].contract, built["stats"].reads, built["stats"].born_as) == ("stats-v1", "aa-v1", "stats", "CHALLENGER")
    assert [(t.task, t.model, t.prompt_version) for t in built["stats"].tasks] == [("evaluation", "claude-haiku-5-5", "stats-assess-v1")]


def test_the_player_agent_is_on_the_page_as_postponed_with_the_gate_that_would_wake_it() -> None:
    views, _ = ai_agents.registry()
    (player,) = [v for v in views if v.status == "postponed"]
    assert player.agent == "player" and player.gate and "F-Player" in player.gate
    assert player.version is None and player.tasks == []


class Unreadable:
    def snapshot(self) -> list[dict[str, Any]]:
        raise RuntimeError("the definition of a prompt cannot be read")

    def problems(self) -> list[agents.Problem]:
        return []


def test_a_registry_that_cannot_be_read_is_one_problem_on_the_page_and_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_agents, "REGISTRY", Unreadable())
    views, problems = ai_agents.registry()
    assert views == []
    assert problems == [RegistryProblem(code="unreadable", subject="registry", text="RuntimeError: the definition of a prompt cannot be read")]


def test_what_cannot_be_read_is_said_in_a_short_line(monkeypatch: pytest.MonkeyPatch) -> None:
    class Wordy(Unreadable):
        def snapshot(self) -> list[dict[str, Any]]:
            raise RuntimeError("x" * 1000)

    monkeypatch.setattr(ai_agents, "REGISTRY", Wordy())
    _, problems = ai_agents.registry()
    assert len(problems[0].text) == 300 and problems[0].text.startswith("RuntimeError: xxx")


def test_every_way_the_registry_disagrees_with_the_code_reaches_the_page_as_the_registry_words_it(monkeypatch: pytest.MonkeyPatch) -> None:
    found = [agents.Problem("prompt_label", "brief/context", "the label of the prompt names two texts"),
             agents.Problem("fingerprint", "reviewer", "the code is not the one registered")]

    class Disagrees(Unreadable):
        def snapshot(self) -> list[dict[str, Any]]:
            return []

        def problems(self) -> list[agents.Problem]:
            return found

    monkeypatch.setattr(ai_agents, "REGISTRY", Disagrees())
    views, problems = ai_agents.registry()
    assert views == [] and problems == [RegistryProblem(code=p.code, subject=p.subject, text=p.text) for p in found]


# ── the vocabularies the page counts by ───────────────────────────────────────────────────────────────────────────────────────────

def test_the_states_of_a_task_and_the_statuses_of_an_attempt_are_those_the_database_checks() -> None:
    m = migration()
    assert ai_agents.TASK_STATES == m.TASK_STATES
    assert ai_agents.RUN_STATUSES == m.RUN_STATUSES


def test_a_task_is_open_until_it_ends() -> None:
    assert ai_agents.OPEN_STATES == ("planned", "queued", "running")
    assert set(ai_agents.OPEN_STATES) <= set(ai_agents.TASK_STATES)
    closed = set(ai_agents.TASK_STATES) - set(ai_agents.OPEN_STATES)
    assert closed == {"done", "failed", "skipped", "expired"}, "the four endings, the ones that must point at an attempt"


def test_the_audit_the_page_shows_is_the_part_of_the_plans_list_the_audit_already_has() -> None:
    assert ai_agents.PLAN_AUDIT_RULES == ("slice_known", "agent_known", "review_known", "shadow_review_known", "memory_known")
    assert set(ai_agents.AUDIT_RULES) <= set(leakage.RULE_NAMES), "a rule is shown only when the audit has it"
    assert tuple(r for r in ai_agents.PLAN_AUDIT_RULES if r in leakage.RULE_NAMES) == ai_agents.AUDIT_RULES, "in the order of the plan"
    assert "slice_known" in ai_agents.AUDIT_RULES, "phase 1 audits the states it writes"
    assert ai_agents.AUDIT_RULES == ("slice_known", "agent_known", "review_known", "shadow_review_known"), "phase 3 audits the agents and the shadow"


def test_the_window_is_a_week_and_the_lists_of_a_match_are_bounded() -> None:
    assert ai_agents.DAYS == 7, "the days Gate A asks for"
    assert 10 <= ai_agents.HISTORY <= 200 and ai_agents.DECISIONS >= 5
