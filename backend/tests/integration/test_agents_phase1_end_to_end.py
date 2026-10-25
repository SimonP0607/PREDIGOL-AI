"""The whole of the first phase of the agents, end to end, over a real match (plan IA, phase 1: items 1.9 to 1.11).

The parts have their own tests: the package, its slices and the registry; the job that writes the state of each match; the nightly proof that
a state knew only what its moment allowed; the two routes of the Admin Console. This file holds the chain together with nothing replaced: a
match of a real world with a packet the builder made from its tables, three passes of the day that stored packets, the job of the worker that
turns each into a state, the night's audit over what the job wrote, and the owner reading both routes over HTTP - what the page is told is
what the tables hold, no more and no less.

What it shows, in order: an honest day reaches the screen as it is (sizes, hashes, code, counts, a clean audit, an empty queue) and the two
routes read and write nothing and never carry the content of the packet; a state that knew more than its moment is on the screen as a
violation naming the state; a packet the package refuses leaves a cycle that ended partial on the screen and no state for that pass.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.ai import package as mcp_package
from fbi.ai.calendar import local_day
from fbi.ai.contracts.mcp import SLICE_NAMES
from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.version import model_code_version
from fbi.intel import leakage
from tests.integration.conftest import Seed
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.integration.test_ai_decision_layer import Savepoints
from tests.integration.test_availability_history import H
from tests.integration.test_match_runs import PASSED, RUN, census, go, passed, three_passes
from tests.integration.test_slice_leak_audit import (
    RAN,
    WRITTEN,
    Scene,
    audited,
    honest,
    scene,
    write,
)

pytestmark = pytest.mark.integration

OVERVIEW = "/api/v1/admin/ai/agents"
CODE = model_code_version()


@pytest.fixture()
def owner(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The owner of the system, reading through the very connection of the test (so that it sees what the test wrote and nothing else)."""
    monkeypatch.setenv("FBI_AI_MODE", "shadow")
    monkeypatch.delenv("FBI_AI_PACKAGE", raising=False)
    monkeypatch.setenv("FBI_AI_KEY_ANTHROPIC", "sk-must-never-leak")
    app = signed_in(create_app(), "SUPER_ADMIN")
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app, headers=SAME_SITE)
    set_clock(SystemClock())


def state_url(s: Scene) -> str:
    return f"/api/v1/admin/ai/matches/{s.w.fixture}/state"


def packet_text(db: psycopg.Connection[Any], packet: int) -> str:
    row = db.execute("SELECT content FROM ai.match_packets WHERE id = %s", (packet,)).fetchone()
    assert row is not None
    return json.dumps(row[0], sort_keys=True)


def test_an_honest_day_reaches_the_screen_as_the_tables_hold_it(db: psycopg.Connection[Any], seed: Seed, owner: TestClient) -> None:
    s = scene(db, seed)
    packets = three_passes(db, s)
    report = go(Savepoints(db))
    assert report is not None and report.status == "ok"
    night = leakage.audit_day(db, day=local_day(RUN), at=RAN + 3 * H)
    assert night["slice_known"] == {"checked": 3, "violations": 0, "examples": []}
    set_clock(FrozenClock(RAN + 4 * H))
    before = census(db)

    overview = owner.get(OVERVIEW)
    match = owner.get(state_url(s))
    assert overview.status_code == 200 and match.status_code == 200
    assert census(db) == before, "reading the page writes nothing, creates no task and calls no model"

    data = overview.json()["data"]
    package = data["package"]
    assert (package["states"], package["matches"], package["by_pass"]) == (3, 1, {"first": 1, "pre": 1, "final": 1})
    assert (package["blocked"], package["flagged"]) == (0, 0)
    assert [(x["name"], x["states"], x["cap"], x["over_cap"]) for x in package["slices"]] == [(n, 3, mcp_package.CAPS[n], 0) for n in SLICE_NAMES]
    assert all(x["tokens_max"] > 0 and x["tokens_p50"] <= x["tokens_p95"] <= x["tokens_max"] for x in package["slices"])
    assert package["cycles"]["total"] == 1 and package["cycles"]["ok"] == 1 and package["cycles"]["last"]["status"] == "ok"
    assert package["cycles"]["last"]["counts"]["built"] == 3 and package["cycles"]["last"]["counts"]["refused"] == 0
    assert package["build_ms"]["max"] is not None and package["build_ms"]["max"] >= 0
    audit = {a["rule"]: a for a in data["audit"]}
    assert (audit["slice_known"]["days_audited"], audit["slice_known"]["checked"], audit["slice_known"]["violations"]) == (1, 3, 0)
    assert data["problems"] == [] and data["settings"] == {"mode": "shadow", "package": True}
    assert data["queue"]["open"] == 0 and sum(data["queue"]["tasks"].values()) == 0 and sum(data["queue"]["runs"].values()) == 0
    assert {f["engine"] for f in data["families"]} == {"llm"}, "no agent was promoted: every family reads the language model of today"

    body = match.json()["data"]
    assert [h["pass_kind"] for h in body["history"]] == ["final", "pre", "first"], "the newest knowledge first"
    assert [h["packet_id"] for h in body["history"]] == [packets[2], packets[1], packets[0]]
    cur = body["current"]
    assert cur["id"] == body["history"][0]["id"] and cur["run_kind"] == "live" and cur["code"] == CODE
    assert [x["name"] for x in cur["slices"]] == list(SLICE_NAMES) and all(x["fits"] and x["tokens"] > 0 for x in cur["slices"])
    expected = honest(db, packets[2], pass_kind="final", model_code=CODE)
    assert cur["package_hash"] == expected["package_hash"], "the hash on the screen is the one of the package derived again from the packet"
    assert [x["hash"] for x in cur["slices"]] == [x["hash"] for x in expected["slices"]]
    assert body["tasks"] == [] and body["runs"] == [], "no agent has worked on it: the Orchestrator arrives in phase 2"

    content = packet_text(db, s.packet)
    assert "Availability 0" in content, "the packet does hold the names of the match"
    for text in (overview.text, match.text):
        assert "Availability 0" not in text and "Availability 1" not in text and "Player 9001" not in text, "measures, never content"
        assert "sk-" not in text and "must-never-leak" not in text


def test_a_state_that_knew_more_than_its_moment_is_on_the_screen_naming_the_state(db: psycopg.Connection[Any], seed: Seed, owner: TestClient) -> None:
    s = scene(db, seed)
    fine = write(db, honest(db, s.packet, pass_kind="first"))
    leaky = honest(db, s.packet, pass_kind="pre")
    leaky["packet_id"] = s.leaky  # the packet it names carries a stamp later than the moment it says it has
    bad = write(db, leaky)
    assert audited(db, WRITTEN, ran=RAN) == {"checked": 2, "violations": 1, "examples": [bad]}
    set_clock(FrozenClock(RAN + H))

    audit = {a["rule"]: a for a in owner.get(OVERVIEW).json()["data"]["audit"]}["slice_known"]
    assert (audit["days_audited"], audit["checked"], audit["violations"]) == (1, 2, 1)
    assert audit["days"][0]["examples"] == [bad] and fine not in audit["days"][0]["examples"]
    body = owner.get(state_url(s)).json()["data"]
    assert {h["id"] for h in body["history"]} == {fine, bad}, "the state the audit names is one the file of the match shows"


def test_a_packet_the_package_refuses_leaves_a_partial_cycle_and_no_state_for_that_pass(db: psycopg.Connection[Any], seed: Seed, owner: TestClient) -> None:
    s = scene(db, seed)
    passed(db, s.w.fixture, "first", s.leaky)
    passed(db, s.w.fixture, "pre", s.packet, finished=PASSED + H)
    report = go(Savepoints(db))
    assert report is not None and report.status == "partial"
    set_clock(FrozenClock(RUN + H))

    data = owner.get(OVERVIEW).json()["data"]
    cycles = data["package"]["cycles"]
    assert (cycles["total"], cycles["ok"], cycles["partial"], cycles["failed"]) == (1, 0, 1, 0)
    assert cycles["last"]["status"] == "partial" and cycles["last"]["counts"]["refused"] == 1 and cycles["last"]["counts"]["built"] == 1
    assert data["package"]["by_pass"] == {"pre": 1}, "the pass that was refused has no state"
    body = owner.get(state_url(s)).json()["data"]
    assert [h["pass_kind"] for h in body["history"]] == ["pre"] and body["current"]["pass_kind"] == "pre"
