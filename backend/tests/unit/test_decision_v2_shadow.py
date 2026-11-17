"""decision-v2's kept shadow (IA-093, AD-D01), without a database: when each evaluation is due, how the mirror groups decision-v1's
moments, what an item of evidence keeps (never its text), how a kept decision reads in the cycle, the switch and the worker's job."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from apps.worker import scheduler

from fbi.decision import engine, shadow
from fbi.intel import decision
from fbi.lifecycle import derive, machine
from fbi.ops.run_watchdog import timeout_for
from fbi.shadowjobs import decision_v2 as door

KO = datetime(2026, 11, 20, 20, 0, tzinfo=UTC)


@pytest.mark.parametrize(("before", "expected"), [
    (timedelta(hours=25), None), (timedelta(hours=24), "E1"), (timedelta(hours=18), "E1"), (timedelta(hours=12), "E1"),
    (timedelta(hours=11), None), (timedelta(minutes=21), None), (timedelta(minutes=20), "E4"), (timedelta(minutes=11), "E4"),
    (timedelta(minutes=10), None), (timedelta(minutes=5), None), (timedelta(0), None)])
def test_each_evaluation_has_its_window(before: timedelta, expected: str | None) -> None:
    assert shadow.evaluation_due(KO, KO - before) == expected


def test_e4_stays_above_decision_v1s_floor_which_is_never_lowered() -> None:
    assert shadow.E4_UNTIL == timedelta(minutes=decision.MIN_MINUTES) == timedelta(minutes=10)
    assert timedelta(minutes=door.every_minutes({})) <= shadow.E4_FROM - shadow.E4_UNTIL, "a pass falls inside the window"


def test_the_evaluations_due_are_planned_once_nearest_first_and_within_the_limit() -> None:
    now = KO - timedelta(minutes=15)
    due = [shadow.Due(1, KO), shadow.Due(2, now + timedelta(hours=13)), shadow.Due(3, now + timedelta(hours=20)),
           shadow.Due(4, now + timedelta(hours=30)), shadow.Due(5, KO + timedelta(minutes=2))]
    plan = shadow.plan_evaluations(due, {(5, "E4"): 1}, now=now, triggers=("E1", "E4"))
    assert [(p.trigger, p.fixtures, p.evaluation) for p in plan] == [("E4", (1,), "E4"), ("E1", (2, 3), "E1")]
    assert all(p.at == now and p.rows is None for p in plan)
    assert [p.trigger for p in shadow.plan_evaluations(due, {}, now=now, triggers=("E1",))] == ["E1"]
    short = shadow.plan_evaluations(due, {}, now=now, triggers=("E1", "E4"), limit=2)
    assert [(p.trigger, p.fixtures) for p in short] == [("E4", (1, 5)), ], "E4 first when the pass is short"


def row(i: int, fixture: int, at: datetime, *, checkpoint: str = "T-3h", kickoff: datetime = KO) -> dict[str, object]:
    return {"id": i, "fixture_id": fixture, "known_at": at, "kickoff_at": kickoff, "checkpoint": checkpoint, "market_key": "OU",
            "selection": "Over", "line": Decimal("2.5")}


def test_the_mirror_groups_decision_v1s_moments_skips_the_days_copies_and_what_is_already_kept() -> None:
    t1, t2, t3 = KO - timedelta(hours=3), KO - timedelta(hours=2), KO - timedelta(hours=1)
    rows = [row(1, 10, t1), row(2, 11, t1), row(3, 10, t2), row(4, 10, t2, checkpoint="selection"), row(5, 12, t3),
            row(6, 13, KO, kickoff=KO)]
    plan = shadow.plan_mirrors(rows, {(12, t3)})
    assert [(p.at, p.fixtures, [r["id"] for r in p.rows or ()]) for p in plan] == [(t1, (10, 11), [1, 2]), (t2, (10,), [3])]
    assert all(p.trigger == "mirror" and p.evaluation is None for p in plan)
    assert len(shadow.plan_mirrors(rows, set(), limit=1)) == 1


def test_an_item_of_evidence_keeps_its_type_level_and_dates_never_its_text() -> None:
    at = KO - timedelta(hours=5)
    base = {"id": 7, "fixture_id": 1, "kind": "injury", "claim_type": None, "subject_type": None, "provider_player_id": 99, "origin": "web",
            "status": "CONFIRMED", "source_tier": "club", "source_domain": "club.example", "published_at": at, "retrieved_at": at,
            "assertion": "out", "claim": "texto que no se guarda"}
    item = shadow.typed_item(base)
    assert item["level"] == "oficial" and item["retrieved_at"] == at.isoformat() and not item["typed"]
    assert "claim" not in item and "texto que no se guarda" not in str(item)
    assert shadow.typed_item({**base, "source_tier": "media", "status": "PROBABLE"})["level"] == "un_medio"
    assert shadow.typed_item({**base, "source_tier": "media", "status": "RUMOR"})["level"] == shadow.RUMOR
    assert shadow.typed_item({**base, "origin": "provider", "source_tier": "provider"})["level"] == "proveedor"
    assert shadow.typed_item({**base, "subject_type": "PLAYER", "claim_type": "STARTER"})["typed"]


def test_an_input_later_than_the_moment_is_named() -> None:
    at = KO - timedelta(hours=2)
    assert shadow.later_than(at, None, at, at - timedelta(minutes=1)) == []
    assert shadow.later_than(at, at + timedelta(seconds=1), "text") == [at + timedelta(seconds=1)]


def test_a_kept_decision_reads_in_the_cycle_as_decision_v1s_words_with_its_evaluation() -> None:
    assert set(shadow.V1_WORDS) == set(engine.RANK)
    rows = [{"id": 1, "fixture_id": 5, "market_key": "OU", "selection": "Over", "line": Decimal("2.5"), "known_at": KO - timedelta(hours=20),
             "checkpoint": "T-24h", "state": "ABSTAIN", "codes": ["edge_not_validated"], "context_status": "FULL", "kickoff_at": KO,
             "evaluation": "E1", "evaluation_version": 1},
            {"id": 2, "fixture_id": 5, "market_key": "OU", "selection": "Over", "line": Decimal("2.5"), "known_at": KO - timedelta(minutes=15),
             "checkpoint": "T-15m", "state": "RECOMMENDED", "codes": [], "context_status": "FULL", "kickoff_at": KO, "evaluation": "E4",
             "evaluation_version": 1}]
    found = shadow.histories_of(rows)
    [(key, hist)] = found.items()
    assert key == derive.Key.of(5, "OU", "Over", "2.5") and [d.layer for d in hist.decisions] == ["decision-v2", "decision-v2"]
    chain = derive.derive(hist, derive.Fixture(5, KO, "NS", "scheduled"), now=KO - timedelta(minutes=12), source=shadow.SOURCE)
    assert [(r.step.state, r.step.reason, r.step.evaluation, r.source) for r in chain] == [
        ("detectado", "candidato_nuevo", None, "intel.decisions_v2"),
        ("confirmada_sombra", "cumple_salvo_validacion", "E1", "intel.decisions_v2"),
        ("confirmada_sombra", "cumple_todo", "E4", "intel.decisions_v2")]
    machine.check_chain([r.step for r in chain])


def test_the_configuration_is_the_book_the_single_figure_and_the_core_and_its_key_says_so() -> None:
    c = shadow.CONFIG
    assert (c.rules, c.price, c.probability, c.view_version, c.families) == ("decision-v2.1", "book", "common", "forecast-v2", ("core",))
    assert c.key == "decision-v2.1|book|common|forecast-v2|core"
    assert c.as_json()["council"] is None and c.as_json()["close"] == "not kept"


def test_the_fingerprint_is_the_same_for_the_same_world_whatever_the_order() -> None:
    a = shadow.sha256({"b": [1, Decimal("2.50")], "a": KO})
    assert a == shadow.sha256({"a": KO, "b": [1, Decimal("2.50")]}) and len(a) == 64
    assert a != shadow.sha256({"a": KO, "b": [1, Decimal("2.51")]})


# -- the switch and the worker ---------------------------------------------------------------------------------------------------------

def test_the_switch_is_off_unless_it_says_shadow() -> None:
    assert door.mode({}) == "off"
    assert door.mode({"FBI_DECISION_V2": "on"}) == "off" and door.mode({"FBI_DECISION_V2": " Shadow "}) == "shadow"
    assert door.every_minutes({}) == 5 and door.every_minutes({"FBI_DECISION_V2_MINUTES": "30"}) == 5
    assert door.every_minutes({"FBI_DECISION_V2_MINUTES": "3"}) == 3
    assert door.triggers({}) == ("E1", "E4", "mirror")
    assert door.triggers({"FBI_DECISION_V2_TRIGGERS": "E4,nonsense"}) == ("E4",)
    assert door.triggers({"FBI_DECISION_V2_TRIGGERS": "nonsense"}) == ("E1", "E4", "mirror")


def test_the_worker_schedules_it_only_in_the_shadow_with_a_deadline() -> None:
    tree = ast.parse(Path(scheduler.__file__).read_text())
    found = [(str(n.args[0].value), str(n.args[1].value)) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_deadline"
             and isinstance(n.args[0], ast.Constant) and isinstance(n.args[1], ast.Constant)]
    assert ("decision_v2_shadow", "decision_v2_shadow") in found
    assert timeout_for("decision_v2_shadow") == timedelta(minutes=10)
    assert "decision_v2_shadow" in scheduler.WORKER_JOB_TYPES
    guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Call) \
                and isinstance(node.test.left.func, ast.Attribute) and node.test.left.func.attr == "mode" \
                and isinstance(node.test.left.func.value, ast.Name) and node.test.left.func.value.id == "dv2":
            body = ast.Module(body=node.body, type_ignores=[])
            guarded = guarded or any(isinstance(n, ast.Constant) and n.value == "decision_v2_shadow" for n in ast.walk(body))
    assert guarded, "the job is registered only while FBI_DECISION_V2 is shadow"


def test_the_job_does_nothing_while_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(door.SWITCH, raising=False)
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(AssertionError("no connection while off")))
    scheduler._decision_v2_shadow_now()


def test_the_job_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(door.SWITCH, "shadow")
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("database down")))
    scheduler._decision_v2_shadow_now()
