"""The pieces of the battery's runner that need neither a database nor a provider (Plan Maestro IA, phase 1, item 1.7): how a measurement
is named, which asks a round makes and what each one is, what the ledger's rows say of a run, which asks are due, and when a recorded
measurement no longer speaks for the corpus in force.

The runner's behaviour against a database and a simulated provider is ``tests/integration/test_battery_run.py``; what is here is what makes
that behaviour exact: a name that is too short, a task that forgets its reserved output, a row of a failed item read as an answer, or a
repetition asked before the first round is whole would pass a test that only looks at the totals."""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai.battery import AGAIN, CONTROLS, TARGETS, VERSION, corpus, evaluate, run
from fbi.ai.battery.evaluate import Outcome

ANSWERED = Outcome("answered", frozenset({"approve"}))
MOVED = Outcome("answered", frozenset({"reject-everything"}))


def row(ask: str, status: str, *, summary: Any = None, model: str | None = "claude-test", cost: Any = None) -> dict[str, Any]:
    """A row of ``run.ITEMS_SQL``: the item that asked, its status, its model, its context and what it cost."""
    context: dict[str, Any] = {"ask": ask, "run": "battery-v1:review:abc"}
    if summary is not None:
        context["result"] = summary
    return {"id": 1, "status": status, "error": None, "model": model, "context": context, "cost_usd": cost}


def held_with(target: str, *, clean: bool = True, suspects: tuple[str, ...] = ()) -> run.Held:
    """Every ask of the first round of a target answered with the same verdict; the cases named in ``suspects`` answered with a verdict
    their base never gave."""
    asks: dict[str, Outcome] = {}
    for ask in run.first_round(target):
        asks[ask.key] = MOVED if ask.case is not None and ask.case.id in suspects else ANSWERED
    return run.Held(asks if clean else {}, items=len(asks))


# ── how a measurement is named ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("target", TARGETS)
def test_a_run_is_named_by_the_battery_the_target_and_twelve_digits_of_the_requests(target: str) -> None:
    name = run.run_id(target)
    assert re.fullmatch(rf"{re.escape(VERSION)}:{target}:[0-9a-f]{{12}}", name), name
    assert name.split(":")[2] == corpus.requests_hash(target)[:12]


@pytest.mark.parametrize("target", TARGETS)
def test_a_suffix_is_a_last_part_and_the_native_route_is_another_digest(target: str) -> None:
    base = run.run_id(target)
    assert run.run_id(target, suffix="2") == f"{base}:2"
    assert run.run_id(target, suffix="") == base
    native = run.run_id(target, native=True)
    assert re.fullmatch(rf"{re.escape(VERSION)}:{target}:[0-9a-f]{{12}}", native) and native != base
    assert native.split(":")[2] == corpus.requests_hash(target, native=True)[:12]


# ── what a round asks ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("target", TARGETS)
def test_the_first_round_asks_every_base_clean_the_same_number_of_times_and_every_case_once(target: str) -> None:
    spec = corpus.target(target)
    asks = run.first_round(target)
    assert len(asks) == len(spec.bases) * CONTROLS + len(corpus.cases_of(target)) == 55
    controls = [a for a in asks if a.case is None]
    attacks = [a for a in asks if a.case is not None]
    assert Counter(a.base for a in controls) == dict.fromkeys(spec.bases, CONTROLS)
    assert sorted(a.n for a in controls) == sorted(list(range(CONTROLS)) * len(spec.bases))
    assert sorted(a.case.id for a in attacks if a.case) == sorted(c.id for c in corpus.cases_of(target))
    assert {a.n for a in attacks} == {0} and {a.stage for a in asks} == {1} and {a.target for a in asks} == {target}
    assert all(a.base == a.case.base for a in attacks if a.case)
    assert len({a.key for a in asks}) == len(asks), "no two asks share a name"


def test_the_number_of_clean_asks_of_a_base_can_be_changed_for_a_trial() -> None:
    assert len(run.first_round("extract", controls=2)) == len(corpus.target("extract").bases) * 2 + 40
    assert len(run.first_round("extract", controls=0)) == 40


@pytest.mark.parametrize("target", TARGETS)
def test_a_repetition_is_asked_again_times_for_each_suspect_of_its_target_only(target: str) -> None:
    mine = [c.id for c in corpus.cases_of(target)][:2]
    theirs = [c.id for t in TARGETS if t != target for c in corpus.cases_of(t)][:2]
    asks = run.repetitions(target, [*mine, *theirs])
    assert len(asks) == 2 * AGAIN and {a.stage for a in asks} == {2} and {a.target for a in asks} == {target}
    assert Counter(a.case.id for a in asks if a.case) == dict.fromkeys(mine, AGAIN)
    assert sorted({a.n for a in asks}) == list(range(AGAIN))
    assert len(run.repetitions(target, mine, again=1)) == 2 and run.repetitions(target, []) == []


def test_the_key_of_an_ask_names_its_subject_stage_and_number() -> None:
    first = run.first_round("review")
    base = next(a for a in first if a.case is None)
    case = next(a for a in first if a.case is not None)
    assert base.subject == evaluate.base_subject(base.base) and base.key == evaluate.key(base.subject, 1, base.n)
    assert case.case is not None
    assert case.subject == evaluate.case_subject(case.case.id) and case.key == evaluate.key(case.subject, 1, 0)


# ── what an ask is ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("target", TARGETS)
def test_the_task_of_an_ask_is_the_labs_and_reserves_the_output_its_prompt_writes(target: str) -> None:
    spec = corpus.target(target)
    rid = run.run_id(target)
    for ask in (run.first_round(target)[0], run.first_round(target)[-1]):
        task = run.task_of(ask, rid)
        assert task.purpose == "other" and task.lab is True and task.prompt_version == VERSION
        assert task.tier == spec.tier and task.typical_output == spec.typical_output > 0
        assert task.request == corpus.request_for(target, ask.base, ask.case)
        assert task.context == {"lab": "battery", "run": rid, "target": target, "base": ask.base,
                                "case": None if ask.case is None else ask.case.id, "ask": ask.key, "stage": ask.stage}


def test_the_native_route_asks_with_structured_outputs() -> None:
    ask = run.first_round("review")[0]
    plain = run.task_of(ask, run.run_id("review"))
    native = run.task_of(ask, run.run_id("review", native=True), native=True)
    assert plain.request != native.request and native.request == corpus.request_for("review", ask.base, None, native=True)


def test_the_input_of_every_ask_is_its_own_and_does_not_change_between_calls() -> None:
    hashes: dict[str, str] = {}
    for target in TARGETS:
        rid = run.run_id(target)
        for ask in run.first_round(target):
            h = run.task_of(ask, rid).input_hash
            assert h == run.task_of(ask, rid).input_hash and re.fullmatch(r"[0-9a-f]{64}", h)
            hashes[f"{target}/{ask.key}"] = h
    assert len(set(hashes.values())) == len(hashes) == 165, "five clean asks of a base are five asks"
    ask = run.first_round("review")[0]
    assert run.task_of(ask, run.run_id("review")).input_hash != run.task_of(ask, run.run_id("review", suffix="2")).input_hash


# ── what the ledger says of a run ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", ["succeeded", "late", "invalid"])
def test_an_item_closed_with_a_summary_is_the_outcome_that_summary_says(status: str) -> None:
    summary = Outcome("answered", frozenset({"approve", "x"}), 2, True).as_json() | {"said": {"anything": "here"}}
    held = run.held_from([row("a/1.0", status, summary=summary)])
    assert held.asks == {"a/1.0": Outcome("answered", frozenset({"approve", "x"}), 2, True)} and held.open == frozenset()
    assert held.known == frozenset({"a/1.0"})


@pytest.mark.parametrize("status", ["errored", "canceled", "expired", "failed", "queued", "abandoned"])
def test_an_item_that_closed_any_other_way_is_an_ask_without_an_answer_even_if_it_carries_a_summary(status: str) -> None:
    held = run.held_from([row("a/1.0", status, summary=ANSWERED.as_json())])
    assert held.asks == {"a/1.0": Outcome("error")} and held.open == frozenset()
    assert held.known == frozenset(), "an ask without an answer is asked again"


@pytest.mark.parametrize("status", ["succeeded", "late", "invalid"])
@pytest.mark.parametrize("summary", [None, "answered", ["answered"], 3])
def test_an_item_closed_without_a_summary_in_the_form_of_one_is_an_ask_without_an_answer(status: str, summary: Any) -> None:
    item = row("a/1.0", status)
    if summary is not None:
        item["context"]["result"] = summary
    assert run.held_from([item]).asks == {"a/1.0": Outcome("error")}


@pytest.mark.parametrize("status", ["submitting", "submitted"])
def test_an_item_still_on_its_way_is_open_and_known_and_has_no_outcome(status: str) -> None:
    for summary in (None, ANSWERED.as_json()):
        held = run.held_from([row("a/1.0", status, summary=summary)])
        assert held.open == frozenset({"a/1.0"}) and held.asks == {} and held.known == frozenset({"a/1.0"})


def test_the_newest_item_of_an_ask_decides_it() -> None:
    lost_then_answered = run.held_from([row("a/1.0", "errored"), row("a/1.0", "succeeded", summary=ANSWERED.as_json())])
    assert lost_then_answered.asks == {"a/1.0": ANSWERED} and lost_then_answered.known == frozenset({"a/1.0"})
    answered_then_lost = run.held_from([row("a/1.0", "succeeded", summary=ANSWERED.as_json()), row("a/1.0", "errored")])
    assert answered_then_lost.asks == {"a/1.0": Outcome("error")}
    lost_then_open = run.held_from([row("a/1.0", "errored"), row("a/1.0", "submitted")])
    assert lost_then_open.open == frozenset({"a/1.0"}) and lost_then_open.asks == {}


def test_every_item_is_counted_and_paid_for_even_when_a_newer_one_replaced_it() -> None:
    held = run.held_from([row("a/1.0", "errored", model="model-b", cost="0.25"),
                          row("a/1.0", "succeeded", summary=ANSWERED.as_json(), model="model-a", cost=Decimal("0.5")),
                          row("b/1.0", "submitted", model=None, cost=None)])
    assert held.items == 3 and len(held.asks) == 1
    assert held.cost == Decimal("0.75"), "what the first attempt cost is spent all the same"
    assert held.models == ("model-a", "model-b"), "sorted, once each, from every item and not only the newest; none for a row without one"


def test_a_run_with_no_items_holds_nothing() -> None:
    held = run.held_from([])
    assert held == run.Held() and held.items == 0 and held.cost == 0 and held.models == () and held.known == frozenset()
    assert run.Held().asks == {} and run.Held().open == frozenset()


def test_what_is_known_is_what_is_on_its_way_or_answered() -> None:
    held = run.held_from([row("a/1.0", "submitted"), row("b/1.0", "succeeded", summary=ANSWERED.as_json()),
                          row("c/1.0", "errored"), row("d/1.0", "invalid", summary=Outcome("invalid").as_json())])
    assert held.known == frozenset({"a/1.0", "b/1.0", "d/1.0"}), "an answer that is invalid is an answer; one that never came is not"


# ── which asks are due ────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("target", TARGETS)
def test_nothing_held_means_the_whole_first_round_is_due(target: str) -> None:
    due = run.due(target, run.Held())
    assert [a.key for a in due] == [a.key for a in run.first_round(target)]


@pytest.mark.parametrize("target", TARGETS)
def test_what_is_known_is_not_due_and_what_is_not_is(target: str) -> None:
    first = run.first_round(target)
    held = run.Held({first[0].key: ANSWERED, first[1].key: Outcome("error")}, frozenset({first[2].key}), items=3)
    assert [a.key for a in run.due(target, held)] == [a.key for a in first[1:2] + first[3:]]


@pytest.mark.parametrize("target", TARGETS)
def test_no_repetition_is_due_until_the_first_round_is_whole(target: str) -> None:
    first = run.first_round(target)
    case = next(a for a in first if a.case is not None)
    for missing in ("never asked", "on its way", "lost"):
        asks = {a.key: (MOVED if a.key == case.key else ANSWERED) for a in first[:-1]}
        held = run.Held(asks, items=len(asks))
        if missing == "on its way":
            held = run.Held(asks, frozenset({first[-1].key}), items=len(asks))
        if missing == "lost":
            held = run.Held(asks | {first[-1].key: Outcome("error")}, items=len(asks) + 1)
        due = run.due(target, held)
        assert all(a.stage == 1 for a in due), missing
        assert [a.key for a in due] == ([] if missing == "on its way" else [first[-1].key]), missing


@pytest.mark.parametrize("target", TARGETS)
def test_once_the_first_round_is_whole_the_repetitions_of_the_suspects_are_due_and_nothing_else(target: str) -> None:
    suspects = tuple(c.id for c in corpus.cases_of(target)[:2])
    held = held_with(target, suspects=suspects)
    due = run.due(target, held)
    assert len(due) == 2 * AGAIN and {a.stage for a in due} == {2} and {a.case.id for a in due if a.case} == set(suspects)
    clean = held_with(target)
    assert run.due(target, clean) == [], "a round with no suspects is finished"


@pytest.mark.parametrize("target", TARGETS)
def test_a_repetition_already_asked_or_on_its_way_is_not_due_again(target: str) -> None:
    suspect = corpus.cases_of(target)[0].id
    held = held_with(target, suspects=(suspect,))
    again = run.repetitions(target, [suspect])
    held = run.Held(held.asks | {again[0].key: ANSWERED}, frozenset({again[1].key}), items=held.items + 2)
    assert [a.key for a in run.due(target, held)] == [again[2].key]


# ── when a recorded measurement no longer speaks ──────────────────────────────────────────────────────────────────

def fresh_evidence(native: bool = False) -> dict[str, Any]:
    return {"battery": VERSION, "native": native, "corpus_hash": corpus.corpus_hash(),
            "targets": {t: {"requests_hash": corpus.requests_hash(t, native=native)} for t in TARGETS}}


def test_a_measurement_of_this_corpus_and_these_requests_is_not_stale() -> None:
    assert run.stale(fresh_evidence()) == [] and run.stale(fresh_evidence(native=True)) == []


def test_a_measurement_is_stale_for_each_thing_that_changed_and_says_which() -> None:
    other_version = fresh_evidence() | {"battery": "battery-v0"}
    assert [r for r in run.stale(other_version) if "battery-v0" in r and VERSION in r]
    other_corpus = fresh_evidence() | {"corpus_hash": "0" * 64}
    assert any("cases or the bases" in r for r in run.stale(other_corpus))
    for target in TARGETS:
        changed = fresh_evidence()
        changed["targets"][target] = {"requests_hash": "f" * 64}
        reasons = run.stale(changed)
        assert len(reasons) == 1 and target in reasons[0] and "prompt, schema or layout" in reasons[0]
        missing = fresh_evidence()
        del missing["targets"][target]
        reasons = run.stale(missing)
        assert len(reasons) == 1 and target in reasons[0] and "was not measured" in reasons[0]


def test_the_route_a_measurement_was_made_with_is_the_route_its_requests_are_compared_on() -> None:
    assert run.stale(fresh_evidence(native=True) | {"native": False}), "native requests are not the plain ones"
    assert run.stale(fresh_evidence() | {"native": True}), "and the plain ones are not the native ones"
    assert run.stale({}) and len(run.stale({})) >= 3
