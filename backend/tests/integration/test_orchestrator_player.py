"""The Player Agent in the orchestrator (``fbi.ai.agents.player``, IA-017) over a real database, with a scripted provider.

What is shown: with ``player`` out of ``FBI_AI_AGENTS`` (the default) the pass is the one before IA-017 - no task, no cost, the set of slices
``slices-v1`` and no word of the agent in the state; with it in, one task of the agent over its own slice about the candidates of goals and result under
the very names of before, its position cited as ``A:player_evaluation`` by the arms that read assessments only, the state written with the set
``slices-v2`` and the leak audit re-deriving the old rows and the new ones alike; with nothing about a player in its slice, nothing is asked."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import orchestrator, prompts
from fbi.ai import package as mcp_package
from fbi.ai.agents import council, player
from fbi.ai.contracts.mcp import SLICE_SETS
from fbi.ai.providers.base import JsonRequest
from fbi.core.version import model_code_version
from fbi.intel import leakage
from tests.integration.conftest import Seed
from tests.integration.orchestrator_world import (
    HAIKU,
    RUN,
    Gear,
    answer_for,
    assign,
    provider,
    settings,
    world,
)
from tests.integration.test_orchestrator import go, reviews_of, rows
from tests.integration.test_slice_leak_audit import RAN, audited, honest, write
from tests.integration.test_slice_leak_audit import scene as slice_scene

pytestmark = pytest.mark.integration

ON = ("match", "council", "player")
NAMES = [("c1", "1X2", "Draw"), ("c2", "1X2", "Home"), ("c3", "OU", "Over")]
"""The names of the candidates of the world (``cand-names-v1``): the same with the Player Agent off and on."""


def names(state: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(c["candidate"], c["market"], c["selection"]) for c in state["candidates"] if c.get("candidate")]


@pytest.fixture(autouse=True)
def clean_memory() -> None:
    orchestrator._failed.clear()


def player_answer(request: JsonRequest) -> dict[str, Any]:
    asked = json.loads(request.user.split("\n")[1])["candidates"]
    return {"contract": "pa-v1", "agent": "player", "mode": "EVALUATION", "data_quality": "GOOD",
            "signals": [{"code": "ABSENCES", "direction": "AWAY", "refs": ["P:shared.absences.home"]}],
            "candidates": [{"candidate": c["candidate"], "stance": "CONCERN", "drivers": ["ABSENCES"], "risks": ["KEY_ABSENCE_OPEN"],
                            "refs": ["P:shared.absences.home"]} for c in asked]}


def script(request: JsonRequest) -> dict[str, Any]:
    return player_answer(request) if request.system == prompts.PLAYER_ASSESS_SYSTEM else answer_for(request)


def player_requests(pv: Any) -> list[JsonRequest]:
    return [r for r in pv.requests if r.system == prompts.PLAYER_ASSESS_SYSTEM]


def tasks(db: psycopg.Connection[Any], fixture: int, agent: str) -> list[dict[str, Any]]:
    return rows(db, "SELECT t.*, r.status AS run_status, r.slice_hash AS run_slice FROM ai.agent_tasks t LEFT JOIN ai.agent_runs r ON r.id = t.last_run_id "
                    "WHERE t.fixture_id = %s AND t.agent = %s ORDER BY t.id", fixture, agent)


def state_of(db: psycopg.Connection[Any], fixture: int) -> dict[str, Any]:
    [state] = rows(db, "SELECT * FROM ai.match_runs WHERE fixture_id = %s AND run_kind = 'shadow'", fixture)
    return state


def audit(db: psycopg.Connection[Any]) -> tuple[int, int, list[int]]:
    return leakage.slice_known(db, RUN - timedelta(days=1), RUN + timedelta(days=1))


def test_off_by_default_the_pass_is_the_one_of_before(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    pv = provider(script)
    report = go(db, Gear(db), pv)
    assert (report.ran, report.invalid, report.failed_open, report.calls) == (1, 0, 0, 5)
    assert player_requests(pv) == [] and tasks(db, w.fixture, "player") == [], "no task and no cost"
    state = state_of(db, w.fixture)
    assert [s["name"] for s in state["slices"]] == list(SLICE_SETS["slices-v1"])
    assert "slices" not in state["model_status"] and "player" not in state["model_status"] and names(state) == NAMES
    assert all("player" not in r["engine_version"] for r in reviews_of(db, w.fixture))
    assert audit(db)[1:] == (0, [])


def test_on_it_is_asked_about_goals_and_result_under_the_same_names_and_only_shadow_arms_read_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    pv = provider(script)
    report = go(db, Gear(db), pv, settings(agents=ON))
    assert (report.ran, report.invalid, report.failed_open, report.calls) == (1, 0, 0, 6)
    [request] = player_requests(pv)
    second = json.loads(request.user.split("\n")[1])
    assert all(set(c) <= {"candidate", "family", "market", "selection", "line"} for c in second["candidates"]), "no number reaches it"

    [t] = tasks(db, w.fixture, "player")
    assert (t["agent_version"], t["task_kind"], t["model"], t["prompt_version"], t["schema_version"], t["effort"]) == (
        "player-v1", "evaluation", HAIKU, "player-assess-v1", "pa-v1", "medium")
    assert t["candidates"] == ["c1", "c2", "c3"] and t["workspace"] == "lab" and t["run_status"] == "ok"
    package = mcp_package.derive(db, w.packet, pass_kind="pre", model_code=model_code_version())
    assert package is not None
    slices = mcp_package.slices_of(package, SLICE_SETS["slices-v2"])
    assert t["input_hash"] == slices["player"].hash == t["run_slice"]

    state = state_of(db, w.fixture)
    assert [s["name"] for s in state["slices"]] == ["match", "stats", "player"] and state["model_status"]["slices"] == "slices-v2"
    assert state["model_status"]["player"] == {"version": "player-v1", "asked": ["c1", "c2", "c3"], "note": None}
    assert names(state) == NAMES, "the names of goals and result do not move"

    views = [json.loads(r.user)["view"] for r in pv.requests if r.schema_name == council.TOOL]
    labelled = [[a["label"] for a in v.get("assessments", [])] for v in views]
    assert len(views) == 3
    assert any("player_evaluation" in labels for labels in labelled) and any(labels == [] for labels in labelled), "cs-v1 reads no assessment"
    for r in reviews_of(db, w.fixture):
        assert ("+player-v1" in r["engine_version"]) is (r["engine"] in ("ma-v1", "ma-v1-h"))
        assert r["mode"] == "shadow"
    assert audit(db)[1:] == (0, []), "the new row verifies with its player slice"


def test_the_audit_derives_again_the_set_each_row_names_old_and_new(db: psycopg.Connection[Any], seed: Seed) -> None:
    s = slice_scene(db, seed)
    old = honest(db, s.packet)
    assert [x["name"] for x in old["slices"]] == ["match", "stats"] and "slices" not in old["model_status"], "a row as it was written before IA-017"
    new = honest(db, s.packet, pass_kind="final")
    package = mcp_package.derive(db, s.packet, pass_kind="final")
    assert package is not None
    made = mcp_package.slices_of(package, SLICE_SETS["slices-v2"])
    new["slices"] = [made[n].measures() for n in SLICE_SETS["slices-v2"]]
    new["model_status"] = {"slices": "slices-v2"}
    write(db, old)
    write(db, new)
    first = audited(db)
    assert (first["checked"], first["violations"]) == (2, 0), "a slices-v1 row and a slices-v2 row, side by side"

    unnamed = dict(new, pass_kind="first", model_status={})
    unknown = dict(new, pass_kind="request", model_status={"slices": "slices-v9"})
    claims = dict(old, run_kind="shadow", model_status={"slices": "slices-v2"})
    ids = [write(db, unnamed), write(db, unknown), write(db, claims)]
    found = audited(db, ran=RAN + timedelta(minutes=1))
    assert found["violations"] == 3 and sorted(found["examples"]) == sorted(ids), (
        "three slices with no set named are held to slices-v1; a set the code does not know; an old row that claims the new set")


def test_on_with_nothing_about_a_player_nothing_is_asked(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(player, "has_players", lambda _document: False)
    w = world(db, seed)
    assign(db, w.fixture)
    pv = provider(script)
    report = go(db, Gear(db), pv, settings(agents=ON))
    assert report.calls == 5 and player_requests(pv) == [] and tasks(db, w.fixture, "player") == []
    state = state_of(db, w.fixture)
    assert state["model_status"]["player"]["note"] == player.NO_PLAYERS and state["model_status"]["slices"] == "slices-v2"
    assert audit(db)[1:] == (0, [])


def test_player_alone_switches_nothing_on(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    for agents in (("player",), ("player", "match"), ("player", "council")):
        report = go(db, Gear(db), provider(script), settings(agents=agents))
        assert report.skipped == "off" and report.calls == 0
    assert tasks(db, w.fixture, "player") == []
