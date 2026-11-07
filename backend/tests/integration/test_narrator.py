"""The Narrator (``narrator-v1``, IA-017) against a real database: the facts of a pick read from its trace, one call through
``call_json`` with a fake provider and the readers' ledger, the verifier - and nothing written but the ledger's row."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import user_budget
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import shared
from fbi.narrator import job
from fbi.narrator.facts import PickFacts
from tests.integration import test_trace_and_registry as traced
from tests.integration.test_trace_and_registry import PRICE_AT, T6, World

pytestmark = pytest.mark.integration

trace_world = traced.world
"""The trace's own world, as a fixture of this module: a match, its picks, decisions, reviews and evidence."""

MODEL = "claude-sonnet-5-5"
SETTINGS = AiSettings(tiers={"analysis": TierModel("anthropic", MODEL)}, keys={"anthropic": "test-key-not-real"},
                      monthly_budget=Decimal("180"), daily_budget=Decimal("6"))
AT = T6 + timedelta(minutes=5)


def s(text: str, *ids: str) -> dict[str, Any]:
    return {"text": text, "facts": list(ids)}


ANSWER = {
    "es": {"why": [s("Las casas pagan 2,10 por la victoria de Trace Home, la mejor cuota entre 6 casas.", "F:odds", "F:match"),
                   s("Trace Home gana 3-0 en sus últimos partidos.", "F:match", "F:odds")],
           "risks": [s("El mercado todavía no tiene una ventaja validada fuera de muestra.", "F:filter.final")]},
    "en": {"why": [s("Bookmakers pay 2.10 for a Trace Home win, the best price among 6 bookmakers.", "F:odds", "F:match"),
                   s("Trace Home win 3-0 in their recent games.", "F:match", "F:odds")],
           "risks": [s("The market's edge is not yet validated out of sample.", "F:filter.final")]},
}


def one(db: psycopg.Connection[Any], sql: str) -> Any:
    row = db.execute(sql).fetchone()
    assert row is not None
    return row[0]


def tables(db: psycopg.Connection[Any]) -> dict[str, int]:
    return {t: int(one(db, f"SELECT count(*) FROM {t}") or 0)
            for t in ("ai.user_narratives", "ai.user_usage", "ai.usage", "intel.decisions", "picks.picks", "ai.pick_reviews")}


def test_a_pick_is_narrated_from_its_trace_and_only_the_ledger_is_written(db: psycopg.Connection[Any], trace_world: dict[str, Any]) -> None:
    pf = job.build(db, trace_world["home_pick"])
    assert isinstance(pf, PickFacts)
    by = pf.by_id()
    assert by["F:match"].params == {"home": "Trace Home", "away": "Trace Away", "competition": "Trace League"}
    assert by["F:odds"].params == {"odds": 2.1, "bookmakers": 6} and by["F:review"].params["verdict"] == "APPROVE"
    assert f"F:evidence.{trace_world['evidence']}" in by and pf.decision_id == trace_world["home_decisions"][1]
    before = tables(db)
    provider = FakeProvider(lambda r: ANSWER, name="anthropic")
    report = job.run(db, SETTINGS, pick_ids=[trace_world["home_pick"], trace_world["home_pick"]], at=AT, mode="shadow", monthly=Decimal(20),
                     provider=(provider, MODEL), ledger=user_budget.UserUsageLedger(shared(db)))
    assert report.status == "ok" and len(provider.requests) == 1, "one call for one pick, asked twice"
    (out,) = report.outcomes
    assert out.status == "partial" and out.input_hash == pf.hash and out.cost > 0
    assert out.content is not None and [x["text"] for x in out.content["es"]["why"]] == [ANSWER["es"]["why"][0]["text"]]
    assert {d.why for d in out.dropped} == {"numbers no cited fact has: 3, 0"}
    after = tables(db)
    assert after["ai.user_usage"] == before["ai.user_usage"] + 1 and after["ai.usage"] == before["ai.usage"]
    assert {k: v for k, v in after.items() if k != "ai.user_usage"} == {k: v for k, v in before.items() if k != "ai.user_usage"}
    assert one(db, "SELECT prompt_version FROM ai.user_usage ORDER BY id DESC LIMIT 1") == "pick-why-v1"
    assert report.as_json()["outcomes"][0]["content"] == out.content


def test_a_new_decision_is_a_new_input(db: psycopg.Connection[Any], seed: Any, trace_world: dict[str, Any]) -> None:
    first = job.build(db, trace_world["home_pick"])
    w = World.__new__(World)
    w.db, w.seed, w.fixture = db, seed, trace_world["fixture"]
    w.decision("Home", T6 + timedelta(hours=2), "T-1h", pick=trace_world["home_pick"], review=trace_world["combined"], evidence=[trace_world["evidence"]],
               price_at=PRICE_AT, state="CAUTELA")
    again = job.build(db, trace_world["home_pick"])
    assert isinstance(first, PickFacts) and isinstance(again, PickFacts)
    assert again.hash != first.hash and again.by_id()["F:verdict"].params == {"state": "CAUTELA"}


def test_off_or_without_the_readers_budget_nothing_is_called(db: psycopg.Connection[Any], trace_world: dict[str, Any]) -> None:
    provider = FakeProvider(lambda r: ANSWER, name="anthropic")
    before = tables(db)
    assert job.run(db, SETTINGS, pick_ids=[trace_world["home_pick"]], at=AT, mode="off", provider=(provider, MODEL)).status == "off"
    assert job.run(db, SETTINGS, pick_ids=[trace_world["home_pick"]], at=AT, mode="shadow", monthly=Decimal(0),
                   provider=(provider, MODEL)).status == "no_budget"
    assert provider.requests == [] and tables(db) == before
