"""The agents over HTTP (plan IA, phase 1): the two routes of the Admin Console that show the registry, the engine of each family, what the job that
writes the state of each match did, and the file of one match. They are the owner's, they read and call nothing, and what they answer is what the web
page reads. Rows are committed (the server reads through its own connection) and removed afterwards (the AI tables need the maintenance flag)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.api.services import ai_agents
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config import reset_cache
from tests.integration.signed_in import SAME_SITE, principal

NOW = datetime(2037, 6, 15, 18, 0, tzinfo=UTC)
MATCH = 9_370_001
EMPTY = 9_370_002


def client_for(role: str) -> TestClient:
    from fbi.api.app import create_app
    from fbi.api.security import optional_principal

    app = create_app()
    who = principal(role)
    app.dependency_overrides[optional_principal] = lambda: who
    return TestClient(app, headers=SAME_SITE)


def slice_of(name: str, tokens: int) -> dict[str, Any]:
    return {"name": name, "hash": hashlib.sha256(name.encode()).hexdigest(), "tokens": tokens, "cap": 18000, "fits": True, "trimmed": [],
            "blocks": ["form", "market"]}


@pytest.fixture()
def world(migrated_database: str) -> Iterator[dict[str, Any]]:
    ids: dict[str, Any] = {}
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        for n, (kind, hours, tokens) in enumerate([("first", 20, 800), ("pre", 6, 1500)]):
            known = NOW - timedelta(hours=hours)
            row = conn.execute(
                "INSERT INTO ai.match_runs (fixture_id, run_kind, pass_kind, known_at, created_at, state_version, package_version, package_hash, "
                "packet_id, elapsed_ms, slices, blocking, flags, model_status) VALUES (%s, 'live', %s, %s, %s, 'ms-v1', 'package-v1', %s, %s, %s, "
                "%s, %s, %s, %s) RETURNING id",
                (MATCH, kind, known, known + timedelta(minutes=2), hashlib.sha256(kind.encode()).hexdigest(), 40 + n, 120 + 30 * n,
                 Jsonb([slice_of("match", tokens), slice_of("stats", 300)]), ["competition_score:PRODUCT_ONLY"] if n else [], [],
                 Jsonb({"code": "mc9a7bec97ca"}))).fetchone()
            assert row is not None
            ids[kind] = row[0]
        cycle = conn.execute(
            "INSERT INTO ai.cycles (kind, started_at, finished_at, status, mode, budget_state, counts) VALUES ('package', %s, %s, 'ok', 'shadow', "
            "'NORMAL', %s) RETURNING id", (NOW - timedelta(minutes=12), NOW - timedelta(minutes=11), Jsonb({"pending": 2, "built": 2}))).fetchone()
        assert cycle is not None
        ids["cycle"] = cycle[0]
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AI_KEY_ANTHROPIC", "sk-must-never-leak")
    mp.setenv("FBI_AI_MODE", "shadow")
    mp.delenv("FBI_AI_PACKAGE", raising=False)
    reset_cache()
    set_clock(FrozenClock(NOW))
    yield ids
    set_clock(SystemClock())
    mp.undo()
    reset_cache()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("SET fbi.ai_maintenance = 'on'")
        conn.execute("DELETE FROM ai.match_runs WHERE fixture_id = ANY(%s)", ([MATCH, EMPTY],))
        conn.execute("DELETE FROM ai.cycles WHERE id = %s", (ids["cycle"],))


def test_the_two_routes_are_the_owners_and_never_show_a_key(world: dict[str, Any]) -> None:
    user, owner = client_for("USER"), client_for("SUPER_ADMIN")
    for path in ("/api/v1/admin/ai/agents", f"/api/v1/admin/ai/matches/{MATCH}/state"):
        assert user.get(path).status_code == 403, path
        res = owner.get(path)
        assert res.status_code == 200, (path, res.text)
        assert "sk-must-never-leak" not in res.text and "sk-" not in res.text, path


def test_the_overview_has_the_shape_the_page_reads(world: dict[str, Any]) -> None:
    res = client_for("SUPER_ADMIN").get("/api/v1/admin/ai/agents")
    body = res.json()
    assert body["status"] == "ok"
    o = body["data"]
    assert set(o) == {"registry", "problems", "families", "decisions", "package", "queue", "audit", "settings"}
    assert o["problems"] == [] and o["settings"] == {"mode": "shadow", "package": True}
    built = {r["agent"]: r for r in o["registry"] if r["status"] == "built"}
    assert {"brief", "reviewer", "extractor", "postmortem", "post_match_reviewer", "learning_analyst", "claim_extractor",
            "match", "council", "stats"} == set(built)
    assert all(r["in_sync"] is True for r in built.values())
    assert all((built[a]["born_as"], built[a]["baseline"]) == ("CHALLENGER", False) for a in ("match", "council", "stats")), (
        "the match agent, the council and the statistics agent are born challengers in shadow: they replace nobody")
    challenger = built["claim_extractor"]
    assert (challenger["born_as"], challenger["baseline"], challenger["replaces"]) == ("CHALLENGER", False, "extractor"), (
        "research v2's extractor is not the baseline: it runs beside the extractor of today and takes over only by a row the owner signs")
    assert [r["agent"] for r in built.values() if r["baseline"] is True] == ["brief", "reviewer", "extractor", "postmortem", "post_match_reviewer",
                                                                            "learning_analyst"]
    assert [f["family"] for f in o["families"]] == ["1X2", "DC", "AH", "OU", "BTTS", "CORNERS", "CARDS"]
    assert {f["engine"] for f in o["families"]} == {"llm"} and o["decisions"] == []
    p = o["package"]
    assert (p["states"], p["matches"], p["blocked"], p["flagged"], p["days"]) == (2, 1, 1, 0, 7)
    assert p["by_pass"] == {"first": 1, "pre": 1}
    assert [(s["name"], s["states"], s["tokens_max"], s["cap"]) for s in p["slices"]] == [("match", 2, 1500, 18000), ("stats", 2, 300, 18000)]
    assert p["build_ms"] == {"p50": 135, "p95": 148, "max": 150}, "120 and 150 milliseconds: the median is between them, the 95th is 148.5"
    assert p["cycles"]["total"] == 1 and p["cycles"]["last"]["id"] == world["cycle"] and p["cycles"]["last"]["counts"] == {"pending": 2, "built": 2}
    assert p["rule"]["state_version"] == "ms-v1" and p["rule"]["window_days"] == 4
    assert [(d["day"], d["states"]) for d in p["per_day"]] == [("2037-06-15", 1), ("2037-06-14", 1)], "Bogotá's days: 07:02 and 17:02 local"
    q = o["queue"]
    assert q["open"] == 0 and q["tasks"]["planned"] == 0 and q["runs"]["ok"] == 0
    assert isinstance(q["reserved_usd"], str), "money travels as text"
    assert [a["rule"] for a in o["audit"]] == list(ai_agents.AUDIT_RULES) and "slice_known" in ai_agents.AUDIT_RULES
    assert all(a["days_audited"] == 0 and a["days"] == [] for a in o["audit"]), "nothing audited in this database: no days, never a clean record"


def test_the_switch_of_the_job_is_shown_as_the_owner_set_it(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_AI_PACKAGE", "0")
    assert client_for("SUPER_ADMIN").get("/api/v1/admin/ai/agents").json()["data"]["settings"] == {"mode": "shadow", "package": False}


def test_the_window_is_a_number_of_days_between_one_and_thirty(world: dict[str, Any]) -> None:
    owner = client_for("SUPER_ADMIN")
    for days in (1, 7, 30):
        data = owner.get("/api/v1/admin/ai/agents", params={"days": days}).json()["data"]
        assert data["package"]["days"] == days and data["queue"]["days"] == days
    for bad in (0, 31, -1, "week"):
        assert owner.get("/api/v1/admin/ai/agents", params={"days": bad}).status_code == 422, bad


def test_the_file_of_a_match_over_http(world: dict[str, Any]) -> None:
    res = client_for("SUPER_ADMIN").get(f"/api/v1/admin/ai/matches/{MATCH}/state")
    body = res.json()
    assert body["status"] == "ok"
    d = body["data"]
    assert d["fixture_id"] == MATCH and d["tasks"] == [] and d["runs"] == []
    assert [h["id"] for h in d["history"]] == [world["pre"], world["first"]]
    cur = d["current"]
    assert cur["id"] == world["pre"] and cur["pass_kind"] == "pre" and cur["run_kind"] == "live" and cur["code"] == "mc9a7bec97ca"
    assert cur["blocking"] == ["competition_score:PRODUCT_ONLY"] and cur["flags"] == []
    assert [(s["name"], s["tokens"], s["cap"], s["fits"]) for s in cur["slices"]] == [("match", 1500, 18000, True), ("stats", 300, 18000, True)]
    assert cur["known_at"].startswith("2037-06-15T12:00:00") and cur["created_at"].startswith("2037-06-15T12:02:00")


def test_a_match_without_a_state_is_an_empty_answer_with_its_reason(world: dict[str, Any]) -> None:
    res = client_for("SUPER_ADMIN").get(f"/api/v1/admin/ai/matches/{EMPTY}/state")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "empty" and body["reason"] == "no_live_state_yet"
    assert body["data"] == {"fixture_id": EMPTY, "current": None, "history": [], "tasks": [], "runs": []}


@pytest.mark.parametrize("fixture", ["0", "-3", "abc", str(2**63)])
def test_a_fixture_that_cannot_be_one_is_refused(world: dict[str, Any], fixture: str) -> None:
    assert client_for("SUPER_ADMIN").get(f"/api/v1/admin/ai/matches/{fixture}/state").status_code == 422
