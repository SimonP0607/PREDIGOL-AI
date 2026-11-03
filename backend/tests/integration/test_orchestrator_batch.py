"""The Batch calendar of the shadow (``fbi.ai.orchestrator``, plan IA sections 16-18) over a real database, with a scripted Message Batches API.

What is shown: a far ``first`` or ``pre`` pass is queued, not asked (stage 1 is stored ``queued`` and sent in the same run); the pass is picked up again
by the job as soon as no item of it is open, plans stage 2 and stage 3 from what the poll kept, and is WRITTEN when the last stage is settled - with rows
that have the shape of the ones a pass asked in real time leaves (the same pass, once each way, is compared row by row); what the Batch can do wrong
(an item that errors, expires or is cancelled, a batch that cannot be created, a spent limit, a stage that cannot be queued in time, an item still open
at T-100) is an arm ``fallback`` with a code and never a paid call in real time; a ``final`` pass and a near pass stay synchronous; the budget is checked
on the WHOLE pass before anything is queued; the poll's handler is idempotent; and text in the evidence is data here too."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from fbi.ai import batch, lab, orchestrator
from fbi.ai.agents import council, match
from fbi.ai.batch import Resolved
from fbi.ai.config import SHADOW_ENGINES
from fbi.ai.providers.base import JsonRequest, LlmResult, LlmUsage
from fbi.ai.providers.fake import FakeBatches
from tests.integration.conftest import Seed
from tests.integration.orchestrator_world import (
    AT,
    HAIKU,
    OPUS,
    RUN,
    SONNET,
    Gear,
    World,
    answer_for,
    assign,
    counts,
    provider,
    rules_review,
    settings,
    world,
)
from tests.integration.test_ai_decision_layer import Savepoints
from tests.integration.test_availability_history import KICKOFF, H
from tests.integration.test_match_runs import passed
from tests.integration.test_orchestrator import (
    INJECTION,
    another_fixture,
    approves_with_doubt,
    injected,
    opus_calls,
)
from tests.integration.test_slice_leak_audit import STORED, stored_at

pytestmark = pytest.mark.integration

D = Decimal
MINUTE = timedelta(minutes=1)
ENGINES = ("ma-v1", "ma-v1-h", "cs-v1")


@pytest.fixture(autouse=True)
def clean_memory() -> None:
    orchestrator._failed.clear()


def rows(db: psycopg.Connection[Any], sql: str, *args: Any, **named: Any) -> list[dict[str, Any]]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, named or args)
        return list(cur.fetchall())


def cfg(**over: Any) -> Any:
    """The shadow on, at full sample, with the ``batch`` switch on (the gate's evidence is not what is tested here)."""
    return settings(switches={"budget_v3": "on", "batch": "on"}, **over)


def as_asked(script: Any) -> Any:
    """A script that reads the request as the orchestrator built it: a request that travels in a batch carries the tool-call instruction after its
    system text (``tool_choice`` is ``auto`` there), so the system text is put back before the script looks at it."""

    def wrapped(request: JsonRequest) -> dict[str, Any]:
        texts = [*match.SYSTEM.values(), *council.SYSTEM_OF.values()]
        for text in sorted(texts, key=len, reverse=True):
            if request.system.startswith(text):
                request = replace(request, system=text)
                break
        return script(request)

    return wrapped


def fake_batches(script: Any = None, **kw: Any) -> FakeBatches:
    return FakeBatches(as_asked(script or answer_for), name="anthropic", **kw)


def run(db: psycopg.Connection[Any], gear: Gear, fake: FakeBatches | None, *, at: Any = RUN, conf: Any = None, prov: Any = None) -> orchestrator.Report:
    return orchestrator.run(Savepoints(db), conf or cfg(), at=at, provider=prov, ledger=gear.ledger, slots=gear.slots, circuit=gear.circuit, batch_client=fake)  # type: ignore[arg-type]


def settle(db: psycopg.Connection[Any], gear: Gear, fake: FakeBatches, *, at: Any, conf: Any = None, **outcomes: Any) -> batch.PollReport:
    """The provider ends every open batch and the poll takes the results."""
    fake.end(outcomes=outcomes.get("outcomes"))
    return batch.poll(Savepoints(db), conf or cfg(), at=at, ledger=gear.ledger, client=fake)  # type: ignore[arg-type]


def items(db: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return rows(db, "SELECT * FROM ai.batch_items ORDER BY id")


def tasks(db: psycopg.Connection[Any], fixture: int) -> list[dict[str, Any]]:
    return rows(db, "SELECT t.*, r.status AS run_status FROM ai.agent_tasks t LEFT JOIN ai.agent_runs r ON r.id = t.last_run_id WHERE t.fixture_id = %s ORDER BY t.id", fixture)


def reviews(db: psycopg.Connection[Any], fixture: int, *engines: str) -> list[dict[str, Any]]:
    return rows(db, "SELECT * FROM ai.pick_reviews WHERE fixture_id = %s AND engine = ANY(%s) ORDER BY engine, market_key, selection, line", fixture, list(engines or ENGINES))


def kinds(rs: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(t["task_kind"], t["agent"]) for t in rs]


def twin(db: psycopg.Connection[Any], w: World) -> int:
    """Another match of the same competition with the same three selections, its own packet and pass (a world to run the other way)."""
    other = another_fixture(db, w)
    packet = stored_at(db, other, AT, stored=STORED)
    passed(db, other, "pre", packet)
    for spec in (("1X2", "Home", "0", "0.55", "2.10"), ("1X2", "Draw", "0", "0.27", "3.60"), ("OU", "Over", "2.5", "0.58", "1.95")):
        rules_review(db, other, packet, spec)
    return other


def to_the_end(db: psycopg.Connection[Any], gear: Gear, fake: FakeBatches, *, conf: Any = None, start: Any = RUN, step: timedelta = 10 * MINUTE, limit: int = 8, prov: Any = None) -> list[orchestrator.Report]:
    """Run, settle, run... until a run writes the pass."""
    reports: list[orchestrator.Report] = []
    now = start
    for _ in range(limit):
        reports.append(run(db, gear, fake, at=now, conf=conf, prov=prov))
        if reports[-1].ran:
            break
        now += step
        settle(db, gear, fake, at=now, conf=conf)
        now += step
    return reports


# ── a far pass is queued, not asked ───────────────────────────────────────────────────────────────────────────────

def test_a_far_pass_stores_stage_one_queued_and_sends_it_in_the_same_run_without_a_call_in_real_time(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, pv = fake_batches(), provider()
    report = run(db, Gear(db), fake, prov=pv)
    assert pv.requests == [], "no call in real time"
    assert (report.considered, report.queued, report.waiting, report.ran, report.calls, report.failed_open) == (1, 3, 1, 0, 0, 0)
    assert len(fake.created) == 1 and len(fake.created[0]) == 3, "one batch of the three questions of stage 1"
    ts = tasks(db, w.fixture)
    assert sorted(kinds(ts)) == sorted([("context", "match"), ("evaluation", "match"), ("council", "council")])
    assert [t["model"] for t in sorted(ts, key=lambda t: t["task_kind"])] == [SONNET, HAIKU, HAIKU] or {t["model"] for t in ts} == {HAIKU, SONNET}
    for t in ts:
        assert t["state"] == "queued" and t["run_kind"] == "shadow" and t["workspace"] == "lab" and t["last_run_id"] is None and t["attempts"] == 0
        assert t["route"]["mode"] == "batch" and t["route"]["stage"] == 1 and t["route"]["packet_id"] == w.packet
        assert t["route"]["batch_custom_id"] == t["custom_id"] or len(t["route"]["batch_custom_id"]) == 48
        assert t["batch_id"] is not None and t["reserved_usd"] == 0, "the batch item holds the reservation, not the task"
        assert t["deadline_at"] == KICKOFF - timedelta(minutes=60) and t["est_cost_usd"] > 0
        assert t["route"]["active"] == ["ma-v1", "ma-v1-h", "cs-v1"] and t["route"]["paused"] == {}
    its = items(db)
    assert len(its) == 3 and {i["status"] for i in its} == {"submitted"} and {i["purpose"] for i in its} == {"other"}
    assert all(i["context"]["lab"] == "shadow" and i["fixture_id"] == w.fixture and i["deadline_at"] == KICKOFF - timedelta(minutes=60) for i in its)
    assert {r["status"] for r in rows(db, "SELECT status FROM ai.batches")} == {"in_progress"}, "flushed in the run that recorded it: nothing left submitting"
    assert counts(db)["ai.match_runs"] == 0 and rows(db, "SELECT 1 FROM ai.pick_reviews WHERE engine = ANY(%s)", list(SHADOW_ENGINES)) == []
    assert counts(db)["ai.usage"] == 0 and counts(db)["ai.agent_runs"] == 0


def test_a_pass_that_waits_is_not_selected_again_until_its_items_are_settled(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(), Gear(db)
    run(db, gear, fake)
    before = counts(db)
    again = run(db, gear, fake, at=RUN + 5 * MINUTE)
    assert (again.considered, again.queued, again.calls) == (0, 0, 0) and counts(db) == before and len(fake.created) == 1
    settle(db, gear, fake, at=RUN + 30 * MINUTE)
    third = run(db, gear, fake, at=RUN + 35 * MINUTE)
    assert third.considered == 1, "the items are settled: the next stage can be planned"
    assert w.fixture


def test_stage_one_is_not_queued_twice_by_a_run_that_repeats(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(), Gear(db)
    run(db, gear, fake)
    # the same moment again (a restart of the job): the tasks are stored, the items are open, nothing new is queued
    db.execute("SAVEPOINT x")
    again = run(db, gear, fake)
    assert again.queued == 0 and len(fake.created) == 1 and len(tasks(db, w.fixture)) == 3 and len(items(db)) == 3
    db.execute("RELEASE SAVEPOINT x")


# ── the stages and the rows ───────────────────────────────────────────────────────────────────────────────────────

def test_the_stages_follow_one_another_and_the_last_one_writes_the_pass(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(), Gear(db)
    pv = provider()
    reports = to_the_end(db, gear, fake)
    assert [r.ran for r in reports] == [0, 1] if len(reports) == 2 else reports[-1].ran == 1
    assert len(fake.created) == 2 and [len(b) for b in fake.created] == [3, 2], "stage 1: context, evaluation, solo council; stage 2: the two arms that read the assessments"
    ts = tasks(db, w.fixture)
    assert len(ts) == 5 and {t["state"] for t in ts} == {"done"} and {t["run_status"] for t in ts} == {"ok"}
    assert sorted(t["route"]["stage"] for t in ts) == [1, 1, 1, 2, 2]
    assert all(t["attempts"] == 1 and t["last_run_id"] is not None and t["finished_at"] is not None and t["started_at"] is not None for t in ts)
    runs = rows(db, "SELECT * FROM ai.agent_runs WHERE fixture_id = %s", w.fixture)
    assert len(runs) == 5 and all(r["batch_id"] is not None and len(r["custom_id"]) == 48 and r["cost_usd"] > 0 and r["usage_id"] for r in runs)
    [state] = rows(db, "SELECT * FROM ai.match_runs WHERE fixture_id = %s AND run_kind = 'shadow'", w.fixture)
    assert state["final"]["status"] == "ran" and state["final"]["too_late"] is False and set(state["final"]["engines"]) == set(ENGINES)
    assert all(e["status"] == "ok" for e in state["final"]["engines"].values()) and len(state["agents"]) == 5
    rs = reviews(db, w.fixture)
    assert len(rs) == 9 and {r["decision"] for r in rs} == {"APPROVE"} and all(r["mode"] == "shadow" and r["status"] == "ok" for r in rs)
    assert all(r["cost_usd"] > 0 and r["usage_ids"] for r in rs)
    assert pv.requests == []
    assert rows(db, "SELECT count(*) AS n FROM ai.batches WHERE status = 'submitting'")[0]["n"] == 0
    assert run(db, gear, fake, at=RUN + timedelta(hours=2)).considered == 0, "written: not selected again"


def normalized(db: psycopg.Connection[Any], fixture: int) -> dict[str, Any]:
    """What a pass left, without what is bound to differ between two ways of asking (ids, moments, the price, the tokens, the route)."""
    out: dict[str, Any] = {}
    shadow = rows(db, "SELECT * FROM ai.pick_reviews WHERE fixture_id = %s AND engine = ANY(%s) ORDER BY engine, market_key, selection, line", fixture, list(SHADOW_ENGINES))
    out["reviews"] = [{k: v for k, v in r.items() if k not in ("id", "reviewed_at", "usage_ids", "cost_usd")} for r in shadow]
    [state] = rows(db, "SELECT * FROM ai.match_runs WHERE fixture_id = %s AND run_kind = 'shadow'", fixture)
    state = {k: v for k, v in state.items() if k not in ("id", "created_at", "elapsed_ms", "fixture_id")}
    state["agents"] = [{k: v for k, v in a.items() if k != "cost_usd"} for a in state["agents"]]
    out["state"] = state
    out["tasks"] = sorted(
        (
            {k: v for k, v in t.items() if k in ("agent", "agent_version", "prompt_version", "schema_version", "model", "effort", "input_version", "input_hash", "pass_kind", "candidates", "task_kind", "state", "idem_key", "package_hash")}
            | dict(rows(db, "SELECT status, output, verdict, evidence_ids, data_refs, error, attempt, parent_run_id IS NOT NULL AS has_parent FROM ai.agent_runs WHERE id = %s", t["last_run_id"])[0])
            for t in rows(db, "SELECT * FROM ai.agent_tasks WHERE fixture_id = %s", fixture)
        ),
        key=lambda t: (t["task_kind"], t["agent"], t["model"], t["idem_key"]),
    )
    return out


@pytest.mark.parametrize("script_name", ["plain", "doubt"])
def test_a_pass_through_the_batch_leaves_the_rows_of_a_pass_asked_in_real_time(db: psycopg.Connection[Any], seed: Seed, script_name: str) -> None:
    """The same pass, once in real time and once through the Batch, over the same fakes: the same reviews, state and tasks, row by row."""
    script = answer_for if script_name == "plain" else approves_with_doubt
    w = world(db, seed)
    assign(db, w.fixture)
    db.execute("SAVEPOINT equivalence")
    sync = orchestrator.run(Savepoints(db), settings(), at=RUN, provider=provider(script), ledger=Gear(db).ledger, slots=Gear(db).slots, circuit=Gear(db).circuit)  # type: ignore[arg-type]
    assert sync.ran == 1 and sync.queued == 0
    real = normalized(db, w.fixture)
    db.execute("ROLLBACK TO SAVEPOINT equivalence")
    gear = Gear(db)
    reports = to_the_end(db, gear, fake_batches(script))
    assert reports[-1].ran == 1 and all(r.calls == 0 for r in reports)
    through = normalized(db, w.fixture)
    assert through["reviews"] == real["reviews"]
    assert through["state"] == real["state"]
    assert through["tasks"] == real["tasks"]
    assert len(real["reviews"]) == 9 and len(real["tasks"]) == (6 if script_name == "doubt" else 5)


def test_opus_is_a_third_stage_asked_once_for_the_two_arms_with_the_hours_frozen(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture, solo=False)
    fake, gear = fake_batches(approves_with_doubt), Gear(db)
    reports = to_the_end(db, gear, fake)
    assert reports[-1].ran == 1 and reports[-1].escalated == 3 and len(fake.created) == 3, "three batches: Match Agent, the two Councils, Opus"
    opus = [t for t in tasks(db, w.fixture) if t["task_kind"] == "escalation"]
    assert len(opus) == 1 and opus[0]["route"]["stage"] == 3 and opus[0]["model"] == OPUS and opus[0]["state"] == "done"
    assert Decimal(opus[0]["route"]["hours_to_kickoff"]) > 0 and set(opus[0]["route"]["escalated"]) == {"c1", "c2", "c3"}
    shadow = reviews(db, w.fixture, "ma-v1", "ma-v1-h")
    assert {(r["decision"], r["confidence"]) for r in shadow} == {("REJECT", D("0.850"))}
    assert all(r["output"]["escalation"] == {"rule": "E7", "model": OPUS, "replaced": True} for r in shadow)
    parent = rows(db, "SELECT r.parent_run_id, p.task_kind FROM ai.agent_runs r JOIN ai.agent_runs p ON p.id = r.parent_run_id WHERE r.task_kind = 'escalation'")
    assert len(parent) == 1 and parent[0]["task_kind"] == "council", "Opus' run points at the Council's"


def test_the_opus_cap_counts_the_opus_tasks_that_wait_in_the_batch(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture, solo=False)
    fake, gear = fake_batches(approves_with_doubt), Gear(db)
    now = RUN
    for _ in range(4):  # until the Opus task is queued (stage 3), not answered
        run(db, gear, fake, at=now)
        if any(t["task_kind"] == "escalation" for t in tasks(db, w.fixture)):
            break
        now += 10 * MINUTE
        settle(db, gear, fake, at=now)
        now += 10 * MINUTE
    assert orchestrator.opus_today(db, now)[0] == 1 and orchestrator.opus_today(db, now)[1] > 0  # type: ignore[attr-defined]


# ── what the Batch can do wrong ───────────────────────────────────────────────────────────────────────────────────

def test_an_item_that_errors_leaves_its_arm_a_fallback_with_the_code_and_nothing_is_asked_in_real_time(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear, pv = fake_batches(), Gear(db), provider()
    run(db, gear, fake, prov=pv)
    evaluation = next(t for t in tasks(db, w.fixture) if t["task_kind"] == "evaluation")
    settle(db, gear, fake, at=RUN + 20 * MINUTE, outcomes={evaluation["route"]["batch_custom_id"]: "errored"})
    second = run(db, gear, fake, at=RUN + 30 * MINUTE, prov=pv)
    assert second.queued == 2 and len(fake.created) == 2, "the Councils that read assessments go on with what the Match Agent gave (fail open)"
    reports = to_the_end(db, gear, fake, start=RUN + 40 * MINUTE, prov=pv)
    assert reports[-1].ran == 1 and pv.requests == [], "no retry in real time, no paid call"
    failed = next(t for t in tasks(db, w.fixture) if t["idem_key"] == evaluation["idem_key"])
    assert failed["state"] == "failed" and failed["run_status"] == "skipped"
    [run_row] = rows(db, "SELECT * FROM ai.agent_runs WHERE idem_key = %s", failed["idem_key"])
    assert run_row["error"].startswith("batch_errored") and run_row["cost_usd"] == 0 and run_row["input_tokens"] is None
    assert {r["decision"] for r in reviews(db, w.fixture, "cs-v1")} == {"APPROVE"}, "the arm that reads no assessment is untouched"


def test_every_arm_that_needed_a_lost_item_is_a_fallback_and_the_others_stand(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(), Gear(db)
    run(db, gear, fake)
    solo = next(t for t in tasks(db, w.fixture) if t["task_kind"] == "council")
    settle(db, gear, fake, at=RUN + 20 * MINUTE, outcomes={solo["route"]["batch_custom_id"]: "expired"})
    reports = to_the_end(db, gear, fake, start=RUN + 30 * MINUTE)
    assert reports[-1].ran == 1
    cs = reviews(db, w.fixture, "cs-v1")
    assert {(r["decision"], r["status"]) for r in cs} == {("ABSTAIN", "fallback")} and all(r["output"]["reason"] == "batch_expired" for r in cs)
    assert {r["decision"] for r in reviews(db, w.fixture, "ma-v1", "ma-v1-h")} == {"APPROVE"}
    [dead] = [t for t in tasks(db, w.fixture) if t["idem_key"] == solo["idem_key"]]
    assert dead["state"] == "expired" and dead["run_status"] == "expired"
    [state] = rows(db, "SELECT final FROM ai.match_runs WHERE run_kind = 'shadow'")
    assert state["final"]["engines"]["cs-v1"]["status"] == "fallback" and state["final"]["engines"]["cs-v1"]["reason"] == "batch_expired"


def test_a_cancelled_item_is_a_fallback_and_costs_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(), Gear(db)
    run(db, gear, fake)
    solo = next(t for t in tasks(db, w.fixture) if t["task_kind"] == "council")
    settle(db, gear, fake, at=RUN + 20 * MINUTE, outcomes={solo["route"]["batch_custom_id"]: "canceled"})
    reports = to_the_end(db, gear, fake, start=RUN + 30 * MINUTE)
    assert reports[-1].ran == 1
    assert {r["output"]["reason"] for r in reviews(db, w.fixture, "cs-v1")} == {"batch_canceled"}
    [dead] = [t for t in tasks(db, w.fixture) if t["idem_key"] == solo["idem_key"]]
    assert dead["state"] == "skipped" and dead["run_status"] == "skipped"


def test_an_answer_the_contract_refuses_is_invalid_and_paid_like_in_real_time(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)

    def asks(request: JsonRequest) -> dict[str, Any]:
        return answer_for(request, extra={"escalate": True}) if request.schema_name == council.TOOL else answer_for(request)

    reports = to_the_end(db, Gear(db), fake_batches(asks))
    assert reports[-1].ran == 1
    assert {(r["decision"], r["status"]) for r in reviews(db, w.fixture)} == {("ABSTAIN", "invalid_output")}
    invalid = [t for t in tasks(db, w.fixture) if t["task_kind"] == "council"]
    assert {t["run_status"] for t in invalid} == {"invalid"}


def test_an_estimate_that_does_not_fit_queues_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake = fake_batches()
    before = counts(db)
    report = run(db, Gear(db), fake, conf=cfg(lab_monthly_budget=D("0.0005")))
    assert report.budget_stop in ("insufficient", "allocation_spent") and report.queued == 0 and report.waiting == 0
    assert fake.created == [] and counts(db) == before and items(db) == []
    none = run(db, Gear(db), fake, conf=cfg(lab_monthly_budget=D(0)))
    assert none.budget_stop == "no_envelope" and counts(db) == before
    later = run(db, Gear(db), fake)
    assert later.queued == 3, "with the envelope, the same pass is queued"


def test_the_open_items_reserve_their_estimate_in_the_labs_day(db: psycopg.Connection[Any], seed: Seed) -> None:
    from fbi.ai.budget_v3 import lab_day

    w = world(db, seed)
    assign(db, w.fixture)
    room_before = lab_day(db, at=RUN, settings=cfg()).remaining
    run(db, Gear(db), fake_batches())
    held = sum((i["est_cost_usd"] for i in items(db)), D(0))
    assert held > 0 and lab_day(db, at=RUN, settings=cfg()).remaining <= room_before - held + D("0.000001")


def test_an_item_still_open_at_t_minus_100_ends_the_pass_too_late_and_is_never_asked_in_real_time(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear, pv = fake_batches(), Gear(db), provider()
    run(db, gear, fake, prov=pv)
    late = KICKOFF - 99 * MINUTE
    report = run(db, gear, fake, at=late, prov=pv)
    assert pv.requests == [] and report.ran == 1 and report.abandoned >= 3 and report.calls == 0
    [state] = rows(db, "SELECT final FROM ai.match_runs WHERE run_kind = 'shadow'")
    assert state["final"]["too_late"] is True and {e["status"] for e in state["final"]["engines"].values()} == {"fallback"}
    assert {e["reason"] for e in state["final"]["engines"].values()} == {"batch_too_late"}
    ts = tasks(db, w.fixture)
    assert {t["state"] for t in ts} == {"expired"} and {t["run_status"] for t in ts} == {"expired"}
    rs = reviews(db, w.fixture)
    assert len(rs) == 9 and {r["decision"] for r in rs} == {"ABSTAIN"} and {r["status"] for r in rs} == {"fallback"}
    assert run(db, gear, fake, at=late + 5 * MINUTE).considered == 0


def test_a_pass_still_waiting_at_t_minus_101_is_left_alone(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(), Gear(db)
    run(db, gear, fake)
    report = run(db, gear, fake, at=KICKOFF - 101 * MINUTE)
    assert report.considered == 0 and counts(db)["ai.match_runs"] == 0
    assert w.fixture


def test_a_stage_that_cannot_be_queued_in_time_ends_the_pass_too_late_with_what_stage_one_gave(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear, pv = fake_batches(), Gear(db), provider()
    run(db, gear, fake, prov=pv)
    settle(db, gear, fake, at=KICKOFF - 130 * MINUTE)
    report = run(db, gear, fake, at=KICKOFF - 125 * MINUTE, prov=pv)
    assert pv.requests == [] and report.ran == 1 and report.queued == 0 and len(fake.created) == 1
    assert {r["decision"] for r in reviews(db, w.fixture, "cs-v1")} == {"APPROVE"}, "the arm that needed no assessment has its answer"
    ma = reviews(db, w.fixture, "ma-v1", "ma-v1-h")
    assert {r["decision"] for r in ma} == {"ABSTAIN"} and {r["output"]["reason"] for r in ma} == {"batch_too_late"}
    [state] = rows(db, "SELECT final FROM ai.match_runs WHERE run_kind = 'shadow'")
    assert state["final"]["too_late"] is True


def test_a_batch_that_cannot_be_created_because_of_the_workspace_limit_is_exhausted_and_not_retried_for_ever(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    other = twin(db, w)
    assign(db, other)
    fake, gear, pv = fake_batches(limit="workspace_limit"), Gear(db), provider()
    first = run(db, gear, fake, prov=pv)
    assert first.budget_stop == "exhausted" and fake.created == [] and first.waiting == 1, "the second match is not tried"
    assert {i["status"] for i in items(db)} == {"abandoned"} and len(tasks(db, w.fixture) + tasks(db, other)) == 3
    again = run(db, gear, fake, at=RUN + 10 * MINUTE, prov=pv)
    assert pv.requests == [] and fake.created == []
    assert again.ran >= 1, "the limit is on: the abandoned items are not asked again, the pass ends with fallbacks"
    done = next(f for f in (w.fixture, other) if reviews(db, f))
    assert {r["decision"] for r in reviews(db, done)} == {"ABSTAIN"}
    assert {r["status"] for r in reviews(db, done)} <= {"fallback", "over_budget"}
    assert rows(db, "SELECT count(*) AS n FROM ai.batch_items")[0]["n"] <= 6


def test_an_item_abandoned_before_it_was_sent_is_asked_again_by_the_queue(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(fail_create="unavailable"), Gear(db)
    run(db, gear, fake)
    assert fake.created == [] and {i["status"] for i in items(db)} == {"abandoned"}
    fake.fail_create = None
    again = run(db, gear, fake, at=RUN + 10 * MINUTE)
    assert again.queued == 3 and len(fake.created) == 1 and len(tasks(db, w.fixture)) == 3, "the same three tasks, now sent"
    assert {t["state"] for t in tasks(db, w.fixture)} == {"queued"} and all(t["batch_id"] for t in tasks(db, w.fixture))
    assert {i["status"] for i in items(db) if i["created_at"] > RUN} == {"submitted"}
    third = run(db, gear, fake, at=RUN + 20 * MINUTE)
    assert third.considered == 0
    reports = to_the_end(db, gear, fake, start=RUN + 30 * MINUTE)
    assert reports[-1].ran == 1


def test_the_tasks_of_a_match_that_started_are_ended_and_nothing_stays_queued(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(), Gear(db)
    run(db, gear, fake)
    report = run(db, gear, fake, at=KICKOFF + MINUTE)
    assert report.considered == 0
    ts = tasks(db, w.fixture)
    assert {t["state"] for t in ts} == {"expired"} and {t["run_status"] for t in ts} == {"expired"}
    assert rows(db, "SELECT error FROM ai.agent_runs WHERE fixture_id = %s", w.fixture)[0]["error"] == "kickoff_passed"
    assert counts(db)["ai.match_runs"] == 0


def test_a_package_that_changed_under_a_waiting_pass_ends_it_without_asking_again(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear, pv = fake_batches(), Gear(db), provider()
    run(db, gear, fake, prov=pv)
    settle(db, gear, fake, at=RUN + 20 * MINUTE)
    db.execute("SET LOCAL fbi.ai_maintenance = 'on'")
    db.execute("UPDATE ai.agent_tasks SET package_hash = %s WHERE fixture_id = %s", ("0" * 64, w.fixture))
    db.execute("SET LOCAL fbi.ai_maintenance = 'off'")
    report = run(db, gear, fake, at=RUN + 30 * MINUTE, prov=pv)
    assert pv.requests == [] and len(fake.created) == 1 and report.not_run == 1 and report.abandoned == 3
    [state] = rows(db, "SELECT final FROM ai.match_runs WHERE run_kind = 'shadow'")
    assert state["final"]["status"] == "not_run" and state["final"]["reason"] == "package_changed"
    assert {t["state"] for t in tasks(db, w.fixture)} == {"expired"}


# ── what stays in real time ───────────────────────────────────────────────────────────────────────────────────────

def test_a_final_pass_is_asked_in_real_time_whatever_the_switch_says(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed, pass_kind="final")
    assign(db, w.fixture)
    fake, pv = fake_batches(), provider()
    report = run(db, Gear(db), fake, prov=pv)
    assert report.ran == 1 and report.queued == 0 and report.calls == 5 == len(pv.requests) and fake.created == [] and items(db) == []
    assert {t["state"] for t in tasks(db, w.fixture)} == {"done"} and all("mode" not in t["route"] for t in tasks(db, w.fixture))


def test_a_pass_too_near_for_the_batch_is_asked_in_real_time(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, pv = fake_batches(), provider()
    report = run(db, Gear(db), fake, prov=pv, at=KICKOFF - 3 * H)
    assert report.ran == 1 and report.queued == 0 and len(pv.requests) == 5 and fake.created == [] and items(db) == []


def test_without_the_batch_switch_or_its_gate_the_far_pass_is_asked_in_real_time_as_before(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, pv = fake_batches(), provider()
    report = run(db, Gear(db), fake, prov=pv, conf=settings())
    assert report.ran == 1 and report.queued == 0 and len(pv.requests) == 5 and fake.created == [] and items(db) == []
    assert w.fixture


def test_with_the_shadow_off_nothing_changes(db: psycopg.Connection[Any], seed: Seed) -> None:
    world(db, seed)
    before = counts(db)
    for over in ({"shadow_sample": D(0)}, {"agents": ()}, {"mode": "off"}):
        report = run(db, Gear(db), fake_batches(), conf=cfg(**over))
        assert report.skipped == "off" and report.queued == 0
    assert counts(db) == before and items(db) == []


# ── the poll's handler ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_poll_keeps_the_raw_answer_of_a_shadow_item_and_nothing_else(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(), Gear(db)
    run(db, gear, fake)
    polled = settle(db, gear, fake, at=RUN + 20 * MINUTE)
    assert polled.counts == {"succeeded": 3} and polled.cost_usd > 0
    for i in items(db):
        res = i["context"]["result"]
        assert res["shadow"] == 1 and res["ok"] is True and isinstance(res["data"], dict) and res["data"]["contract"] in ("aa-v1", "cd-v1")
        assert res["usage_id"] == i["usage_id"] and res["model"] == i["model"] and res["late"] is False
    assert counts(db)["ai.agent_runs"] == 0 and counts(db)["ai.match_runs"] == 0 and counts(db)["ai.pick_reviews"] == 3, "the poll writes no run, no state, no review"
    assert {t["state"] for t in tasks(db, w.fixture)} == {"queued"}


def test_a_shadow_answer_settled_twice_is_the_same_answer(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(), Gear(db)
    run(db, gear, fake)
    settle(db, gear, fake, at=RUN + 20 * MINUTE)
    again = batch.poll(Savepoints(db), cfg(), at=RUN + 25 * MINUTE, ledger=gear.ledger, client=fake)  # type: ignore[arg-type]
    assert again.items == 0 and again.batches == 0, "an ended batch is not taken twice"
    item = items(db)[0]
    first = dict(item["context"]["result"])
    resolved = Resolved(item, LlmResult(first["data"], LlmUsage(input_tokens=10, output_tokens=5), "anthropic", str(item["model"]), latency_ms=0), None, item["usage_id"], D(first["cost"]), RUN, False, int(item["batch_id"]))
    lab.settle_lab(Savepoints(db), resolved)  # type: ignore[arg-type]
    lab.settle_lab(Savepoints(db), resolved)  # type: ignore[arg-type]
    assert items(db)[0]["context"]["result"]["data"] == first["data"] and items(db)[0]["context"]["result"]["ok"] is True
    reports = to_the_end(db, gear, fake, start=RUN + 40 * MINUTE)
    assert reports[-1].ran == 1
    assert rows(db, "SELECT count(*) AS n FROM (SELECT idem_key FROM ai.agent_runs WHERE status IN ('ok', 'invalid', 'abstain') GROUP BY 1 HAVING count(*) > 1) x")[0]["n"] == 0


def test_a_shadow_item_the_provider_answered_with_nothing_readable_is_an_invalid_arm(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    fake, gear = fake_batches(), Gear(db)
    run(db, gear, fake)
    solo = next(t for t in tasks(db, w.fixture) if t["task_kind"] == "council")
    settle(db, gear, fake, at=RUN + 20 * MINUTE, outcomes={solo["route"]["batch_custom_id"]: "cut"})
    reports = to_the_end(db, gear, fake, start=RUN + 30 * MINUTE)
    assert reports[-1].ran == 1
    assert {(r["decision"], r["status"]) for r in reviews(db, w.fixture, "cs-v1")} == {("ABSTAIN", "invalid_output")}


# ── what text cannot do ───────────────────────────────────────────────────────────────────────────────────────────

def test_an_order_in_the_text_of_the_evidence_is_data_through_the_batch_too(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, evidence_id = injected(db, seed)
    assign(db, w.fixture)
    seen: list[JsonRequest] = []

    def obeys(request: JsonRequest) -> dict[str, Any]:
        seen.append(request)
        if INJECTION in request.user and request.schema_name == council.TOOL:
            data = answer_for(request, verdict="APPROVE", confidence="HIGH")
            for v in data["verdicts"]:
                v["refs"] = ["E:999"]
            return data
        return answer_for(request)

    before = counts(db)
    reports = to_the_end(db, Gear(db), fake_batches(obeys))
    after = counts(db)
    assert reports[-1].ran == 1 and reports[-1].failed_open == 0
    councils = [r for r in seen if r.schema_name == council.TOOL]
    assert councils and all(INJECTION in r.user for r in councils)
    [item] = json.loads(councils[0].user)["view"]["evidence"]
    assert item["id"] == evidence_id and "untrusted" in json.dumps(item)
    assert not [r for r in seen if r.system == council.SYSTEM_OF["critical"]], "nothing escalated"
    shadow = reviews(db, w.fixture)
    assert shadow and all(r["decision"] != "APPROVE" for r in shadow) and all(r["confidence"] != D("0.850") for r in shadow)
    assert after["ai.evidence"] == before["ai.evidence"] and after["ai.fixture_passes"] == before["ai.fixture_passes"]


def test_the_reviews_of_production_are_as_they_were(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    to_the_end(db, Gear(db), fake_batches())
    after = rows(db, "SELECT id FROM ai.pick_reviews WHERE engine = 'rules' AND fixture_id = %s ORDER BY id", w.fixture)
    assert [r["id"] for r in after] == w.reviews
    assert opus_calls(provider()) == []
