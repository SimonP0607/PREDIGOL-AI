"""The research by entity and topic over HTTP (plan IA, phase 2): the route of the Admin Console that shows what research v2 kept, found and spent,
beside the week of comparison with v1 and the gate that decides whether v2 may replace it. It is the owner's, it reads and calls nothing, and what it
answers is what the web page reads. Rows are committed (the server reads through its own connection) and removed afterwards (the AI tables need the
maintenance flag).

What the page computes from a built world is ``test_ai_research_service``; here the route is held to its contract: who may ask, how many days, the
shape the page reads, money as text, and a part that cannot be computed being a part of the answer and not an error."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.ai import cache
from fbi.ai.evidence import EvidenceIn, store
from fbi.ai.usage import UsageLedger, shared
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config import reset_cache
from tests.integration.conftest import Seed
from tests.integration.signed_in import SAME_SITE, principal

pytestmark = pytest.mark.integration

NOW = datetime(2037, 6, 15, 18, 0, tzinfo=UTC)  # 13:00 in Bogotá, the 15th
PATH = "/api/v1/admin/ai/research/entities"
UNREAD = "a-key-nobody-reads"
PASS_COUNTS = {"research_v2_shadow": 1, "web_searches": 2, "web_items": 2, "web_new": 2, "v2_demand": 2, "v2_paid": 0, "v2_shared": 1, "v2_reused": 1,
               "v2_pages": 3, "v2_pages_known": 1, "v2_pages_unread": 1, "v2_pages_flagged": 1, "v2_claims": 2, "v2_new": 2}
PASS_ROW = ("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, counts) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'ok', %s) RETURNING id")


def client_for(role: str | None) -> TestClient:
    from fbi.api.app import create_app
    from fbi.api.security import optional_principal

    app = create_app()
    who = None if role is None else principal(role)
    app.dependency_overrides[optional_principal] = lambda: who
    return TestClient(app, headers=SAME_SITE)


def body(topic: str, *, level: int, results: int, classes: dict[str, int]) -> dict[str, Any]:
    return {"v": cache.KEY_VERSION, "topic": topic, "level": level, "search": "k", "searched_at": (NOW - timedelta(hours=2)).isoformat(),
            "results": results, "standing": True, "classes": classes}


@pytest.fixture()
def world(migrated_database: str, seed: Seed) -> Iterator[dict[str, Any]]:
    ids: dict[str, Any] = {"passes": [], "usage": [], "evidence": []}
    kickoff = NOW + timedelta(days=3)
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        cache.remember(conn, "TEAM", seed.home_team_id, "availability", body("availability", level=1, results=5, classes={"media": 4, "official": 1}),
                       at=NOW - timedelta(hours=2), nearest_kickoff=kickoff)
        cache.remember(conn, "MATCH", seed.fixture_id, "preview", body("preview", level=3, results=3, classes={"media": 3}),
                       at=NOW - timedelta(hours=1), nearest_kickoff=kickoff)
        conn.execute("INSERT INTO ai.research_cache (scope, key, fetched_at, expires_at, content_hash, payload) VALUES ('entity', %s, %s, %s, 'h', '{}')",
                     (UNREAD, NOW - timedelta(hours=3), NOW + timedelta(days=1)))
        for day, kind, hours in ((date(2037, 6, 14), "first", 30), (date(2037, 6, 15), "pre", 6)):
            started = NOW - timedelta(hours=hours)
            row = conn.execute(PASS_ROW, (seed.fixture_id, day, kind, started, started + timedelta(minutes=2), kickoff, Jsonb(PASS_COUNTS))).fetchone()
            assert row is not None
            ids["passes"].append(row[0])
        ledger = UsageLedger(shared(conn))
        for cost, tag in (("0.0070", f"{cache.KEY_VERSION}:search-of-v2"), ("0.0050", "search-of-v1")):
            ids["usage"].append(ledger.record(at=NOW - timedelta(hours=3), purpose="web_search", tier="search", provider="exa", model="exa", usage=None,
                                              cost=Decimal(cost), status="ok", input_hash=tag))
        item = EvidenceIn(fixture_id=None, team_id=seed.home_team_id, kind="news", claim="a typed claim", origin="web", source_name="bbc.co.uk",
                          retrieved_at=NOW - timedelta(hours=2), story_key="t:api", source_url="https://bbc.co.uk/api", assertion="info",
                          source_tier="media", published_at=NOW - timedelta(hours=3), attributes={}, claim_type="OUT", subject_type="TEAM",
                          subject_id=seed.home_team_id, fresh_until=NOW + timedelta(hours=20))
        evidence_id, created = store(conn, item, at=NOW - timedelta(hours=2))
        assert created
        ids["evidence"].append(evidence_id)
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AI_KEY_ANTHROPIC", "sk-must-never-leak")
    mp.setenv("FBI_AI_MODE", "shadow")
    mp.setenv("FBI_AI_RESEARCH_V2", "shadow")
    reset_cache()
    set_clock(FrozenClock(NOW))
    yield ids
    set_clock(SystemClock())
    mp.undo()
    reset_cache()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("SET fbi.ai_maintenance = 'on'")
        conn.execute("DELETE FROM ai.evidence WHERE id = ANY(%s)", (ids["evidence"],))
        conn.execute("DELETE FROM ai.fixture_passes WHERE id = ANY(%s)", (ids["passes"],))
        conn.execute("DELETE FROM ai.usage WHERE id = ANY(%s)", (ids["usage"],))
        conn.execute("DELETE FROM ai.research_cache WHERE scope = 'entity' AND (key LIKE %s OR key = %s)", (f"{cache.KEY_VERSION}:%", UNREAD))


def test_the_route_is_the_owners_and_never_shows_a_key(world: dict[str, Any]) -> None:
    assert client_for(None).get(PATH).status_code == 401, "nobody signed in"
    for role in ("USER", "GHOST"):
        assert client_for(role).get(PATH).status_code == 403, role
    res = client_for("SUPER_ADMIN").get(PATH)
    assert res.status_code == 200, res.text
    assert "sk-must-never-leak" not in res.text and "sk-" not in res.text


def test_the_page_has_the_shape_the_web_reads(world: dict[str, Any], seed: Seed) -> None:
    body_ = client_for("SUPER_ADMIN").get(PATH).json()
    assert body_["status"] == "ok"
    o = body_["data"]
    assert set(o) == {"days", "since", "switch", "freshness", "answers", "claims", "per_day", "pages", "comparison", "gate"}
    assert o["days"] == 7 and datetime.fromisoformat(o["since"]) == datetime(2037, 6, 9, 5, 0, tzinfo=UTC), (
        "the window starts at Bogotá's midnight of its first day")
    s = o["switch"]
    assert (s["asked"], s["mode"], s["typed_visible"], s["gate_passed"], s["gate_at"], s["history"]) == ("shadow", "shadow", False, False, None, [])
    assert [(t["topic"], t["entity"], t["levels"], t["entries"], t["fresh"]) for t in o["freshness"]["topics"]] == [
        ("availability", "TEAM", [1, 2], 1, 1), ("confirmation", "TEAM", [2], 0, 0), ("preview", "MATCH", [3], 1, 1)]
    assert o["freshness"]["unreadable"] == 1 and UNREAD not in str(o), "a key the page does not read is counted and never shown"
    assert [(a["kind"], a["name"], a["topic"], a["results"], a["fresh"], a["claims"]) for a in o["answers"]] == [
        ("MATCH", "Manchester United vs Liverpool", "preview", 3, True, 0), ("TEAM", "Manchester United", "availability", 5, True, 1)], (
        "the newest first, the entity named, and the claims about it counted")
    assert o["answers"][0]["tiers"] == {"media": 3} and o["answers"][1]["tiers"] == {"media": 4, "official": 1}
    c = o["claims"]
    assert (c["total"], c["fresh"], c["entity_scoped"], c["match_scoped"], c["flagged"]) == (1, 1, 1, 0, 0)
    assert c["by_status"]["PROBABLE"] + c["by_status"]["RUMOR"] + c["by_status"]["CONFIRMED"] == 1
    assert {r["key"]: r["total"] for r in c["by_class"]}["RELIABLE_MEDIA"] == 1 and {r["key"]: r["total"] for r in c["by_type"]}["OUT"] == 1
    assert [d["day"] for d in o["per_day"]] == [f"2037-06-{n:02d}" for n in range(15, 8, -1)], "seven days, the newest first"
    today, yesterday = o["per_day"][0], o["per_day"][1]
    assert (today["passes"], today["passes_v2"], today["searches"], today["demand"], today["shared"], today["reused"]) == (1, 1, 2, 2, 1, 1)
    assert (yesterday["passes"], yesterday["pages"], yesterday["pages_known"], yesterday["claims"]) == (1, 3, 1, 2)
    assert all(d["passes"] == 0 for d in o["per_day"][2:]), "a day nothing ran is a row of zeros"
    assert o["pages"]["read"] == 6 and o["pages"]["known"] == 2 and o["pages"]["unread"] == 2 and o["pages"]["flagged"] == 2
    cmp_ = o["comparison"]
    assert cmp_["status"] == "ok", cmp_
    k = cmp_["data"]
    assert (k["passes_in_shadow"], k["passes_compared"], k["searches_v1"], k["searches_v2_alone"], k["saved"]) == (2, 2, 4, 2, 2)
    assert k["saved_pct"] == "50.00" and k["reuse_pct"] == "33.33"
    assert k["coverage_pct"] is None and k["coverage_players_pct"] is None and k["extractor_invalid_pct"] is None, (
        "nothing to cover and nothing extracted: a percentage of nothing is no figure, never a zero")
    gate = o["gate"]
    assert gate["status"] == "ok", gate
    g = gate["data"]
    assert g["verdict"] == "PENDIENTE POR TIEMPO REAL" and g["window"]["complete"] is False and g["consequence"] is None
    assert (g["window"]["stable_complete_days"], g["window"]["anchor"], g["window"]["eligible_on"]) == (1, "2037-06-14", "2037-06-21"), (
        "one complete day of shadow: the seventh is the 20th, and the first day the gate can be evaluated is the 21st")
    assert g["checks"] == [] and len(g["pending"]) == 1 and g["pending"][0].startswith("1 de 7 días completos"), (
        "a gate that cannot be judged yet judges nothing: it says how many days it still lacks")
    assert g["preview"]["note"].startswith("NOT evidence") and g["preview"]["searches"]["searches_v1"] == 2, "what the days gone show, never as evidence"
    assert seed.home_team_id > 0


def test_money_travels_as_text_and_the_arms_of_the_search_are_told_apart(world: dict[str, Any]) -> None:
    o = client_for("SUPER_ADMIN").get(PATH).json()["data"]
    today = o["per_day"][0]
    assert isinstance(today["exa_v1_usd"], str) and isinstance(today["exa_v2_usd"], str)
    assert (Decimal(today["exa_v1_usd"]), Decimal(today["exa_v2_usd"])) == (Decimal("0.0050"), Decimal("0.0070")), (
        "the search that carries the key of v2 is v2's; any other is v1's")
    k = o["comparison"]["data"]
    assert (k["exa_v1_searches"], k["exa_v2_searches"]) == (1, 1) and Decimal(k["exa_v1_usd"]) == Decimal("0.0050")
    assert isinstance(k["exa_v1_usd"], str) and isinstance(k["exa_v2_usd"], str)


def test_the_window_is_a_number_of_days_between_one_and_thirty(world: dict[str, Any]) -> None:
    owner = client_for("SUPER_ADMIN")
    for days in (1, 7, 30):
        data = owner.get(PATH, params={"days": days}).json()["data"]
        assert data["days"] == days and len(data["per_day"]) == days
        assert data["per_day"][0]["day"] == "2037-06-15"
    for bad in (0, 31, -1, "week", ""):
        assert owner.get(PATH, params={"days": bad}).status_code == 422, bad


def test_the_page_changes_nothing(world: dict[str, Any], migrated_database: str) -> None:
    tables = ("ai.feature_gates", "ai.evidence", "ai.fixture_passes", "ai.usage", "ai.research_cache", "ai.cycles", "ai.match_runs")

    def counts() -> list[Any]:
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            return [conn.execute(f"SELECT count(*), COALESCE(sum(hits), 0) FROM {t}" if t == "ai.research_cache" else f"SELECT count(*), 0 FROM {t}").fetchone()
                    for t in tables]

    before = counts()
    owner = client_for("SUPER_ADMIN")
    for days in (7, 30):
        assert owner.get(PATH, params={"days": days}).status_code == 200
    assert counts() == before, "asking is not searching, reusing, recording or counting a reuse"


def test_a_part_that_cannot_be_computed_is_a_part_of_the_answer_and_not_an_error(world: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai import gate_research

    def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("password=hunter2 host=10.0.0.9")

    monkeypatch.setattr(gate_research, "evaluate", broken)
    res = client_for("SUPER_ADMIN").get(PATH)
    assert res.status_code == 200 and res.json()["status"] == "ok"
    o = res.json()["data"]
    assert o["gate"]["status"] == "not_available" and o["gate"]["data"] is None and o["gate"]["code"] == "gate_failed"
    assert "RuntimeError" in o["gate"]["reason"] and "hunter2" not in res.text and "10.0.0.9" not in res.text, "the class of the error and nothing else"
    assert o["comparison"]["status"] == "ok", "the rest of the page is whole"
    assert [a["topic"] for a in o["answers"]] == ["preview", "availability"]
