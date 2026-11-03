"""The Batch calendar of the shadow without a database (``fbi.ai.orchestrator``, ``fbi.ai.orchestrator_store``, ``fbi.ai.lab``): the constants, the codes a batch
item that gave no answer is stored with, the poll's handler for ``context.lab = 'shadow'``, and the one place where a task of a pass of the Batch is queued,
read or given up (``_Runner.ask_batch``) with a scripted queue and scripted rows."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fbi.ai import batch, lab, orchestrator, router, runtime
from fbi.ai.agents.registry import REGISTRY
from fbi.ai.batch import Admission, Resolved
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.orchestrator import Asked, BatchRun
from fbi.ai.orchestrator_store import ABANDON_BEFORE, PENDING_SQL, StoredTask, TaskRecord, Work
from fbi.ai.providers.base import JsonRequest, LlmResult, LlmUsage, ProviderError

D = Decimal
AT = datetime(2032, 10, 5, 14, 0, tzinfo=UTC)
KICKOFF = AT + timedelta(hours=8)
HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
TIERS = {"bulk": TierModel("anthropic", HAIKU), "analysis": TierModel("anthropic", SONNET), "final": TierModel("anthropic", OPUS)}
MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0111_ia_phase1_agent_tasks_runs_state.py"


def settings(**over: Any) -> AiSettings:
    base: dict[str, Any] = {"tiers": dict(TIERS), "keys": {"anthropic": "k"}, "lab_keys": {"anthropic": "l"}, "engines": ("rules", "llm", "ma-v1", "ma-v1-h", "cs-v1"),
                            "shadow_sample": D(1), "agents": ("match", "council")}
    return AiSettings(**(base | over))


# ── the constants ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_calendar_gives_up_at_the_minute_the_final_pass_starts_and_queues_no_stage_it_could_not_wait_for() -> None:
    assert timedelta(minutes=100) == ABANDON_BEFORE, "the final pass starts when the match is 100 minutes away (runtime.due_pass)"
    assert orchestrator.BATCH_DEADLINE == batch.DEADLINE_MARGIN == timedelta(minutes=60)
    assert orchestrator.STAGE_MIN_LEAD == ABANDON_BEFORE + orchestrator.BATCH_DEADLINE == timedelta(minutes=160)
    assert orchestrator.STAGE_MIN_LEAD > runtime.FINAL_MARGIN


def test_the_codes_of_an_item_that_gave_no_answer_are_runs_and_tasks_the_tables_have_and_none_is_paid() -> None:
    assert set(orchestrator.BATCH_CODES) == {"errored", "canceled", "expired", "abandoned", "missing", "too_late"}
    for status, state in orchestrator.BATCH_CODES.values():
        assert status in ("skipped", "expired") and state in ("failed", "skipped", "expired"), "a run that is not paid, a task that ends"
    assert [f"batch_{k}" for k in orchestrator.BATCH_CODES] == ["batch_errored", "batch_canceled", "batch_expired", "batch_abandoned", "batch_missing", "batch_too_late"]


def test_every_state_the_end_of_a_queued_task_goes_through_is_a_line_the_guard_allows() -> None:
    guard = MIGRATION.read_text(encoding="utf-8")
    for line in ("('queued', 'running')", "('running', 'done')", "('running', 'failed')", "('running', 'expired')", "('running', 'skipped')"):
        assert line in guard, line


def test_the_report_counts_what_the_calendar_did() -> None:
    out = orchestrator.Report(queued=3, waiting=1, settled=2, abandoned=4).to_json()
    assert (out["queued"], out["waiting"], out["settled"], out["abandoned"]) == (3, 1, 2, 4)
    assert {"queued", "waiting", "settled", "abandoned"} <= {f.name for f in dataclasses.fields(orchestrator.Report)}
    assert orchestrator.Report().to_json()["queued"] == 0


def test_a_waiting_batch_pass_is_selected_again_only_when_no_item_is_open_or_the_time_to_give_up_has_come() -> None:
    assert "t.route ->> 'mode' IS DISTINCT FROM 'batch'" in PENDING_SQL
    assert "bi.status IN ('submitting', 'submitted')" in PENDING_SQL and "f.kickoff_at - %(abandon)s > %(at)s" in PENDING_SQL


# ── the poll's handler ────────────────────────────────────────────────────────────────────────────────────────────

def resolved(result: LlmResult | None, error: ProviderError | None = None, *, late: bool = False) -> Resolved:
    item = {"id": 7, "custom_id": "c" * 48, "purpose": "other", "tier": "analysis", "model": SONNET, "fixture_id": 5, "input_hash": "h", "prompt_version": "council-v1",
            "deadline_at": KICKOFF, "context": {"lab": "shadow", "idem": "k" * 64}}
    return Resolved(item, result, error, 31, D("0.004"), AT, late, 2)


def test_the_handler_of_a_shadow_item_keeps_the_raw_answer_and_validates_nothing() -> None:
    data = {"contract": "cd-v1", "verdicts": [{"candidate": "c99", "verdict": "APPROVE"}], "anything": ["the contract may refuse"]}
    got = lab._settle_shadow(resolved(LlmResult(data, LlmUsage(input_tokens=10, output_tokens=5), "anthropic", SONNET, latency_ms=0, extra={"stop_reason": "end_turn"})))
    assert got["shadow"] == 1 and got["ok"] is True and got["data"] == data and got["usage_id"] == 31 and got["cost"] == "0.004"
    assert got["model"] == SONNET and got["late"] is False and got["stop_reason"] == "end_turn"
    again = lab._settle_shadow(resolved(LlmResult(data, LlmUsage(input_tokens=10, output_tokens=5), "anthropic", SONNET, latency_ms=0, extra={"stop_reason": "end_turn"})))
    assert again == got, "the same answer settled twice is the same summary"


def test_an_answer_that_could_not_be_read_is_kept_as_such_with_its_code() -> None:
    got = lab._settle_shadow(resolved(None, ProviderError("refused", "no")))
    assert got["ok"] is False and got["error"] == "refused" and "data" not in got
    assert lab._settle_shadow(resolved(None, None))["error"] == "invalid_output"
    assert lab._settle_shadow(resolved(None, ProviderError("invalid_output", "x"), late=True))["late"] is True


class Conn:
    """A connection that only records the statement of the handler."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    def cursor(self, **kw: Any) -> Conn:
        return self

    def __enter__(self) -> Conn:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def execute(self, sql: str, params: Any) -> None:
        self.statements.append((sql, params))


def test_the_lab_handler_has_a_branch_for_shadow_and_stores_it_under_result_in_the_item() -> None:
    conn = Conn()
    lab.settle_lab(conn, resolved(LlmResult({"contract": "aa-v1"}, LlmUsage(input_tokens=1, output_tokens=1), "anthropic", SONNET, latency_ms=0)))  # type: ignore[arg-type]
    [(sql, params)] = conn.statements
    assert "UPDATE ai.batch_items SET context = context ||" in sql and params[1] == 7
    assert params[0].obj["result"]["data"] == {"contract": "aa-v1"}
    with pytest.raises(ValueError):
        lab.settle_lab(conn, dataclasses.replace(resolved(None), item={"id": 1, "context": {"lab": "something else"}}))  # type: ignore[arg-type]
    assert batch.handler_for("other") is lab.settle_lab


# ── the one place where a task of a pass of the Batch is queued, read or given up ──────────────────────────────

class Queue:
    """A scripted ``BatchQueue``: what it admits, and what it was asked."""

    def __init__(self, admission: Admission | None = None) -> None:
        self.admission = admission or Admission("queued", "q" * 48, est_cost=D("0.01"))
        self.tasks: list[batch.Task] = []

    def add(self, task: batch.Task) -> Admission:
        self.tasks.append(task)
        return self.admission


class Rig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, stored: dict[str, StoredTask] | None = None, kickoff: datetime = KICKOFF, now: datetime = AT,
                 admission: Admission | None = None, cfg: AiSettings | None = None, gate: bool = True) -> None:
        self.rows = dict(stored or {})
        self.queue = Queue(admission)
        self.inserted: list[TaskRecord] = []
        monkeypatch.setattr(orchestrator, "batch_task", lambda conn, key: self.rows.get(key))
        monkeypatch.setattr(orchestrator, "existing", lambda conn, key: None)
        monkeypatch.setattr(orchestrator, "open_batch_of", lambda conn, cid: 9)
        monkeypatch.setattr(orchestrator, "link_batch", lambda conn, task, batch_id: None)
        monkeypatch.setattr(orchestrator.gates, "enabled", lambda *a, **kw: gate)
        clock = SimpleNamespace(now=now)
        self.runner = orchestrator._Runner(object(), cfg or settings(), at=AT, limit=20, max_seconds=240.0, provider=None, transport=None, ledger=None,  # type: ignore[arg-type]
                                           slots=runtime.Slots(), circuit=runtime.Circuit(), monotonic=lambda: 0.0, sleep=lambda s: None)
        monkeypatch.setattr(self.runner, "clock", lambda: clock.now)
        self.clock = clock

        def queue_row(conn: Any, rec: TaskRecord, *, custom_id: str, batch_id: int | None) -> int:
            self.inserted.append(rec)
            self.rows[rec.identity.key] = StoredTask(task_id=len(self.inserted), key=rec.identity.key, state="queued", task_kind=rec.task_kind,
                                                     route=rec.route | {"batch_custom_id": custom_id, "mode": "batch"}, package_hash=None, created_at=AT, deadline_at=KICKOFF,
                                                     item_status="submitting")
            return len(self.inserted)

        monkeypatch.setattr(orchestrator, "queue_task", queue_row)
        monkeypatch.setattr(self.runner, "record", lambda p, a: TaskRecord(identity=a.identity, task_kind=a.task_kind, reason="r", route={"packet_id": 9}, est_cost=a.est, priority=1,
                                                                           deadline_at=KICKOFF, state="queued", status="skipped", started_at=AT, finished_at=AT, known_at=AT - timedelta(hours=1),
                                                                           package_hash="p" * 64, slice_hash="s" * 64))
        work = Work(fixture_id=5, pass_kind="pre", packet_id=9, known_at=AT - timedelta(hours=1), kickoff_at=kickoff, passed_at=AT)
        self.p = SimpleNamespace(work=work, asked={}, batch=BatchRun(queue=self.queue, active=("ma-v1",)), too_late=False, engines=("ma-v1",))  # type: ignore[arg-type]
        self.n = 0

    def ask(self, *, model: str = SONNET, level: str = "complex", call: bool = True, key: str | None = None, stage: int = 1) -> Asked:
        self.n += 1
        identity = REGISTRY.identity_for("council", "council", workspace="lab", input_version="council-view-v1", input_hash=f"{self.n if key is None else key:0>64}",
                                         pass_kind="pre", fixture_id=5, candidates=("c1", "c2"), model=model)
        decision = router.Decision(task="council", action="CALL" if call else "SKIP", rule="task", reasons=() if call else ("daily_cap",))
        request = JsonRequest(system="s", user="u", schema={}, schema_name="submit_council", max_tokens=1000)
        return self.runner.ask(self.p, identity=identity, task_kind="council", level=level, request=request, purpose="pick_review", prompt_version="council-v1",  # type: ignore[arg-type]
                               input_hash="h", decision=decision, model=model, agent="council", stage=stage)

    def stored(self, asked: Asked, **over: Any) -> StoredTask:
        base: dict[str, Any] = {
            "task_id": 1,
            "key": asked.key,
            "state": "queued",
            "task_kind": "council",
            "route": {"batch_custom_id": "c" * 48, "mode": "batch"},
            "package_hash": None,
            "created_at": AT - timedelta(minutes=30),
            "deadline_at": KICKOFF,
            "item_status": "submitted",
            "item_model": SONNET,
            "usage_id": 31,
            "item_batch": 2,
            "cost": D("0.004"),
        }
        return StoredTask(**(base | over))


def key_of(rig: Rig, n: int) -> str:
    return REGISTRY.identity_for("council", "council", workspace="lab", input_version="council-view-v1", input_hash=f"{n:0>64}", pass_kind="pre", fixture_id=5,
                                 candidates=("c1", "c2"), model=SONNET).key


def test_a_new_task_is_queued_as_a_task_of_the_lab_with_the_context_the_handler_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch)
    asked = rig.ask()
    [task] = rig.queue.tasks
    assert task.purpose == "other" and task.lab is True and task.agent == "council" and task.tier == "analysis" and task.fixture_id == 5
    assert task.deadline_at == KICKOFF - timedelta(minutes=60) and task.typical_output == 500
    assert task.context["lab"] == "shadow" and task.context["idem"] == asked.key and task.context["stage"] == 1 and task.context["packet_id"] == 9
    assert asked.pending and asked.queued_here and asked.batch_task == 1 and asked.calls == 0 and asked.data is None and not asked.answered
    assert rig.runner.tally.calls == 0 and rig.p.batch.queued_now == 1
    [rec] = rig.inserted
    assert rec.state == "queued" and rec.route["stage"] == 1 and rec.route["active"] == ["ma-v1"] and rec.deadline_at == KICKOFF - timedelta(minutes=60)


def test_a_new_task_is_never_a_call_in_real_time(monkeypatch: pytest.MonkeyPatch) -> None:
    import fbi.ai.usage as usage

    def forbidden(*a: Any, **kw: Any) -> Any:
        raise AssertionError("a pass of the Batch asked in real time")

    monkeypatch.setattr(usage, "call_json", forbidden)
    rig = Rig(monkeypatch)
    rig.ask()
    rig.ask(call=False)
    rig.ask(stage=3, level="critical", model=OPUS)


def test_the_router_saying_no_or_an_exhausted_run_queues_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch)
    no = rig.ask(call=False)
    assert rig.queue.tasks == [] and (no.skip, no.status, no.state) == ("daily_cap", "budget_skip", "skipped")
    rig.runner.exhausted = True
    done = rig.ask()
    assert rig.queue.tasks == [] and done.skip == "exhausted"


def test_a_stage_that_cannot_wait_for_its_answer_before_the_final_pass_is_given_up_not_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch, kickoff=AT + orchestrator.STAGE_MIN_LEAD - timedelta(seconds=1))
    asked = rig.ask(stage=2)
    assert rig.queue.tasks == [] and asked.skip == "batch_too_late" and (asked.status, asked.state) == ("expired", "expired") and rig.p.too_late is True
    assert rig.runner.tally.abandoned == 1 and not asked.pending
    roomy = Rig(monkeypatch, kickoff=AT + orchestrator.STAGE_MIN_LEAD)
    assert roomy.ask(stage=2).pending


def test_a_later_stage_needs_the_batch_gate_still_on_for_its_model(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch, gate=False)
    assert rig.ask(stage=2).skip == "batch_off" and rig.queue.tasks == []
    first = Rig(monkeypatch, gate=False)
    assert first.ask(stage=1).pending, "stage 1 was decided with the gate when the pass started"


def test_a_model_that_is_not_the_configured_one_is_not_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch)
    asked = rig.ask(model=HAIKU)
    assert asked.skip == "model_not_configured" and rig.queue.tasks == []


@pytest.mark.parametrize("reason, skip, status", [("lab_budget", "lab_envelope", "budget_skip"), ("attempts", "batch_refused_attempts", "skipped"), ("no_model", "batch_refused_no_model", "skipped")])
def test_a_task_the_queue_refuses_is_a_skip_with_the_reason_and_nothing_is_stored(monkeypatch: pytest.MonkeyPatch, reason: str, skip: str, status: str) -> None:
    rig = Rig(monkeypatch, admission=Admission("refused", "", reason))
    asked = rig.ask()
    assert (asked.skip, asked.status) == (skip, status) and rig.inserted == [] and not asked.pending and asked.batch_task is None


def test_a_stored_task_whose_item_is_open_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch)
    probe = rig.ask(key="a")
    rig2 = Rig(monkeypatch)
    rig2.p.batch.stored[probe.key] = rig2.stored(probe)
    rig2.rows[probe.key] = rig2.stored(probe)
    waiting = rig2.ask(key="a")
    assert waiting.pending and waiting.batch_task == 1 and rig2.queue.tasks == [] and waiting.started == AT - timedelta(minutes=30)


def test_an_item_still_open_at_the_minute_the_final_pass_starts_is_given_up(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Rig(monkeypatch).ask(key="a")
    rig = Rig(monkeypatch, kickoff=AT + ABANDON_BEFORE)
    rig.p.batch.stored[probe.key] = rig.stored(probe)
    asked = rig.ask(key="a")
    assert asked.skip == "batch_too_late" and not asked.pending and asked.batch_task == 1 and rig.p.too_late
    before = Rig(monkeypatch, kickoff=AT + ABANDON_BEFORE + timedelta(seconds=1))
    before.p.batch.stored[probe.key] = before.stored(probe)
    assert before.ask(key="a").pending


def test_an_answered_item_becomes_a_task_answered_with_the_batch_price_and_the_ledger_row(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Rig(monkeypatch).ask(key="a")
    rig = Rig(monkeypatch)
    rig.p.batch.stored[probe.key] = rig.stored(probe, item_status="succeeded", result={"shadow": 1, "ok": True, "data": {"contract": "cd-v1"}}, item_idem=probe.key)
    asked = rig.ask(key="a")
    assert asked.answered and asked.data == {"contract": "cd-v1"} and asked.model == SONNET and asked.cost == D("0.004") and asked.usage_ids == [31]
    assert (asked.calls, asked.provider, asked.batch_id, asked.pending) == (1, "anthropic", 2, False)
    assert rig.runner.tally.calls == 0, "this process made no call"
    late = Rig(monkeypatch)
    late.p.batch.stored[probe.key] = late.stored(probe, item_status="late", result={"shadow": 1, "ok": True, "data": {"a": 1}}, item_idem=probe.key)
    assert late.ask(key="a").answered, "a late answer that arrives before the pass is given up is used"


def test_an_item_shared_with_another_task_is_paid_by_the_first_one_only(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Rig(monkeypatch).ask(key="a")
    rig = Rig(monkeypatch)
    rig.p.batch.stored[probe.key] = rig.stored(probe, item_status="succeeded", result={"shadow": 1, "ok": True, "data": {"x": 1}}, item_idem="z" * 64)
    asked = rig.ask(key="a")
    assert asked.answered and asked.cost == 0 and asked.usage_ids == []


def test_an_item_that_could_not_be_read_is_an_invalid_answer_that_was_paid(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Rig(monkeypatch).ask(key="a")
    rig = Rig(monkeypatch)
    rig.p.batch.stored[probe.key] = rig.stored(probe, item_status="invalid", result={"shadow": 1, "ok": False, "error": "invalid_output"}, item_idem=probe.key)
    asked = rig.ask(key="a")
    assert (asked.status, asked.state, asked.error, asked.data) == ("invalid", "done", "invalid_output", None) and asked.cost == D("0.004") and rig.runner.tally.invalid == 1
    handler = Rig(monkeypatch)
    handler.p.batch.stored[probe.key] = handler.stored(probe, item_status="invalid", result=None, item_error="handler_failed: KeyError", item_idem=probe.key)
    assert handler.ask(key="a").status == "invalid"


@pytest.mark.parametrize("item_status, code, status, state", [
    ("errored", "batch_errored", "skipped", "failed"), ("canceled", "batch_canceled", "skipped", "skipped"),
    ("expired", "batch_expired", "expired", "expired"), (None, "batch_missing", "skipped", "failed")])
def test_an_item_that_gave_no_answer_is_a_fallback_with_its_code_unpaid_and_never_asked_again(monkeypatch: pytest.MonkeyPatch, item_status: str | None, code: str, status: str, state: str) -> None:
    probe = Rig(monkeypatch).ask(key="a")
    rig = Rig(monkeypatch)
    rig.p.batch.stored[probe.key] = rig.stored(probe, item_status=item_status, item_error="overloaded_error")
    asked = rig.ask(key="a")
    assert asked.skip == code and (asked.status, asked.state) == (status, state) and asked.cost == 0 and asked.batch_task == 1 and not asked.pending
    assert rig.queue.tasks == [], "no retry"
    assert orchestrator._Runner.arm_status(asked)[0] == orchestrator.STATUS_FALLBACK and orchestrator._Runner.arm_status(asked)[1] == code


def test_an_item_abandoned_before_it_was_sent_is_asked_again_by_the_queue_and_the_stored_task_follows_it(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Rig(monkeypatch).ask(key="a")
    rig = Rig(monkeypatch)
    rig.p.batch.stored[probe.key] = rig.stored(probe, item_status="abandoned", item_error="create_failed: unavailable")
    again = dataclasses.replace(rig.stored(probe, item_status="submitting"))
    calls = {"n": 0}

    def fresh(conn: Any, key: str) -> StoredTask:
        calls["n"] += 1
        return again

    monkeypatch.setattr(orchestrator, "batch_task", fresh)
    asked = rig.ask(key="a")
    assert len(rig.queue.tasks) == 1 and asked.pending and rig.inserted == [], "the same task, not a second row"


def test_an_abandoned_item_the_queue_now_refuses_is_a_fallback_batch_abandoned(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Rig(monkeypatch).ask(key="a")
    rig = Rig(monkeypatch, admission=Admission("refused", "", "attempts"))
    rig.p.batch.stored[probe.key] = rig.stored(probe, item_status="abandoned")
    asked = rig.ask(key="a")
    assert asked.skip == "batch_abandoned" and asked.error is not None and asked.error.endswith("attempts") and not asked.pending
    assert rig.inserted == []


def test_an_abandoned_item_of_a_stage_that_is_too_late_is_not_asked_again(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Rig(monkeypatch).ask(key="a")
    rig = Rig(monkeypatch, kickoff=AT + timedelta(minutes=120))
    rig.p.batch.stored[probe.key] = rig.stored(probe, item_status="abandoned")
    asked = rig.ask(key="a")
    assert rig.queue.tasks == [] and asked.skip == "batch_too_late"


def test_the_question_of_another_pass_is_read_but_its_task_is_not_ours_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = Rig(monkeypatch).ask(key="a")
    rig = Rig(monkeypatch)
    rig.rows[probe.key] = rig.stored(probe, item_status="succeeded", result={"shadow": 1, "ok": True, "data": {"x": 1}}, item_idem=probe.key)
    asked = rig.ask(key="a")
    assert asked.answered and asked.batch_task is None and asked.cost == 0 and asked.usage_ids == []


def test_the_same_question_twice_in_a_pass_is_one_item(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch)
    first = rig.ask(key="a")
    again = rig.ask(key="a")
    assert again is first and first.shared and len(rig.queue.tasks) == 1


def test_a_task_found_ended_in_the_tables_is_read_not_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai.orchestrator_store import Existing

    rig = Rig(monkeypatch)
    monkeypatch.setattr(orchestrator, "existing", lambda conn, key: Existing(state="done", status="ok", output={"contract": "cd-v1"}, cost=D("0.5"), model=SONNET))
    asked = rig.ask()
    assert asked.reused and asked.data == {"contract": "cd-v1"} and rig.queue.tasks == []


def test_the_opus_hours_are_frozen_in_the_pass_once_read() -> None:
    p = SimpleNamespace(batch=BatchRun(queue=Queue()), work=Work(fixture_id=5, pass_kind="pre", packet_id=9, known_at=AT, kickoff_at=KICKOFF, passed_at=AT))  # type: ignore[arg-type]
    runner = orchestrator._Runner(object(), settings(), at=AT, limit=1, max_seconds=1.0, provider=None, transport=None, ledger=None,  # type: ignore[arg-type]
                                  slots=runtime.Slots(), circuit=runtime.Circuit(), monotonic=lambda: 0.0, sleep=lambda s: None)
    first = runner.hours_for(p)  # type: ignore[arg-type]
    assert first == D("8.00") and p.batch.hours == first
    p.work = dataclasses.replace(p.work, kickoff_at=KICKOFF - timedelta(hours=5))
    assert runner.hours_for(p) == first, "a later run reads the frozen hours: the rules fire on the same candidates"
    sync = SimpleNamespace(batch=None, work=p.work)
    assert runner.hours_for(sync) == D("3.00"), "in real time they are read from the clock, as before"  # type: ignore[arg-type]
