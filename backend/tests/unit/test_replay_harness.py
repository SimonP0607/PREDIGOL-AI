"""The harness of the replay bank (IA-047) without a database: what a run would ask and cost, why it may not be sent, that it
spends nothing without the owner's confirmation and the protocol, that it is all or nothing, how an answer is kept by the
worker's poll and read the way the shadow reads it - and that nothing in the bank writes a table that is not its own."""

from __future__ import annotations

import ast
import dataclasses
import inspect
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest

from fbi.ai import batch, budget_v3, lab
from fbi.ai.agents import council
from fbi.ai.batch import Admission, FlushReport, Resolved
from fbi.ai.calendar import days_left_in_month, local_day
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.pricing import token_cost
from fbi.ai.providers.base import LlmResult, LlmUsage, ProviderError
from fbi.ai.replay import REPEATS, SAME, VERSION, bank, harness, measure

from .synthetic_packet import AT
from .test_replay_bank import NAMING, SCOPES, SHADOW, inputs, stored, verdicts

D = Decimal
HAIKU, SONNET, OPUS = "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"
TIERS = {"bulk": TierModel("anthropic", HAIKU), "analysis": TierModel("anthropic", SONNET), "final": TierModel("anthropic", OPUS)}


def settings(**over: Any) -> AiSettings:
    base: dict[str, Any] = {"tiers": dict(TIERS), "keys": {"anthropic": "k"}, "lab_keys": {"anthropic": "l"}, "lab_monthly_budget": D(55)}
    return AiSettings(**(base | over))


def items() -> list[bank.Item]:
    got, excluded = bank.admit([stored(s, i) for i, s in enumerate(SCOPES, start=1)], inputs())
    assert excluded == []
    return got


def built() -> bank.Build:
    return bank.Build(tuple(items()), (), AT - timedelta(days=14), AT)


def lab_day(remaining: str = "47.86", *, allowed: bool = True, typical: str = "0.52") -> budget_v3.LabDay:
    return budget_v3.LabDay(allowed, D(55), D(55) - D(remaining), D(remaining), D(typical), "ok" if allowed else "allocation_spent")


@pytest.fixture()
def lab_now(monkeypatch: pytest.MonkeyPatch) -> dict[str, budget_v3.LabDay]:
    state = {"day": lab_day()}
    monkeypatch.setattr(budget_v3, "lab_day", lambda conn, *, at, settings: state["day"])
    monkeypatch.setattr(harness, "with_switches", lambda conn, settings, request, model: request)
    return state


# -- the asks ------------------------------------------------------------------------------------------------------------------

def test_an_ask_is_named_by_the_variant_the_stored_runs_key_and_the_repetition_and_never_by_a_run() -> None:
    k = "a" * 64
    assert harness.ask_hash(SAME, k, 1) == harness.ask_hash(SAME, k, 1)
    assert len({harness.ask_hash(SAME, k, 1), harness.ask_hash(SAME, k, 2), harness.ask_hash("other", k, 1),
                harness.ask_hash(SAME, "b" * 64, 1)}) == 4


def test_an_ask_is_a_task_of_the_lab_with_the_banks_own_version_and_no_match_and_no_agent(lab_now: dict[str, Any]) -> None:
    p = harness.plan(object(), settings(), built(), at=AT)  # type: ignore[arg-type]
    tasks = [harness.task_of(a, run_key=p.run_key, variant=SAME) for a in p.asks]
    assert len(tasks) == len(items()) * REPEATS == len(p.asks)
    for t, a in zip(tasks, p.asks, strict=True):
        assert t.purpose == "other" and t.prompt_version == VERSION and t.lab is True and t.agent is None and t.fixture_id is None
        assert t.context == {"lab": "replay", "bank": VERSION, "variant": SAME, "run": p.run_key, "item": a.item.run.id,
                             "idem": a.item.run.idem_key, "repetition": a.repetition, "scope": a.item.scope}
        assert t.request.pinned is True and t.typical_output == a.item.run.output_tokens
    ids = {batch.custom_id_of(t, str(TIERS[t.tier].model)) for t in tasks}
    assert len(ids) == len(tasks), "two repetitions are two items of the queue"
    assert ids == {batch.custom_id_of(harness.task_of(a, run_key="another run", variant=SAME), str(TIERS[a.tier].model)) for a in p.asks}, \
        "the same ask sent by another run is the same item: it is paid once"


def test_the_request_sent_is_the_agents_own_with_the_tiers_effort_and_the_switches_applied_once_then_pinned(
        monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, Any]] = []

    def switches(conn: Any, s: AiSettings, request: Any, model: str) -> Any:
        seen.append((model, request.effort))
        return dataclasses.replace(request, cache=True)

    monkeypatch.setattr(harness, "with_switches", switches)
    item = next(i for i in items() if i.scope == "council/ma-v1")
    sent = harness.sent_request(object(), settings(), item, "analysis")  # type: ignore[arg-type]
    assert seen == [(SONNET, item.ask.request.effort)] and sent.cache is True and sent.pinned is True
    assert sent.user == item.ask.request.user and sent.system == item.ask.request.system


def test_the_tier_of_a_stored_run_is_the_one_whose_model_it_ran_with() -> None:
    assert (harness.tier_of(HAIKU), harness.tier_of(SONNET), harness.tier_of(OPUS)) == ("bulk", "analysis", "final")


def test_an_ask_costs_the_stored_calls_own_tokens_at_half_price_and_the_worst_case_is_every_answer_at_its_maximum() -> None:
    item = next(i for i in items() if i.scope == "council/ma-v1")
    run = dataclasses.replace(item.run, input_tokens=7000, output_tokens=600)
    cost = harness.cost_of(run, item.ask.request, at=AT)

    def half(out: int) -> Decimal:
        return token_cost("anthropic", SONNET, input_tokens=7000, output_tokens=out, batch=True, at=AT)

    assert cost.expected == half(600) and cost.prudent == half(900) and cost.worst == half(council.MAX_TOKENS)
    assert cost.expected < cost.prudent < cost.worst
    assert cost.expected == (D(7000) * D(2) + D(600) * D(10)) / D(1_000_000) / D(2), "Sonnet 5.5: 2 and 10 USD per million, halved"
    assert harness.typical_output(run, item.ask.request) == 600
    assert harness.typical_output(dataclasses.replace(run, output_tokens=None), item.ask.request) == council.MAX_TOKENS // 2


# -- the plan --------------------------------------------------------------------------------------------------------------------

def test_a_plan_asks_every_admitted_run_twice_and_says_what_it_costs_and_what_is_left_for_the_shadow(lab_now: dict[str, Any]) -> None:
    p = harness.plan(object(), settings(), built(), at=AT)  # type: ignore[arg-type]
    assert p.sendable and p.blockers == ()
    out = p.as_json()
    assert out["items"] == 6 and out["asks"] == 12 and set(out["by_scope"]) == set(SCOPES)
    assert all(v["asks"] == 2 * v["items"] for v in out["by_scope"].values())
    assert D(out["cost"]["prudent_usd"]) <= D(out["cap_usd"]) == harness.DEFAULT_MAX_USD
    days_left = days_left_in_month(local_day(AT))
    assert p.headroom == (2 * D("0.52") * days_left).quantize(D("0.01")) and days_left == 7, "25 Oct 2026: seven days to the end"
    assert out["lab_left_after_worst_case_usd"] == str((D("47.86") - p.cost.worst).quantize(D("0.0001")))
    assert p.run_key.startswith(f"{VERSION}:{SAME}:") and p.run_key == harness.plan(object(), settings(), built(), at=AT).run_key  # type: ignore[arg-type]


@pytest.mark.parametrize("change, blocker", [
    ({"max_usd": D("0.0001")}, "over the cap of the run"),
    ({"max_usd": D("15.01")}, "at most 15.0000 USD"),
    ({"lab": lab_day("0.80")}, "kept for the shadow"),
    ({"lab": lab_day(allowed=False)}, "the LAB may not spend today (allocation_spent)"),
    ({"settings": {"lab_keys": {}}}, "no LAB key"),
    ({"settings": {"lab_monthly_budget": D(0)}}, "the LAB has no envelope"),
    ({"settings": {"tiers": TIERS | {"analysis": TierModel("anthropic", OPUS)}}}, "never asked on another model"),
])
def test_a_plan_says_every_reason_it_may_not_be_sent(lab_now: dict[str, Any], change: dict[str, Any], blocker: str) -> None:
    if "lab" in change:
        lab_now["day"] = change["lab"]
    p = harness.plan(object(), settings(**change.get("settings", {})), built(), at=AT,  # type: ignore[arg-type]
                     max_usd=change.get("max_usd", harness.DEFAULT_MAX_USD))
    assert not p.sendable and any(blocker in b for b in p.blockers), p.blockers


def test_a_plan_of_nothing_is_not_sendable_and_only_the_variant_of_the_stored_run_exists_today(lab_now: dict[str, Any]) -> None:
    p = harness.plan(object(), settings(), bank.Build((), ()), at=AT)  # type: ignore[arg-type]
    assert not p.sendable and "nothing to ask: no admitted run in the selection" in p.blockers
    with pytest.raises(ValueError):
        harness.plan(object(), settings(), built(), at=AT, variant="match-v6")  # type: ignore[arg-type]


def test_a_plan_narrowed_to_a_scope_and_a_limit_asks_only_those(lab_now: dict[str, Any]) -> None:
    p = harness.plan(object(), settings(), built(), at=AT, scopes=["council/ma-v1"], limit_per_scope=1)  # type: ignore[arg-type]
    assert {a.item.scope for a in p.asks} == {"council/ma-v1"} and len(p.asks) == REPEATS
    assert p.selected_by["scopes"] == ["council/ma-v1"] and p.selected_by["limit_per_scope"] == 1


# -- the run -----------------------------------------------------------------------------------------------------------------------

class Conn:
    """Records every statement; answers the bank's id lookup."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, **kw: Any) -> Conn:
        return self

    def __enter__(self) -> Conn:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.statements.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return [(r, 100 + r) for r in self.statements[-1][1]["runs"]] if "source_run_id = ANY" in self.statements[-1][0] else []

    def fetchone(self) -> tuple[Any, ...] | None:
        return (1,)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class Queue:
    """A scripted ``BatchQueue``: what it admits, what it was asked and whether it was flushed."""

    instances: ClassVar[list[Queue]] = []
    refuse: ClassVar[bool] = False

    def __init__(self, conn: Any, settings: Any, **kw: Any) -> None:
        self.added: list[batch.Task] = []
        self.flushed = False
        self.refused: dict[str, int] = {}
        Queue.instances.append(self)

    def add(self, task: batch.Task) -> Admission:
        self.added.append(task)
        if Queue.refuse and len(self.added) == 2:
            self.refused["lab_budget"] = 1
            return Admission("refused", "x", "lab_budget")
        return Admission("queued", "c" * 48, est_cost=D("0.001"))

    def flush(self) -> FlushReport:
        self.flushed = True
        return FlushReport(batches=1, sent=len(self.added))


@pytest.fixture()
def queue(monkeypatch: pytest.MonkeyPatch) -> type[Queue]:
    Queue.instances, Queue.refuse = [], False
    monkeypatch.setattr(harness, "BatchQueue", Queue)
    return Queue


def stamp(monkeypatch: pytest.MonkeyPatch, *, registered: bool) -> None:
    from fbi.research import protocol

    def fake(key: str) -> dict[str, Any]:
        if not registered:
            raise LookupError(f"no hay protocolo registrado para {key}")
        return {"protocol": key, "version": "proto-int-c02-v1", "fingerprint": "f" * 64, "framework": protocol.VERSION}

    monkeypatch.setattr(protocol, "stamp", fake)


def test_without_the_owners_confirmation_a_run_is_its_plan_and_writes_nothing(lab_now: dict[str, Any], queue: type[Queue]) -> None:
    conn = Conn()
    p = harness.plan(conn, settings(), built(), at=AT)  # type: ignore[arg-type]
    before = len(conn.statements)
    got = harness.submit(conn, settings(), built(), p, confirmed_by_owner=False)  # type: ignore[arg-type]
    assert got["dry_run"] is True and got["submitted"] == 0 and len(conn.statements) == before and queue.instances == []


def test_without_the_protocol_registered_a_confirmed_run_writes_nothing(lab_now: dict[str, Any], queue: type[Queue],
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    stamp(monkeypatch, registered=False)
    conn = Conn()
    p = harness.plan(conn, settings(), built(), at=AT)  # type: ignore[arg-type]
    got = harness.submit(conn, settings(), built(), p, confirmed_by_owner=True)  # type: ignore[arg-type]
    assert got["submitted"] == 0 and any("INT-C02" in b for b in got["blockers"]) and conn.statements == [] and queue.instances == []


def test_a_plan_with_a_blocker_is_not_sent_even_when_confirmed(lab_now: dict[str, Any], queue: type[Queue],
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    stamp(monkeypatch, registered=True)
    lab_now["day"] = lab_day("0.10")
    conn = Conn()
    p = harness.plan(conn, settings(), built(), at=AT)  # type: ignore[arg-type]
    assert harness.submit(conn, settings(), built(), p, confirmed_by_owner=True)["submitted"] == 0  # type: ignore[arg-type]
    assert conn.statements == [] and queue.instances == []


def test_a_confirmed_run_writes_the_bank_then_records_every_ask_then_its_row_then_sends_one_batch(
        lab_now: dict[str, Any], queue: type[Queue], monkeypatch: pytest.MonkeyPatch) -> None:
    stamp(monkeypatch, registered=True)
    conn = Conn()
    p = harness.plan(conn, settings(), built(), at=AT)  # type: ignore[arg-type]
    got = harness.submit(conn, settings(), built(), p, confirmed_by_owner=True)  # type: ignore[arg-type]
    assert got["submitted"] == 12 and got["states"] == {"queued": 12} and got["protocol"]["version"] == "proto-int-c02-v1"
    [q] = queue.instances
    assert q.flushed and len(q.added) == 12
    sqls = [s for s, _ in conn.statements]
    assert sum("INSERT INTO ai.replay_bank_items" in s for s in sqls) == 6 and conn.commits == 1
    assert sqls[-1].lstrip().startswith("INSERT INTO ai.replay_runs")
    params = conn.statements[-1][1]
    assert params["estimate"] == p.cost.prudent <= params["cap"] and params["worst"] == p.cost.worst and params["asks"] == 12


def test_a_run_the_queue_refuses_in_part_sends_nothing(lab_now: dict[str, Any], queue: type[Queue], monkeypatch: pytest.MonkeyPatch) -> None:
    stamp(monkeypatch, registered=True)
    queue.refuse = True
    conn = Conn()
    p = harness.plan(conn, settings(), built(), at=AT)  # type: ignore[arg-type]
    got = harness.submit(conn, settings(), built(), p, confirmed_by_owner=True)  # type: ignore[arg-type]
    assert got["submitted"] == 0 and got["refused"] == {"lab_budget": 1} and conn.rollbacks == 1
    assert not queue.instances[0].flushed and not any("ai.replay_runs" in s for s, _ in conn.statements)


# -- the answers -------------------------------------------------------------------------------------------------------------------

def resolved(result: LlmResult | None, error: ProviderError | None = None) -> Resolved:
    item = {"id": 9, "custom_id": "c" * 48, "purpose": "other", "tier": "analysis", "model": SONNET, "fixture_id": None, "input_hash": "h",
            "prompt_version": VERSION, "deadline_at": None, "context": {"lab": "replay", "item": 4, "repetition": 1}}
    return Resolved(item, result, error, 41, D("0.003"), AT, False, 2)


def test_the_poll_keeps_the_raw_answer_of_a_replay_and_validates_nothing() -> None:
    data = {"contract": "cd-v1", "verdicts": [{"candidate": "c99"}]}
    got = harness.settle(resolved(LlmResult(data, LlmUsage(input_tokens=10, output_tokens=5), "anthropic", SONNET, latency_ms=0,
                                            extra={"stop_reason": "end_turn"})))
    assert got == {"replay": 1, "usage_id": 41, "cost": "0.003", "late": False, "model": SONNET, "ok": True, "data": data,
                   "stop_reason": "end_turn"}
    assert harness.settle(resolved(None, ProviderError("refused", "no")))["error"] == "refused"
    assert harness.settle(resolved(None))["error"] == "invalid_output"


class Recorder:
    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []

    def cursor(self, **kw: Any) -> Recorder:
        return self

    def __enter__(self) -> Recorder:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def execute(self, sql: str, params: Any) -> None:
        self.statements.append((sql, params))


def test_the_lab_handler_sends_an_answer_of_the_bank_to_the_bank_and_keeps_it_under_result() -> None:
    conn = Recorder()
    lab.settle_lab(conn, resolved(LlmResult({"contract": "aa-v1"}, LlmUsage(input_tokens=1, output_tokens=1), "anthropic", SONNET,  # type: ignore[arg-type]
                                            latency_ms=0)))
    [(sql, params)] = conn.statements
    assert "UPDATE ai.batch_items SET context = context ||" in sql and params[1] == 9
    assert params[0].obj["result"]["replay"] == 1 and params[0].obj["result"]["data"] == {"contract": "aa-v1"}
    assert batch.handler_for("other") is lab.settle_lab


def by_scope() -> dict[str, bank.Item]:
    return {i.scope: i for i in items()}


def test_an_answer_is_read_by_the_agents_own_reader_against_the_rebuilt_slice_and_names() -> None:
    item = by_scope()["match/evaluation"]
    got = harness.read_answer(item, SHADOW.outputs["match/evaluation"])
    assert got.status == "ok" and got.units == item.units and got.verdict is not None and got.problems == ()
    bad = harness.read_answer(item, {"contract": "aa-v1", "agent": "match", "mode": "EVALUATION", "candidates": "c1"})
    assert bad.status == "invalid" and bad.output is None and bad.units == {} and bad.problems
    stranger = dict(SHADOW.outputs["match/evaluation"], candidates=[{"candidate": "c99", "stance": "SUPPORT", "drivers": [], "risks": [],
                                                                      "refs": []}])
    assert harness.read_answer(item, stranger).status == "invalid", "a candidate that was not asked is no answer"


def test_a_council_that_abstains_on_every_candidate_is_an_answer_that_stood_and_says_abstain() -> None:
    item = by_scope()["council/ma-v1-h"]
    assert item.ask.view is not None
    data = verdicts(NAMING, item.ask.view, first="ABSTAIN")
    got = harness.read_answer(item, data)
    assert got.status == "abstain" and set(got.units.values()) == {"ABSTAIN"} and got.verdict == f"ABSTAIN:{len(NAMING.keys)}"
    assert harness.read_answer(by_scope()["match/context"], SHADOW.outputs["match/context"]).units == {"signals": "FORM:HOME"}


def test_the_units_of_a_scope_are_the_stored_words_against_the_two_replays_and_an_open_ask_is_counted() -> None:
    stored_rows = {1: {"scope": "council/ma-v1", "fixture_id": 10, "stored_status": "ok", "stored_units": {"c1": "APPROVE"},
                       "stored_confidence": {"c1": "HIGH"}},
                   2: {"scope": "council/ma-v1", "fixture_id": 11, "stored_status": "invalid", "stored_units": {}, "stored_confidence": {}}}
    out = {"verdicts": [{"candidate": "c1", "verdict": "APPROVE", "confidence": "MEDIUM"}]}
    rows = [{"source_run_id": 1, "repetition": 1, "status": "ok", "units": {"c1": "APPROVE"}, "output": out, "cost_usd": D(0)},
            {"source_run_id": 1, "repetition": 2, "status": "invalid", "units": {}, "output": None, "cost_usd": D(0)},
            {"source_run_id": 2, "repetition": 1, "status": "ok", "units": {"c1": "REJECT"}, "output": out, "cost_usd": D(0)}]
    held = harness.Held({(2, 2): {"status": "submitted"}})
    got = harness.scope_units(rows, stored_rows, held)["council/ma-v1"]
    assert got.units == [measure.Unit(1, 10, "c1", "APPROVE", "APPROVE", None), measure.Unit(2, 11, "c1", None, "REJECT", None)]
    assert got.answers() == measure.Answers(stored=2, stored_invalid=1, replays=3, replays_invalid=1, open=1)
    assert got.confidence == {"1:c1": ("HIGH", "MEDIUM", None)}


# -- what the bank never writes ----------------------------------------------------------------------------------------------

REPLAY = Path(inspect.getfile(harness)).parent


def statements() -> list[str]:
    found: list[str] = []
    for path in sorted(REPLAY.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r"\b(INSERT|UPDATE|DELETE)\b", node.value):
                found.append(node.value)
    return found


def test_the_bank_writes_its_own_four_tables_and_nothing_else() -> None:
    writes = statements()
    targets = {m for s in writes for m in re.findall(r"INSERT INTO (\S+)", s)}
    assert targets == {"ai.replay_bank_items", "ai.replay_runs", "ai.replay_results", "ai.replay_assessments"}
    assert not [s for s in writes if re.search(r"\bUPDATE\s+\S+\s+SET\b|\bDELETE\s+FROM\b", s)], "append-only: no update, no delete"
    source = "\n".join(p.read_text(encoding="utf-8") for p in sorted(REPLAY.glob("*.py")))
    for call in ("record_gate", "_record_if_new", "write_task", "queue_task", "end_task", "write_state", "write_review", "record_switches",
                 "call_json", "complete_json"):
        assert f"{call}(" not in source, f"the bank never calls {call}: no gate, no run of the shadow, no call in real time"


def test_the_bank_reads_the_shadow_and_its_state_and_never_names_a_table_of_production_decisions() -> None:
    source = "\n".join(p.read_text(encoding="utf-8") for p in sorted(REPLAY.glob("*.py")))
    for table in ("picks.", "intel.promotions", "customer.", "models.predictions"):
        assert table not in source
    assert (VERSION, SAME, REPEATS) == ("replay-bank-v1", "same", 2)


def test_the_worst_case_is_never_below_the_prudent_cost_even_for_an_answer_longer_than_the_request_allows() -> None:
    item = next(i for i in items() if i.scope == "match/evaluation")
    for out in (0, 1, 600, match_max := item.ask.request.max_tokens, match_max + 500):
        cost = harness.cost_of(dataclasses.replace(item.run, input_tokens=20000, output_tokens=out), item.ask.request, at=AT)
        assert cost.expected <= cost.prudent <= cost.worst, out


class Collecting:
    """The statements of a collection: what was asked and what was written."""

    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.rowcount = 1

    def cursor(self, **kw: Any) -> Collecting:
        return self

    def __enter__(self) -> Collecting:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.statements.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        sql = self.statements[-1][0]
        return [(1, 101), (2, 102)] if "source_run_id = ANY" in sql else []


def test_an_answer_whose_input_cannot_be_rebuilt_any_more_is_left_uncollected_and_said(monkeypatch: pytest.MonkeyPatch) -> None:
    ok_item = next(i for i in items() if i.scope == "match/context")
    gone = dataclasses.replace(stored("match/evaluation", 2), agent_version="match-v4")
    rows = {(1, 1): {"id": 11, "status": "succeeded", "error": None, "model": "m", "usage_id": 5, "cost_usd": D("0.001"),
                     "context": {"result": {"ok": True, "data": SHADOW.outputs["match/context"]}}},
            (2, 1): {"id": 12, "status": "succeeded", "error": None, "model": "m", "usage_id": 6, "cost_usd": D("0.001"),
                     "context": {"result": {"ok": True, "data": {}}}},
            (3, 2): {"id": 13, "status": "succeeded", "error": None, "model": "m", "usage_id": 7, "cost_usd": D("0.001"),
                     "context": {"result": {"ok": True, "data": {}}}}}
    monkeypatch.setattr(harness, "held_items", lambda conn, *, variant: harness.Held(rows))
    monkeypatch.setattr(bank, "read_runs_by_id", lambda conn, ids: [dataclasses.replace(ok_item.run, id=1), gone])
    monkeypatch.setattr(bank, "build", lambda conn, *, runs, changed_at: bank.Build(
        (dataclasses.replace(ok_item, run=dataclasses.replace(ok_item.run, id=1)),), (bank.Exclusion(gone, "match/evaluation",
                                                                                                     "version_not_in_force"),)))
    conn = Collecting()
    got = harness.collect(conn, at=AT)  # type: ignore[arg-type]
    written = [p for s, p in conn.statements if "INSERT INTO ai.replay_results" in s]
    assert [p["item"] for p in written] == [101] and written[0]["status"] == "ok" and written[0]["units"].obj == {"signals": "FORM:HOME"}
    assert got["written"] == 1 and got["not_rebuilt"] == {"2": "version_not_in_force", "3": "stored_run_missing"}
