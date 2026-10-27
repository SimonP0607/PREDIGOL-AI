"""Migration 0111 (Plan Maestro IA, phase 1): the queue of the agents, their runs and the state of a match, on a real database.

What the database refuses by itself is what no code has to remember: a task whose question changes, a state that skips a step, a fourth
start, a question paid twice, a row of the record that is rewritten. Each rule is shown here by the row that breaks it - and by the
constraint that says so, so that a statement refused for another reason (a typo, a missing column) fails the test instead of passing it.
The vocabularies are read back out of the constraints the database holds and held equal to the code's.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal
from typing import Any, get_args

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai import idempotency, router
from fbi.ai.agents.registry import REGISTRY, BuiltTask
from fbi.ai.contracts import base, mcp
from fbi.ai.contracts.assessment import CANDIDATES_MAX
from tests.integration.agent_tables import (
    ABSTAIN,
    HASH,
    INVALID,
    NOW,
    OTHER,
    UNPAID,
    columns_of,
    insert,
    key,
    match_values,
    refuses,
    run_values,
    shaped,
    task_values,
    update,
)
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

STATES = ("planned", "queued", "running", "done", "failed", "skipped", "expired")
LEGAL = frozenset({
    ("planned", "queued"), ("planned", "skipped"), ("planned", "expired"),
    ("queued", "running"), ("queued", "skipped"), ("queued", "expired"),
    ("running", "done"), ("running", "failed"), ("running", "expired"), ("running", "queued"), ("running", "skipped"),
    ("failed", "planned"), ("skipped", "planned"), ("expired", "planned"),
})
"""The lines the plan draws (section 18) and the retry of a transport failure (running back to queued): nothing else."""


# ── the vocabularies are the code's ──────────────────────────────────────────────────────────────────────────────────────────────

def lists_of(db: psycopg.Connection[Any], table: str) -> dict[str, set[str]]:
    """Every ``column IN (...)`` the CHECK constraints of a table hold, as the database stores it, by column."""
    found: dict[str, set[str]] = {}
    rows = db.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE contype = 'c' AND conrelid = %s::regclass", (table,)).fetchall()
    for (definition,) in rows:
        for column, body in re.findall(r"\(?(\w+) = ANY \(ARRAY\[((?:'[^']*'::text(?:, )?)+)\]\)", definition):
            found.setdefault(column, set()).update(re.findall(r"'([^']*)'::text", body))
    return found


def patterns_of(db: psycopg.Connection[Any], table: str) -> dict[str, set[str]]:
    """Every ``column ~ '...'`` the CHECK constraints of a table hold, by column."""
    found: dict[str, set[str]] = {}
    rows = db.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE contype = 'c' AND conrelid = %s::regclass", (table,)).fetchall()
    for (definition,) in rows:
        for column, pattern in re.findall(r"\(?(\w+) ~ '((?:[^']|'')*)'::text", definition):
            found.setdefault(column, set()).add(pattern.replace("''", "'"))
    return found


def test_the_database_admits_the_vocabularies_of_the_code(db: psycopg.Connection[Any]) -> None:
    tasks = {t.task for spec in REGISTRY.agents for t in spec.tasks} | {t.task for plan in REGISTRY.planned for t in plan.tasks}
    tasks |= set(router.TASKS)
    runs, queue, state, promotions = (lists_of(db, t) for t in ("ai.agent_runs", "ai.agent_tasks", "ai.match_runs", "intel.promotions"))
    assert runs["task_kind"] == queue["task_kind"] == tasks
    assert runs["pass_kind"] == queue["pass_kind"] == state["pass_kind"] == set(idempotency.PASS_KINDS) == set(get_args(mcp.PassKind))
    assert queue["workspace"] == set(idempotency.WORKSPACES)
    assert queue["effort"] == runs["effort"] == set(idempotency.EFFORTS)
    assert queue["state"] == set(STATES)
    assert runs["status"] == {"ok", "invalid", "timeout", "abstain", "skipped", "expired", "budget_skip"}
    assert queue["run_kind"] == {"live", "shadow", "replay"}
    assert runs["run_kind"] == {"live", "shadow", "replay", "battery"}
    assert state["run_kind"] == {"live", "shadow", "replay"}
    assert promotions["entity"] == {"calibrator", "market_edge", "selection_rule", "model", "agent"}
    assert promotions["market_key"] == set(base.FAMILIES), "an agent promotion is about one family, and only the families of the contracts"
    roles = {"CHAMPION", "CHALLENGER", "RETIRED", "REJECTED", "VALIDATED", "NOT_VALIDATED"}
    assert promotions["to_role"] == promotions["from_role"] == roles


def test_the_database_names_things_as_the_code_does(db: psycopg.Connection[Any]) -> None:
    queue, runs, state = (patterns_of(db, t) for t in ("ai.agent_tasks", "ai.agent_runs", "ai.match_runs"))
    for column in ("agent", "agent_version", "prompt_version", "schema_version", "model", "input_version", "router_version"):
        assert queue[column] == {idempotency.NAME.pattern}, column
    for column in ("agent", "agent_version", "prompt_version", "schema_version", "model", "router_version"):
        assert runs[column] == {idempotency.NAME.pattern}, column
    assert state["state_version"] == state["package_version"] == {idempotency.NAME.pattern}
    for column in ("idem_key", "package_hash"):
        assert queue[column] == {idempotency.SHA256.pattern}, column
    for column in ("idem_key", "package_hash", "slice_hash"):
        assert runs[column] == {idempotency.SHA256.pattern}, column
    assert state["package_hash"] == {idempotency.SHA256.pattern}
    assert queue["input_hash"] == {idempotency.SHA256.pattern}


def test_every_task_the_registry_can_run_is_a_question_the_queue_takes(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The key, the batch name and the versions the CODE makes are the ones the database's CHECKs were written for."""
    tier_models = {"bulk": "claude-haiku-5-5", "analysis": "claude-sonnet-5-5", "final": "claude-opus-5-5"}  # what the old route's tiers resolve to

    def model_of(built: BuiltTask) -> str:
        if built.model is not None:
            return str(built.model)
        assert built.tier is not None, "a task names a model or a tier"
        return tier_models[built.tier]

    made = 0
    for spec in REGISTRY.agents:
        for built in spec.tasks:
            made += 1
            identity = REGISTRY.identity_for(spec.agent, built.task, workspace="production", input_version="package-v1", input_hash=HASH,
                                             pass_kind="first", fixture_id=seed.fixture_id, candidates=("c2", "c1"),
                                             model=model_of(built))
            idem = idempotency.idem_key(identity)
            insert(db, "ai.agent_tasks", task_values(
                seed, made, idem_key=idem, custom_id=idempotency.custom_id(idem), agent=identity.agent, agent_version=identity.agent_version,
                prompt_version=identity.prompt_version, schema_version=identity.schema_version, model=identity.model, effort=identity.effort,
                input_version=identity.input_version, input_hash=identity.input_hash, pass_kind=identity.pass_kind,
                candidates=list(identity.candidates), task_kind=built.task, router_version=router.VERSION))
    assert made >= 8, "the six agents of today run eight tasks between them"
    assert scalar(db.execute("SELECT count(*) FROM ai.agent_tasks")) == made


@pytest.mark.parametrize(("candidates", "expected"), [
    ([], True), (["c1"], True), (["c12", "c1"], True), ([f"c{i}" for i in range(1, 13)], True), ([f"c{i}" for i in range(1, 14)], False),
    (["c1", "c1"], False), (["C1"], False), (["c"], False), (["c1000"], False), (["x1"], False), ([" c1"], False), (["c1", ""], False),
    (["c1", None], False), (["c0"], True), (["c999"], True),
])
def test_the_selections_of_a_task_are_named_as_the_package_names_them(db: psycopg.Connection[Any], candidates: list[str | None],
                                                                     expected: bool) -> None:
    def code_accepts() -> bool:
        names = [c for c in candidates if c is not None]
        return (len(names) == len(candidates) and len(candidates) <= CANDIDATES_MAX and len(set(names)) == len(names)
                and all(base.CANDIDATE.fullmatch(c) for c in names))

    assert scalar(db.execute("SELECT ai.candidates_ok(%s::text[])", (candidates,))) is expected
    assert code_accepts() is expected, "the database and the contracts must agree on every one"


def test_a_missing_list_of_candidates_is_not_a_list_of_none(db: psycopg.Connection[Any]) -> None:
    assert scalar(db.execute("SELECT ai.candidates_ok(NULL)")) is False


# ── the queue ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_task_goes_through_the_queue_and_its_reservation_comes_and_goes_by_itself(db: psycopg.Connection[Any], seed: Seed) -> None:
    task = insert(db, "ai.agent_tasks", task_values(seed))

    def seen() -> tuple[Any, ...]:
        found = db.execute("SELECT state, attempts, reserved_usd FROM ai.agent_tasks WHERE id = %s", (task,)).fetchone()
        assert found is not None
        return tuple(found)

    assert seen() == ("planned", 0, Decimal(0)), "a task that waits to be queued reserves nothing"
    update(db, "ai.agent_tasks", task, state="queued", queued_at=NOW)
    assert seen() == ("queued", 0, Decimal("0.031000"))
    update(db, "ai.agent_tasks", task, state="running", started_at=NOW + timedelta(seconds=1), attempts=1)
    assert seen() == ("running", 1, Decimal("0.031000"))
    run = insert(db, "ai.agent_runs", run_values(seed))
    update(db, "ai.agent_tasks", task, state="done", finished_at=NOW + timedelta(seconds=4), last_run_id=run)
    assert seen() == ("done", 1, Decimal(0)), "the reservation went with the state: nothing had to release it"


def test_a_task_that_travels_in_a_batch_reserves_nothing_because_its_item_carries_the_estimate(db: psycopg.Connection[Any],
                                                                                              seed: Seed) -> None:
    plain = insert(db, "ai.agent_tasks", task_values(seed, 1, state="queued", queued_at=NOW))
    in_batch = insert(db, "ai.agent_tasks", task_values(seed, 2, state="queued", queued_at=NOW, batch_id=41, est_cost_usd=Decimal("0.5")))
    running = insert(db, "ai.agent_tasks", task_values(seed, 3, state="running", queued_at=NOW, started_at=NOW, attempts=1,
                                                       est_cost_usd=Decimal("0.2")))
    waiting = insert(db, "ai.agent_tasks", task_values(seed, 4, est_cost_usd=Decimal("1.0")))
    reserved = dict(db.execute("SELECT id, reserved_usd FROM ai.agent_tasks WHERE id = ANY(%s)", ([plain, in_batch, running, waiting],)).fetchall())
    assert reserved == {plain: Decimal("0.031"), in_batch: Decimal(0), running: Decimal("0.2"), waiting: Decimal(0)}
    total = scalar(db.execute("SELECT sum(reserved_usd) FROM ai.agent_tasks WHERE workspace = 'production' AND fixture_id = %s", (seed.fixture_id,)))
    assert total == Decimal("0.231"), "what the budget adds to the month's spend"
    update(db, "ai.agent_tasks", in_batch, batch_id=None)
    assert scalar(db.execute("SELECT reserved_usd FROM ai.agent_tasks WHERE id = %s", (in_batch,))) == Decimal("0.5"), "the estimate comes back by itself"


def test_the_reservation_is_generated_and_nobody_writes_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    with refuses(db, psycopg.errors.GeneratedAlways):
        insert(db, "ai.agent_tasks", task_values(seed, reserved_usd=Decimal(0)))
    task = insert(db, "ai.agent_tasks", task_values(seed))
    with refuses(db, psycopg.errors.GeneratedAlways):
        update(db, "ai.agent_tasks", task, reserved_usd=Decimal(0))


def test_a_new_task_waits_to_be_queued_with_no_attempt_and_no_run(db: psycopg.Connection[Any], seed: Seed) -> None:
    task = insert(db, "ai.agent_tasks", task_values(seed))
    found = db.execute("SELECT state, attempts, queued_at, started_at, finished_at, batch_id, last_run_id FROM ai.agent_tasks WHERE id = %s", (task,)).fetchone()
    assert found == ("planned", 0, None, None, None, None, None)


def test_the_state_moves_only_along_the_lines_the_plan_draws(db: psycopg.Connection[Any], seed: Seed) -> None:
    run = insert(db, "ai.agent_runs", run_values(seed, 900))
    n = 0
    for origin in STATES:
        for target in STATES:
            if origin == target:
                continue
            n += 1
            change = shaped(target, run)
            if target in ("planned", "queued", "running"):
                change["finished_at"] = None
            if target == "planned":
                change["attempts"] = 0
            with db.transaction(force_rollback=True):
                task = insert(db, "ai.agent_tasks", task_values(seed, n, **shaped(origin, run)))
                if (origin, target) in LEGAL:
                    update(db, "ai.agent_tasks", task, **change)
                    assert scalar(db.execute("SELECT state FROM ai.agent_tasks WHERE id = %s", (task,))) == target, (origin, target)
                else:
                    said = "done and final" if origin == "done" else f"cannot go from {origin} to {target}"
                    with refuses(db, psycopg.errors.CheckViolation, saying=said):
                        update(db, "ai.agent_tasks", task, **change)
    assert n == len(STATES) * (len(STATES) - 1)


IDENTITY_CHANGES: dict[str, Any] = {
    "id": 10**9, "idem_key": key(777), "custom_id": "x" * 48, "workspace": "lab", "agent": "match", "agent_version": "council-v2",
    "prompt_version": "council-prompt-v2", "schema_version": "cd-v2", "model": "claude-opus-5-5", "effort": "medium",
    "input_version": "package-v2", "input_hash": OTHER, "pass_kind": "final", "fixture_id": 987654, "candidates": ["c1"],
    "run_kind": "shadow", "task_kind": "evaluation", "reason": "another reason", "router_version": "router-v2",
    "route": Jsonb({"level": "opus"}), "package_hash": None, "est_cost_usd": Decimal("0.5"), "created_at": NOW + timedelta(days=1),
}
MAY_CHANGE = {"priority", "not_before", "deadline_at", "state", "queued_at", "started_at", "finished_at", "attempts", "batch_id",
              "last_run_id", "reserved_usd"}


def test_every_column_of_the_queue_is_what_the_task_is_or_what_may_change(db: psycopg.Connection[Any]) -> None:
    """A column a later migration adds must be put on one side or the other, here and in the guard."""
    assert not set(IDENTITY_CHANGES) & MAY_CHANGE
    assert set(columns_of(db, "ai.agent_tasks")) == set(IDENTITY_CHANGES) | MAY_CHANGE


@pytest.mark.parametrize("column", sorted(IDENTITY_CHANGES))
def test_what_a_task_is_never_changes(db: psycopg.Connection[Any], seed: Seed, column: str) -> None:
    task = insert(db, "ai.agent_tasks", task_values(seed))
    with refuses(db, psycopg.errors.CheckViolation, saying="never changes"):
        update(db, "ai.agent_tasks", task, **{column: IDENTITY_CHANGES[column]})


def test_the_priority_the_window_and_the_batch_may_change_while_a_task_waits(db: psycopg.Connection[Any], seed: Seed) -> None:
    task = insert(db, "ai.agent_tasks", task_values(seed, state="queued", queued_at=NOW))
    update(db, "ai.agent_tasks", task, priority=5, not_before=NOW + timedelta(hours=1), deadline_at=NOW + timedelta(hours=12), batch_id=41)
    found = db.execute("SELECT priority, not_before, deadline_at, batch_id, reserved_usd FROM ai.agent_tasks WHERE id = %s", (task,)).fetchone()
    assert found == (5, NOW + timedelta(hours=1), NOW + timedelta(hours=12), 41, Decimal(0))
    with refuses(db, psycopg.errors.CheckViolation, constraint="agent_tasks_window"):
        update(db, "ai.agent_tasks", task, deadline_at=NOW)


def test_the_attempts_count_up_by_one_when_a_task_starts_and_stop_at_three(db: psycopg.Connection[Any], seed: Seed) -> None:
    task = insert(db, "ai.agent_tasks", task_values(seed, state="queued", queued_at=NOW))
    started = NOW + timedelta(seconds=1)
    with refuses(db, psycopg.errors.CheckViolation, saying="without counting the attempt"):
        update(db, "ai.agent_tasks", task, state="running", started_at=started)
    with refuses(db, psycopg.errors.CheckViolation, saying="move only when it starts"):
        update(db, "ai.agent_tasks", task, state="running", started_at=started, attempts=2)
    for attempt in (1, 2, 3):
        update(db, "ai.agent_tasks", task, state="running", started_at=started, attempts=attempt)
        update(db, "ai.agent_tasks", task, state="queued")  # a transport failure: back to the queue, the attempt stays counted
    assert scalar(db.execute("SELECT attempts FROM ai.agent_tasks WHERE id = %s", (task,))) == 3
    with refuses(db, psycopg.errors.CheckViolation, constraint="agent_tasks_attempts_check"):
        update(db, "ai.agent_tasks", task, state="running", started_at=started, attempts=4)
    with refuses(db, psycopg.errors.CheckViolation, saying="move only when it starts"):
        update(db, "ai.agent_tasks", task, attempts=0)  # nobody gives the attempts back, except by planning the task again


def test_planning_a_task_again_gives_the_attempts_back_all_or_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    run = insert(db, "ai.agent_runs", run_values(seed))
    failed = insert(db, "ai.agent_tasks", task_values(seed, state="failed", queued_at=NOW, started_at=NOW, attempts=3, finished_at=NOW,
                                                      last_run_id=run))
    with refuses(db, psycopg.errors.CheckViolation, saying="move only when it starts"):
        update(db, "ai.agent_tasks", failed, state="planned", finished_at=None, attempts=2)
    update(db, "ai.agent_tasks", failed, state="planned", finished_at=None, attempts=0)
    found = db.execute("SELECT state, attempts, finished_at, last_run_id FROM ai.agent_tasks WHERE id = %s", (failed,)).fetchone()
    assert found == ("planned", 0, None, run), "the run of the failed attempt stays: it is the record"


def test_a_done_task_is_final_and_a_task_is_never_deleted_unless_the_owner_lifts_the_guard(db: psycopg.Connection[Any], seed: Seed) -> None:
    run = insert(db, "ai.agent_runs", run_values(seed))
    done = insert(db, "ai.agent_tasks", task_values(seed, 1, **shaped("done", run)))
    waiting = insert(db, "ai.agent_tasks", task_values(seed, 2))
    with refuses(db, psycopg.errors.CheckViolation, saying="done and final"):
        update(db, "ai.agent_tasks", done, priority=1)
    with refuses(db, psycopg.errors.CheckViolation, saying="never deleted"):
        db.execute("DELETE FROM ai.agent_tasks WHERE id = %s", (waiting,))
    with refuses(db, psycopg.errors.CheckViolation, saying="never deleted"):
        db.execute("DELETE FROM ai.agent_tasks WHERE id = %s", (done,))
    with db.transaction(force_rollback=True):  # the owner's repair: one transaction, then the guard is back
        db.execute("SET LOCAL fbi.ai_maintenance = 'on'")
        update(db, "ai.agent_tasks", done, priority=1)
        assert db.execute("DELETE FROM ai.agent_tasks WHERE id = %s", (waiting,)).rowcount == 1
    assert scalar(db.execute("SELECT count(*) FROM ai.agent_tasks WHERE id = ANY(%s)", ([done, waiting],))) == 2


def test_the_same_question_is_one_task(db: psycopg.Connection[Any], seed: Seed) -> None:
    insert(db, "ai.agent_tasks", task_values(seed, 1))
    with refuses(db, psycopg.errors.UniqueViolation, constraint="agent_tasks_idem_key_key"):
        insert(db, "ai.agent_tasks", task_values(seed, 1, priority=1))


RUN = object()
"""Stands for the id of a run the test inserts first: an ending must point at one for the rest of its rules to be the ones that speak."""

BAD_TASKS = [
    ("custom_id is not the start of the key", {"custom_id": "z" * 48}, "agent_tasks_custom_id"),
    ("an idem_key that is not a sha256", {"idem_key": "abc", "custom_id": "abc"}, "agent_tasks_idem_key_check"),
    ("an upper-case hash", {"input_hash": "A" * 64}, "agent_tasks_input_hash_check"),
    ("a window that closes before it opens", {"deadline_at": NOW - timedelta(hours=1)}, "agent_tasks_window"),
    ("a free task", {"est_cost_usd": Decimal(0)}, "agent_tasks_est_cost_usd_check"),
    ("a fixture that is not one", {"fixture_id": 0}, "agent_tasks_fixture_id_check"),
    ("thirteen candidates", {"candidates": [f"c{i}" for i in range(1, 14)]}, "agent_tasks_candidates_check"),
    ("a candidate twice", {"candidates": ["c1", "c1"]}, "agent_tasks_candidates_check"),
    ("a candidate that is not named c<n>", {"candidates": ["x1"]}, "agent_tasks_candidates_check"),
    ("a workspace that is neither", {"workspace": "staging"}, "agent_tasks_workspace_check"),
    ("an effort the plan does not use", {"effort": "high"}, "agent_tasks_effort_check"),
    ("a battery task (a battery runs, it is not queued)", {"run_kind": "battery"}, "agent_tasks_run_kind_check"),
    ("a task the router does not know", {"task_kind": "gossip"}, "agent_tasks_task_kind_check"),
    ("a pass that does not exist", {"pass_kind": "late"}, "agent_tasks_pass_kind_check"),
    ("an agent with a space in its name", {"agent": "the council"}, "agent_tasks_agent_check"),
    ("a model with a slash", {"model": "anthropic/claude"}, "agent_tasks_model_check"),
    ("an empty reason", {"reason": "   "}, "agent_tasks_reason_check"),
    ("a priority below zero", {"priority": -1}, "agent_tasks_priority_check"),
    ("a priority beyond a million", {"priority": 1_000_001}, "agent_tasks_priority_check"),
    ("a state nobody defined", {"state": "paused"}, "agent_tasks_state_check"),
    ("a fourth attempt", {"attempts": 4}, "agent_tasks_attempts_check"),
    ("a route that is not an object", {"route": Jsonb([1])}, "agent_tasks_route_check"),
    ("a package hash that is not a hash", {"package_hash": "xyz"}, "agent_tasks_package_hash_check"),
    ("queued with no queue time", {"state": "queued"}, "agent_tasks_times"),
    ("running with no start", {"state": "running", "queued_at": NOW, "attempts": 1}, "agent_tasks_times"),
    ("running with no attempt counted", {"state": "running", "queued_at": NOW, "started_at": NOW}, "agent_tasks_times"),
    ("planned and already finished", {"finished_at": NOW}, "agent_tasks_times"),
    ("queued and already finished", {"state": "queued", "queued_at": NOW, "finished_at": NOW}, "agent_tasks_times"),
    ("done with no finish", {"state": "done", "queued_at": NOW, "started_at": NOW, "attempts": 1, "last_run_id": RUN}, "agent_tasks_times"),
    ("failed with no start", {"state": "failed", "queued_at": NOW, "finished_at": NOW, "attempts": 1, "last_run_id": RUN}, "agent_tasks_times"),
    ("an ending that left no run", {"state": "expired", "finished_at": NOW}, "agent_tasks_ends_in_a_run"),
]


@pytest.mark.parametrize(("label", "over", "constraint"), BAD_TASKS, ids=[b[0] for b in BAD_TASKS])
def test_the_queue_refuses_a_task_that_is_not_well_formed(db: psycopg.Connection[Any], seed: Seed, label: str, over: dict[str, Any],
                                                          constraint: str) -> None:
    run = insert(db, "ai.agent_runs", run_values(seed, 900))
    over = {column: run if value is RUN else value for column, value in over.items()}
    with refuses(db, psycopg.errors.CheckViolation, constraint=constraint):
        insert(db, "ai.agent_tasks", task_values(seed, **over))


def test_a_task_that_names_no_fixture_or_no_key_is_not_a_task(db: psycopg.Connection[Any], seed: Seed) -> None:
    for column in ("idem_key", "custom_id", "workspace", "agent", "model", "fixture_id", "task_kind", "reason", "priority", "est_cost_usd",
                   "created_at", "not_before", "deadline_at", "input_hash", "router_version"):
        values = task_values(seed)
        del values[column]
        with refuses(db, psycopg.errors.NotNullViolation):
            insert(db, "ai.agent_tasks", values)


# ── the record of every attempt ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_run_is_recorded_once_and_never_rewritten(db: psycopg.Connection[Any], seed: Seed) -> None:
    run = insert(db, "ai.agent_runs", run_values(seed))
    with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
        update(db, "ai.agent_runs", run, cost_usd=Decimal(0))
    with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
        db.execute("DELETE FROM ai.agent_runs WHERE id = %s", (run,))
    with db.transaction(force_rollback=True):  # only the owner's repair, in one transaction
        db.execute("SET LOCAL fbi.ai_maintenance = 'on'")
        update(db, "ai.agent_runs", run, reason="repaired by the owner")
        assert scalar(db.execute("SELECT reason FROM ai.agent_runs WHERE id = %s", (run,))) == "repaired by the owner"


def test_a_question_is_paid_once(db: psycopg.Connection[Any], seed: Seed) -> None:
    insert(db, "ai.agent_runs", run_values(seed, 5, **UNPAID, attempt=1))  # the first attempt got no answer, and cost nothing
    insert(db, "ai.agent_runs", run_values(seed, 5, attempt=2))  # the second did
    for answer in ({}, INVALID, ABSTAIN):
        with refuses(db, psycopg.errors.UniqueViolation, constraint="ai_agent_runs_paid_once"):
            insert(db, "ai.agent_runs", run_values(seed, 5, attempt=3, **answer))
    insert(db, "ai.agent_runs", run_values(seed, 5, **(UNPAID | {"status": "skipped"}), attempt=3))  # what costs nothing can still be recorded
    with refuses(db, psycopg.errors.UniqueViolation, constraint="agent_runs_attempt_once"):
        insert(db, "ai.agent_runs", run_values(seed, 5, **UNPAID, attempt=3))
    # another question is another key: it pays again
    insert(db, "ai.agent_runs", run_values(seed, 6, attempt=1))
    for n, extra in ((10, INVALID), (11, ABSTAIN)):
        insert(db, "ai.agent_runs", run_values(seed, n, attempt=1, **extra))
    paid = scalar(db.execute("SELECT count(*) FROM ai.agent_runs WHERE status IN ('ok', 'invalid', 'abstain')"))
    assert paid == 4


def test_a_run_may_cite_the_run_it_follows(db: psycopg.Connection[Any], seed: Seed) -> None:
    first = insert(db, "ai.agent_runs", run_values(seed, 1))
    insert(db, "ai.agent_runs", run_values(seed, 2, parent_run_id=first, run_kind="shadow"))
    with refuses(db, psycopg.errors.ForeignKeyViolation):
        insert(db, "ai.agent_runs", run_values(seed, 3, parent_run_id=10**9))


BAD_RUNS = [
    ("an answer with no output", {"output": None}, "agent_runs_output"),
    ("an answer from no model", {"model": None}, "agent_runs_answer"),
    ("an answer that counted no tokens", {"input_tokens": None}, "agent_runs_answer"),
    ("an answer that wrote no tokens", {"output_tokens": None}, "agent_runs_answer"),
    ("a timeout that cost money", UNPAID | {"cost_usd": Decimal("0.01")}, "agent_runs_unpaid"),
    ("a timeout that used tokens", UNPAID | {"input_tokens": 10, "output_tokens": 0}, "agent_runs_unpaid"),
    ("a budget skip that cost money", UNPAID | {"status": "budget_skip", "cost_usd": Decimal("0.01")}, "agent_runs_unpaid"),
    ("a failure that says nothing", UNPAID | {"error": None}, "agent_runs_error"),
    ("an invalid answer that says nothing", INVALID | {"error": None}, "agent_runs_error"),
    ("a skipped run with an output", UNPAID | {"status": "skipped", "output": Jsonb({})}, "agent_runs_output"),
    ("an invalid answer that keeps a verdict", INVALID | {"verdict": "APPROVE"}, "agent_runs_output"),
    ("more cached tokens than input", {"cached_tokens": 1000, "cache_write_tokens": 300}, "agent_runs_tokens"),
    ("a run that ends before it starts", {"finished_at": NOW - timedelta(seconds=1)}, "agent_runs_time"),
    ("knowledge from after the start", {"known_at": NOW + timedelta(seconds=1)}, "agent_runs_time"),
    ("a fourth attempt", {"attempt": 4}, "agent_runs_attempt_check"),
    ("a run kind nobody has", {"run_kind": "lab"}, "agent_runs_run_kind_check"),
    ("a task nobody knows", {"task_kind": "gossip"}, "agent_runs_task_kind_check"),
    ("a pass nobody knows", {"pass_kind": "late"}, "agent_runs_pass_kind_check"),
    ("an effort nobody uses", {"effort": "high"}, "agent_runs_effort_check"),
    ("a cache lifetime of half an hour", {"cache_ttl": "30m"}, "agent_runs_cache_ttl_check"),
    ("a negative cost", {"cost_usd": Decimal("-0.01")}, "agent_runs_cost_usd_check"),
    ("a negative count of tokens", {"thinking_tokens": -1}, "agent_runs_thinking_tokens_check"),
    ("a model with a space", {"model": "claude sonnet"}, "agent_runs_model_check"),
    ("an agent with a space", {"agent": "the council"}, "agent_runs_agent_check"),
    ("a package hash that is not a hash", {"package_hash": "xyz"}, "agent_runs_package_hash_check"),
    ("a slice hash that is not a hash", {"slice_hash": "xyz"}, "agent_runs_slice_hash_check"),
    ("an idem_key that is not a hash", {"idem_key": "xyz"}, "agent_runs_idem_key_check"),
    ("a batch name with a dot", {"custom_id": "a.b"}, "agent_runs_custom_id_check"),
    ("a reason that is blank", {"reason": " "}, "agent_runs_reason_check"),
    ("a verdict beyond 64 characters", {"verdict": "x" * 65}, "agent_runs_verdict_check"),
    ("an output that is a list", {"output": Jsonb([1])}, "agent_runs_output_check"),
    ("a candidate the package does not name", {"candidates": ["x"]}, "agent_runs_candidates_check"),
    ("a fixture below one", {"fixture_id": 0}, "agent_runs_fixture_id_check"),
    ("an error beyond 2000 characters", UNPAID | {"error": "e" * 2001}, "agent_runs_error_check"),
    ("a latency below zero", {"latency_ms": -1}, "agent_runs_latency_ms_check"),
]


@pytest.mark.parametrize(("label", "over", "constraint"), BAD_RUNS, ids=[b[0] for b in BAD_RUNS])
def test_the_record_refuses_a_run_that_is_not_well_formed(db: psycopg.Connection[Any], seed: Seed, label: str, over: dict[str, Any],
                                                          constraint: str) -> None:
    with refuses(db, psycopg.errors.CheckViolation, constraint=constraint):
        insert(db, "ai.agent_runs", run_values(seed, **over))


def test_a_run_the_database_takes_is_what_the_code_means_by_each_ending(db: psycopg.Connection[Any], seed: Seed) -> None:
    """All seven endings, each as the orchestrator will write it - and the answer of a model is the only thing that is paid."""
    endings: dict[str, dict[str, Any]] = {
        "ok": {}, "invalid": INVALID, "abstain": ABSTAIN, "timeout": UNPAID,
        "skipped": UNPAID | {"status": "skipped", "error": "the match kicked off"},
        "expired": UNPAID | {"status": "expired", "error": "past its deadline"},
        "budget_skip": UNPAID | {"status": "budget_skip", "error": "the envelope has no room"},
    }
    for n, (status, extra) in enumerate(endings.items(), start=1):
        insert(db, "ai.agent_runs", run_values(seed, n, **extra))
        assert scalar(db.execute("SELECT status FROM ai.agent_runs WHERE idem_key = %s", (key(n),))) == status
    assert set(endings) == lists_of(db, "ai.agent_runs")["status"]


# ── the state of a match ──────────────────────────────────────────────────────────────────────────────────────────────────────────

VIEW_COLUMNS = ["match_run_id", "fixture_id", "pass_kind", "known_at", "created_at", "state_version", "package_version", "package_hash",
                "packet_id", "elapsed_ms", "slices", "blocking", "flags", "data_status", "market_status", "model_status", "research_status",
                "agents", "contradictions", "candidates", "risks", "final"]


def test_the_view_of_the_state_of_a_match_has_the_columns_the_administrator_reads(db: psycopg.Connection[Any]) -> None:
    assert columns_of(db, "ai.match_state") == VIEW_COLUMNS


def test_a_row_built_before_any_agent_ran_has_them_empty(db: psycopg.Connection[Any], seed: Seed) -> None:
    run = insert(db, "ai.match_runs", match_values(seed))
    found = db.execute("SELECT agents, contradictions, candidates, risks, final, data_status, market_status, model_status, research_status "
                       "FROM ai.match_runs WHERE id = %s", (run,)).fetchone()
    assert found == ([], [], [], [], {}, {}, {}, {}, {})


def test_the_state_of_a_match_is_its_newest_live_row(db: psycopg.Connection[Any], seed: Seed) -> None:
    first = insert(db, "ai.match_runs", match_values(seed, known_at=NOW - timedelta(hours=6), created_at=NOW - timedelta(hours=5)))
    newest = insert(db, "ai.match_runs", match_values(seed, pass_kind="pre", known_at=NOW - timedelta(hours=2)))
    insert(db, "ai.match_runs", match_values(seed, pass_kind="final", run_kind="shadow", known_at=NOW - timedelta(minutes=30)))
    insert(db, "ai.match_runs", match_values(seed, pass_kind="request", run_kind="replay", known_at=NOW - timedelta(minutes=20)))
    state = db.execute("SELECT match_run_id, pass_kind FROM ai.match_state WHERE fixture_id = %s", (seed.fixture_id,)).fetchall()
    assert state == [(newest, "pre")], "the arms under test and the backtests never become the state of the match"
    assert first != newest


def test_two_rows_of_one_moment_of_knowledge_are_decided_by_the_later_write(db: psycopg.Connection[Any], seed: Seed) -> None:
    insert(db, "ai.match_runs", match_values(seed, pass_kind="first"))
    later = insert(db, "ai.match_runs", match_values(seed, pass_kind="pre"))
    assert db.execute("SELECT match_run_id FROM ai.match_state WHERE fixture_id = %s", (seed.fixture_id,)).fetchall() == [(later,)]


def test_each_match_has_one_state(db: psycopg.Connection[Any], seed: Seed) -> None:
    other = seed.fixture_id + 1
    insert(db, "ai.match_runs", match_values(seed))
    insert(db, "ai.match_runs", match_values(seed, known_at=NOW - timedelta(minutes=10)))
    insert(db, "ai.match_runs", match_values(seed, fixture_id=other))
    rows = db.execute("SELECT fixture_id FROM ai.match_state WHERE fixture_id = ANY(%s) ORDER BY fixture_id", ([seed.fixture_id, other],)).fetchall()
    assert rows == [(seed.fixture_id,), (other,)]


def test_the_same_pass_at_the_same_moment_is_one_row(db: psycopg.Connection[Any], seed: Seed) -> None:
    """A builder that runs twice over the same stored packet writes once: ON CONFLICT DO NOTHING has a constraint to name."""
    insert(db, "ai.match_runs", match_values(seed))
    with refuses(db, psycopg.errors.UniqueViolation, constraint="match_runs_once"):
        insert(db, "ai.match_runs", match_values(seed, elapsed_ms=1))
    insert(db, "ai.match_runs", match_values(seed, run_kind="shadow"))  # the same moment, another kind of run: another row
    insert(db, "ai.match_runs", match_values(seed, pass_kind="pre"))


def test_the_state_of_a_match_is_never_rewritten(db: psycopg.Connection[Any], seed: Seed) -> None:
    run = insert(db, "ai.match_runs", match_values(seed))
    with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
        update(db, "ai.match_runs", run, flags=[])
    with refuses(db, psycopg.errors.CheckViolation, saying="append-only"):
        db.execute("DELETE FROM ai.match_runs WHERE id = %s", (run,))


@pytest.mark.parametrize("table", ["agent_runs", "match_runs"])
def test_the_record_is_guarded_row_by_row_so_a_statement_that_touches_nothing_is_no_error(db: psycopg.Connection[Any], seed: Seed,
                                                                                         table: str) -> None:
    """A repair that finds nothing to repair, or a clean-up that matches no row, is not an attempt to rewrite the record."""
    insert(db, f"ai.{table}", run_values(seed) if table == "agent_runs" else match_values(seed))
    assert db.execute(f"UPDATE ai.{table} SET fixture_id = fixture_id WHERE false").rowcount == 0
    assert db.execute(f"DELETE FROM ai.{table} WHERE false").rowcount == 0
    assert scalar(db.execute(f"SELECT count(*) FROM ai.{table}")) == 1


BAD_STATES = [
    ("knowledge from after the row was built", {"known_at": NOW + timedelta(minutes=1)}, "match_runs_time"),
    ("a fixture below one", {"fixture_id": 0}, "match_runs_fixture_id_check"),
    ("a pass nobody knows", {"pass_kind": "late"}, "match_runs_pass_kind_check"),
    ("a battery is not a state", {"run_kind": "battery"}, "match_runs_run_kind_check"),
    ("a version with a space", {"state_version": "ms v1"}, "match_runs_state_version_check"),
    ("a package that names no version properly", {"package_version": "mcp/v1"}, "match_runs_package_version_check"),
    ("a package hash that is not a hash", {"package_hash": "xyz"}, "match_runs_package_hash_check"),
    ("a negative build time", {"elapsed_ms": -1}, "match_runs_elapsed_ms_check"),
    ("slices that are an object", {"slices": Jsonb({})}, "match_runs_slices_check"),
    ("a final that is a list", {"final": Jsonb([])}, "match_runs_final_check"),
    ("agents that are an object", {"agents": Jsonb({})}, "match_runs_agents_check"),
    ("contradictions that are an object", {"contradictions": Jsonb({})}, "match_runs_contradictions_check"),
    ("candidates that are an object", {"candidates": Jsonb({})}, "match_runs_candidates_check"),
    ("risks that are an object", {"risks": Jsonb({})}, "match_runs_risks_check"),
    ("a data status that is a list", {"data_status": Jsonb([])}, "match_runs_data_status_check"),
    ("a market status that is a list", {"market_status": Jsonb([])}, "match_runs_market_status_check"),
    ("a model status that is a list", {"model_status": Jsonb([])}, "match_runs_model_status_check"),
    ("a research status that is a list", {"research_status": Jsonb([])}, "match_runs_research_status_check"),
]


@pytest.mark.parametrize(("label", "over", "constraint"), BAD_STATES, ids=[b[0] for b in BAD_STATES])
def test_the_state_refuses_a_row_that_is_not_well_formed(db: psycopg.Connection[Any], seed: Seed, label: str, over: dict[str, Any],
                                                        constraint: str) -> None:
    with refuses(db, psycopg.errors.CheckViolation, constraint=constraint):
        insert(db, "ai.match_runs", match_values(seed, **over))


def test_nothing_new_holds_a_foreign_key_to_a_busy_table(db: psycopg.Connection[Any]) -> None:
    """The worker writes core.fixtures, ai.usage and ai.match_packets all day: a foreign key to them is a lock held against it."""
    rows = db.execute("SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint WHERE contype = 'f' "
                      "AND conrelid IN ('ai.agent_tasks'::regclass, 'ai.agent_runs'::regclass, 'ai.match_runs'::regclass)").fetchall()
    assert sorted(rows) == [("ai.agent_runs", "ai.agent_runs"), ("ai.agent_tasks", "ai.agent_runs")]
