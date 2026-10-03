"""The analyst's tools read the product API's own answers, with provenance, and the
LLM loop is exercised against a mocked model: no network, no key needed."""

from __future__ import annotations

import json
from collections.abc import Iterator

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.analyst.agent import AnalystAgent, AnalystConfig, ToolCall, unverified_figures
from fbi.analyst.tools import TOOLS, ToolError, run_tool
from fbi.core.config import reset_cache
from tests.integration.conftest import Seed
from tests.integration.signed_in import SAME_SITE, signed_in

KEY = "sk-analyst-key-that-must-never-leave-the-server"


def test_every_tool_has_a_schema_and_an_endpoint() -> None:
    assert {"get_match", "get_odds", "get_model_prediction", "get_pick", "get_performance",
            "get_data_quality"} <= set(TOOLS)
    for t in TOOLS.values():
        spec = t.spec()
        assert spec["input_schema"]["type"] == "object" and t.endpoint.startswith("/api/v1/")


def test_a_tool_result_carries_its_provenance(db: psycopg.Connection, seed: Seed) -> None:
    res = run_tool(db, "get_match", {"fixture_id": seed.fixture_id})
    assert res["status"] == "ok" and res["data"]["match"]["id"] == seed.fixture_id
    assert res["provenance"]["endpoint"] == f"/api/v1/admin/matches/{seed.fixture_id}"
    assert res["provenance"]["read_only"] is True and res["provenance"]["generated_at"]
    quality = run_tool(db, "get_data_quality", {})
    assert quality["status"] in ("ok", "insufficient_data", "not_available", "empty")


def test_bad_arguments_and_unknown_tools_are_tool_errors(db: psycopg.Connection) -> None:
    with pytest.raises(ToolError):
        run_tool(db, "get_match", {})
    with pytest.raises(ToolError):
        run_tool(db, "get_match", {"fixture_id": "abc"})
    with pytest.raises(ToolError):
        run_tool(db, "get_match", {"fixture_id": 2**61})  # does not exist -> 404 -> tool error
    with pytest.raises(ToolError):
        run_tool(db, "drop_tables", {})


def test_figures_are_checked_against_the_tool_results() -> None:
    call = ToolCall("T1", "get_performance", {}, True, {"data": {"settled": 12, "roi_pct": "-3.2500",
                                                                 "p": 0.5423}})
    text = "Settled 12 picks [T1], ROI -3.25% [T1], a probability of 54.2% [T1], and 71.3% from nowhere."
    assert unverified_figures(text, [call]) == ["71.3"]


def test_the_loop_runs_tools_and_flags_what_it_cannot_source(db: psycopg.Connection, seed: Seed) -> None:
    replies = [
        {"content": [{"type": "text", "text": "Checking."},
                     {"type": "tool_use", "id": "tu1", "name": "get_match", "input": {"fixture_id": seed.fixture_id}}]},
        {"content": [{"type": "text", "text": f"Fixture {seed.fixture_id} [T1] kicks off as recorded; "
                                               "the home side wins 64.0% of the time."}]},
    ]
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        assert request.headers["x-api-key"] == KEY
        assert {t["name"] for t in body["tools"]} == set(TOOLS)
        return httpx.Response(200, json=replies[len(seen) - 1])

    agent = AnalystAgent(db, AnalystConfig(KEY, "test-model", "https://llm.invalid"),
                         transport=httpx.MockTransport(handler))
    try:
        answer = agent.ask("Tell me about this fixture.")
    finally:
        agent.close()
    assert answer.rounds == 2 and [c.tool for c in answer.calls] == ["get_match"]
    assert answer.calls[0].result is not None and answer.calls[0].result["citation"] == "T1"
    tool_result = seen[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "tu1"
    assert answer.unverified_figures == ["64.0"], "an invented percentage is flagged, a cited id is not"


@pytest.fixture()
def client(migrated_database: str) -> Iterator[TestClient]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.delenv("FBI_ANALYST_API_KEY", raising=False)
    mp.delenv("FBI_ANALYST_MODEL", raising=False)
    reset_cache()
    from fbi.api.app import create_app

    with TestClient(signed_in(create_app()), headers=SAME_SITE) as c:
        yield c
    mp.undo()
    reset_cache()


def test_without_a_key_the_analyst_says_so_and_sends_nothing(client: TestClient) -> None:
    status = client.get("/api/v1/admin/analyst").json()
    assert status["status"] == "not_available" and "FBI_ANALYST_API_KEY" in status["reason"]
    assert len(status["data"]["tools"]) == len(TOOLS)
    r = client.post("/api/v1/admin/analyst/ask", json={"question": "How are the models doing?"})
    assert r.status_code == 200 and r.json()["status"] == "not_available"
    assert "Nothing was sent anywhere" in r.json()["reason"]
    assert client.post("/api/v1/admin/analyst/ask", json={"question": ""}).status_code == 422


def test_the_tool_console_and_a_configured_key_that_never_leaks(client: TestClient, seed: Seed,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    r = client.get(f"/api/v1/admin/analyst/tools/get_match?fixture_id={seed.fixture_id}")
    assert r.status_code == 200 and r.json()["provenance"]["endpoint"].endswith(str(seed.fixture_id))
    assert client.get("/api/v1/admin/analyst/tools/drop_tables").status_code == 404
    assert client.get("/api/v1/admin/analyst/tools/get_match").status_code == 422
    monkeypatch.setenv("FBI_ANALYST_API_KEY", KEY)
    monkeypatch.setenv("FBI_ANALYST_MODEL", "test-model")
    body = client.get("/api/v1/admin/analyst")
    assert body.json()["data"]["configured"] is True and KEY not in body.text
