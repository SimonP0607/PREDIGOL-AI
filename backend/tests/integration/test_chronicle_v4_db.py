"""The single chronicle in shadow (IA-103/IA-104) in a real database, with a model that answers what each test needs (no network).

A match PrediGol Intelligence analysed gets its content plan from the readers' own story and the packet's news BY REFERENCE (a source the
directory does not let a model read never reaches it); the chronicle keeps the sentences the verifier lets stand and drops the others, in
``ai.chronicles`` (append-only); the same input is never paid twice; a match without a story keeps its abstention once; nothing is called
past the day's cap; a batch's answer is verified against the plan its item carries and kept once. The transaction is rolled back."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.batch import Admission, FlushReport, Resolved
from fbi.ai.providers.base import LlmResult, LlmUsage
from fbi.ai.usage import UsageLedger, shared
from fbi.chronicle import inputs, v4_job
from fbi.chronicle import plan as cp
from fbi.chronicle.writer import PROMPT_VERSION as CHRONICLE_PROMPT
from fbi.chronicle.writer import WriterInput
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.test_match_forecast import World, world  # noqa: F401  (the fixture and the data)
from tests.integration.test_user_narrative import MODEL, RUN_AT, SETTINGS, Model, frozen, match  # noqa: F401

pytestmark = pytest.mark.integration


def S(text: str, *facts: str) -> dict[str, Any]:  # noqa: N802 - a constructor
    return {"text": text, "facts": list(facts)}


def empty() -> dict[str, Any]:
    return {s: [] for s in cp.SECTIONS}


def answer(plan: cp.ContentPlan) -> dict[str, Any]:
    """One sentence the plan supports (the newest result of the home side) and one it does not (a medical detail of an absence)."""
    result = plan.by_id()["P:results.home.1"].params
    absent = next(f for f in plan.planned if f.kind == "absence.out")
    es, en = empty(), empty()
    es["como_llega"] = [S(f"El {result['team']} ganó {result['goals_for']}-{result['goals_against']} al {result['opponent']} en su "
                          "último partido.", "P:results.home.1")]
    en["como_llega"] = [S(f"{result['team']} beat {result['opponent']} {result['goals_for']}-{result['goals_against']} in their last "
                          "match.", "P:results.home.1")]
    es["jugadores"] = [S(f"{absent.params['player']} es baja por una lesión en el isquiotibial.", absent.id)]
    en["jugadores"] = [S(f"{absent.params['player']} is out with a hamstring injury.", absent.id)]
    return {"es": es, "en": en}


def plan_of(db: psycopg.Connection[Any], fid: int) -> cp.ContentPlan:
    built = inputs.plan_input(db, fid, at=RUN_AT)
    assert not isinstance(built, str), built
    return cp.build(built)


def run(db: psycopg.Connection[Any], model: Model, **kw: Any) -> v4_job.RunReport:
    return v4_job.run(db, SETTINGS, at=RUN_AT, mode_word="shadow", batch=kw.pop("batch", False), provider=(model, MODEL),
                      ledger=UsageLedger(shared(db)), cap=kw.pop("cap", Decimal("1.00")), **kw)


def rows(db: psycopg.Connection[Any], fid: int) -> list[dict[str, Any]]:
    cur = db.execute("SELECT status, abstention, content, dropped, metrics, route, plan, plan_hash, input_hash, cost_usd, usage_id "
                     "FROM ai.chronicles WHERE fixture_id = %s ORDER BY id", (fid,))
    names = [d.name for d in cur.description or []]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def test_the_plan_comes_from_the_story_and_the_news_by_reference(db: psycopg.Connection[Any], world: World, seed: Seed,  # noqa: F811
                                                                  frozen: None) -> None:  # noqa: F811
    fid, packet, ids = match(db, world, seed)
    assert {e.reason for e in plan_of(db, fid).excluded if e.ref.startswith("E:")} == {"sin_momento"}, \
        "an item the packet copied without its moment is not known"
    content, as_of = db.execute("SELECT content, as_of FROM ai.match_packets WHERE id = %s", (packet,)).fetchone()  # type: ignore[misc]
    for e in content["evidence"]:
        e["retrieved_at"] = (as_of - timedelta(hours=1)).isoformat()
    db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, missing) "
               "VALUES (%s, 'packet-v8', %s, %s, %s, %s, %s)", (fid, as_of + timedelta(minutes=5), as_of + timedelta(minutes=6), "d" * 64,
                                                                Jsonb(content), ["stats"]))
    plan = plan_of(db, fid)
    assert plan.abstention is None and "P:results.home.1" in plan.by_id()
    reasons = {e.ref: e.reason for e in plan.excluded}
    for key in ("injury", "doubt", "rumour"):
        assert reasons[f"E:{ids[key]}"] == "fuente_sin_permiso", "no source the directory does not authorise reaches a model"
    assert f"E:{ids['provider']}" not in reasons and f"E:{ids['provider']}" not in plan.by_id(), "a provider's report is no news"
    absences = [f for f in plan.facts if f.kind.startswith("absence.")]
    assert absences and all("reason" not in f.params for f in absences), "the provider's reason (Hamstring Injury) never enters"
    assert "Hamstring" not in str(WriterInput(plan, inputs.claims_for(db, plan)).body())


def test_the_job_keeps_what_stands_drops_the_rest_and_never_pays_twice(db: psycopg.Connection[Any], world: World, seed: Seed,  # noqa: F811
                                                                       frozen: None) -> None:  # noqa: F811
    fid, _packet, _ids = match(db, world, seed)
    model = Model(answer(plan_of(db, fid)))
    report = run(db, model)
    assert report.counts["partial"] == 1 and report.counts["errors"] == 0, report.counts
    assert len(model.asked) == 1 and model.asked[0].cache, "the system block is marked for the prompt cache"
    [row] = rows(db, fid)
    assert row["status"] == "partial" and row["route"] == "realtime" and row["abstention"] is None
    assert list(row["content"]["es"]) == ["como_llega"] and "isquiotibial" not in str(row["content"])
    assert any("health" in d["why"] or "injury" in d["why"] for d in row["dropped"])
    assert row["metrics"]["kept"] == 1 and row["metrics"]["proposed"] == 2 and row["metrics"]["support"] == 0.5
    assert row["plan"]["version"] == "content-plan-v1" and row["cost_usd"] > 0 and row["usage_id"] is not None
    usage = db.execute("SELECT prompt_version, purpose, input_hash FROM ai.usage WHERE id = %s", (row["usage_id"],)).fetchone()
    assert usage == ("chronicle-v4", "match_brief", row["input_hash"])
    again = run(db, Model())
    assert again.counts["already_answered"] == 1 and len(rows(db, fid)) == 1
    with pytest.raises(psycopg.Error, match="append-only"):
        db.execute("UPDATE ai.chronicles SET status = 'ok' WHERE fixture_id = %s", (fid,))


def test_a_match_without_a_story_keeps_its_abstention_once_and_calls_nothing(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                                                             seed: Seed, frozen: None) -> None:  # noqa: F811
    fid, _packet, _ids = match(db, world, seed, past=False)
    model = Model()
    assert run(db, model).counts["abstained_SIN_PLAN"] == 1
    assert run(db, model).counts["same_plan"] == 1 and model.asked == []
    [row] = rows(db, fid)
    assert (row["status"], row["abstention"], row["route"], row["cost_usd"]) == ("abstained", "SIN_PLAN", "none", 0)


def test_nothing_is_called_past_the_days_cap(db: psycopg.Connection[Any], world: World, seed: Seed, frozen: None) -> None:  # noqa: F811
    fid, _packet, _ids = match(db, world, seed)
    model = Model()
    report = run(db, model, cap=Decimal("0"))
    assert report.counts["piece_day_cap"] == 1 and model.asked == [] and rows(db, fid) == []
    assert v4_job.day_cap({"FBI_CHRONICLE_V4_DAY_USD": "5"}) == Decimal("1.00"), "the environment may only lower the cap"
    assert v4_job.day_cap({"FBI_CHRONICLE_V4_DAY_USD": "0.40"}) == Decimal("0.40")


class Queue:
    """The batch queue, standing in: it admits every task and sends nothing."""

    def __init__(self) -> None:
        self.tasks: list[Any] = []

    def add(self, task: Any) -> Admission:
        self.tasks.append(task)
        return Admission("queued", "c" * 48, est_cost=Decimal("0.002"))

    def flush(self) -> FlushReport:
        return FlushReport(batches=1, sent=len(self.tasks))


def test_a_batch_answer_is_verified_against_the_plan_its_item_carries_and_kept_once(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                                                                    seed: Seed, frozen: None) -> None:  # noqa: F811
    fid, _packet, _ids = match(db, world, seed)
    queue = Queue()
    report = run(db, Model(), batch=True, queue=queue)
    assert report.counts["queued"] == 1 and report.counts["batch_sent"] == 1 and rows(db, fid) == []
    [task] = queue.tasks
    assert task.purpose == "match_brief" and task.prompt_version == "chronicle-v4" and task.context["chronicle"] == "chronicle-v4"
    plan = cp.from_json(task.context["plan"])
    item = {"id": 1, "custom_id": "d" * 48, "purpose": "match_brief", "model": MODEL, "fixture_id": fid,
            "input_hash": task.input_hash, "context": {**task.context, "decode": {}}}
    result = LlmResult(answer(plan), LlmUsage(input_tokens=6000, output_tokens=1500), "anthropic", MODEL, 0, "msg")
    r = Resolved(item, result, None, None, Decimal("0.0015"), RUN_AT + timedelta(hours=1), False, 1)
    v4_job.settle(db, r)
    v4_job.settle(db, r)
    [row] = rows(db, fid)
    assert row["route"] == "batch" and row["status"] == "partial" and row["input_hash"] == task.input_hash
    with pytest.raises(ValueError, match="not a chronicle-v4"):
        v4_job.settle(db, Resolved({**item, "context": {}}, result, None, None, Decimal(0), RUN_AT, False, 1))


def test_the_table_refuses_a_text_without_its_status(db: psycopg.Connection[Any], world: World, seed: Seed,  # noqa: F811
                                                     frozen: None) -> None:  # noqa: F811
    fid, _packet, _ids = match(db, world, seed)
    plan = plan_of(db, fid)
    sql = ("INSERT INTO ai.chronicles (fixture_id, created_at, plan_at, version, plan_version, classes_version, verify_version, plan_hash, "
           "plan, status, abstention, content, route) VALUES (%s, %s, %s, 'chronicle-v4', 'content-plan-v1', 'claim-classes-v1', "
           "'chronicle-verify-v1', %s, %s, %s, %s, %s, 'none')")
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(sql, (fid, RUN_AT, RUN_AT, plan.hash, Jsonb(plan.as_json()), "rejected", None, Jsonb({"es": {}})))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(sql, (fid, RUN_AT, RUN_AT + timedelta(minutes=1), plan.hash, Jsonb(plan.as_json()), "abstained", "SIN_PLAN", None))
    assert scalar(db.execute("SELECT count(*) FROM ai.chronicles WHERE fixture_id = %s", (fid,))) == 0


def test_nothing_is_called_past_95_percent_of_the_capabilitys_month(db: psycopg.Connection[Any], world: World, seed: Seed,  # noqa: F811
                                                                      frozen: None) -> None:  # noqa: F811
    """IA-137 (AD-K05): the chronicle's month (US$ 14, ``chronicle_v4``) stops the job at 95 %, the next call counted, whatever the day."""
    fid, _packet, _ids = match(db, world, seed)
    UsageLedger(shared(db)).record(at=RUN_AT - timedelta(minutes=1), purpose="match_brief", tier="bulk", provider="anthropic", model=MODEL,
                                   usage=None, cost=Decimal("13.30"), status="ok", prompt_version=CHRONICLE_PROMPT)
    assert v4_job.spent_this_month(db, RUN_AT) == Decimal("13.30")
    model = Model()
    report = run(db, model, cap=Decimal("100"))
    assert report.counts["piece_month_cap"] == 1 and model.asked == [] and rows(db, fid) == []
