"""The AI decision layer over HTTP: what a user sees of a match's analysis (only qualified cards and the
model's view of unpriced markets), what stays the owner's (the evaluation cards, every admin view), and the
owner's queued "run now". Committed in 2033 and removed afterwards (the AI tables need the maintenance flag)."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config import reset_cache
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, principal

NOW = datetime(2033, 10, 1, 15, tzinfo=UTC)


def card(market: str, selection: str, kind: str, verdict: str, *, qualified: bool, **over: Any) -> dict[str, Any]:
    base = {"market": market, "selection": selection, "line": "0", "kind": kind, "odds": "2.400", "bookmaker": "BK",
            "p_model": "0.5200", "p_low": "0.4700", "p_market": "0.4500", "fair_odds": "1.92", "minimum_odds": "2.23",
            "edge": "0.0700", "ev": "0.2480", "model": "dixon_coles", "pick_id": None, "qualified": qualified,
            "verdict": verdict, "verdict_reason": "value", "ai": None}
    return base | over


@pytest.fixture()
def world(migrated_database: str, seed: Seed) -> Iterator[dict[str, Any]]:
    ids: dict[str, Any] = {"fixtures": [], "teams": []}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                    "('ai-api@test.local', 'AI API', '$argon2id$x') RETURNING id")
        ids["user"] = scalar(cur)
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                    "is_tracked) VALUES (97601, 'AI League', 'league', 'club', 'domestic_league', true) RETURNING id")
        ids["competition"] = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2033, true) "
                    "RETURNING id", (ids["competition"],))
        season = scalar(cur)
        for n in range(3):
            teams = []
            for side in (0, 1):
                cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                            (976000 + 2 * n + side, f"AI{n}-{side}"))
                teams.append(scalar(cur))
            ids["teams"].extend(teams)
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                        "away_team_id, kickoff_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (7360100 + n, season, teams[0], teams[1], NOW + timedelta(hours=5 + n)))
            ids["fixtures"].append(scalar(cur))
        priced, unpriced, _ = ids["fixtures"]
        packets = []
        for fid, observed in ((priced, True), (unpriced, False)):
            cur.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, "
                        "sources, missing, approx_tokens) VALUES (%s, 'packet-v1', %s, %s, %s, %s, %s, %s, 900) "
                        "RETURNING id", (fid, NOW - timedelta(minutes=5), NOW - timedelta(minutes=5), f"{fid:064d}",
                                         Jsonb({"market": {"observed": observed}}), Jsonb([{"block": "market"}]),
                                         [] if observed else ["market"]))
            packets.append(scalar(cur))
        cur.execute("INSERT INTO ai.match_analyses (fixture_id, built_at, rule_version, input_hash, packet_id, "
                    "market_observed, cards, summary, engines) VALUES (%s, %s, 'match-analysis-v1', 'a', %s, true, %s, "
                    "%s, '{rules}')",
                    (priced, NOW - timedelta(minutes=5), packets[0], Jsonb([
                        card("1X2", "Home", "value", "recommended", qualified=True,
                             ai={"decision": "APPROVE", "review_id": None, "confidence": 0.7, "reason": "sin contexto en contra",
                                 "positives": [], "risks": [], "engines": ["rules"]}),
                        card("OU", "Over", "value", "caution", qualified=False),
                        card("BTTS", "Yes", "evaluated", "not_recommended", qualified=False)]),
                     Jsonb({"missing": ["absences"]})))
        cur.execute("INSERT INTO ai.match_analyses (fixture_id, built_at, rule_version, input_hash, packet_id, "
                    "market_observed, cards, summary, engines) VALUES (%s, %s, 'match-analysis-v1', 'b', %s, false, %s, "
                    "'{}', '{rules}')",
                    (unpriced, NOW - timedelta(minutes=5), packets[1], Jsonb([
                        card("1X2", "Home", "no_market", "no_market", qualified=False, odds=None, bookmaker=None,
                             p_market=None, edge=None, ev=None, verdict_reason="market_unobserved")])))
        cur.execute("INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, engine, "
                    "engine_version, input_hash, decision, confidence, output, packet_id, mode, status) VALUES "
                    "(%s, %s, '1X2', 'Home', 0, 'combined', 'rules-review-v1+none', 'x', 'APPROVE', 0.7, %s, %s, "
                    "'shadow', 'ok') RETURNING id",
                    (NOW - timedelta(minutes=5), priced, Jsonb({"reason": "ok", "engines": []}), packets[0]))
        ids["review"] = scalar(cur)
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AI_KEY_ANTHROPIC", "sk-must-never-leak")
    mp.setenv("FBI_AI_MODEL_ANALYSIS", "anthropic:claude-haiku-5-5")
    reset_cache()
    set_clock(FrozenClock(NOW))
    yield ids
    set_clock(SystemClock())
    mp.undo()
    reset_cache()
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("SET fbi.ai_maintenance = 'on'")
        for table in ("match_analyses", "pick_reviews", "match_packets"):
            cur.execute(f"DELETE FROM ai.{table} WHERE fixture_id = ANY(%s)", (ids["fixtures"],))
        cur.execute("DELETE FROM ai.run_requests WHERE requested_by = %s", (ids["user"],))
        cur.execute("DELETE FROM auth.users WHERE id = %s", (ids["user"],))
        cur.execute("DELETE FROM core.fixtures WHERE id = ANY(%s)", (ids["fixtures"],))
        cur.execute("DELETE FROM core.teams WHERE id = ANY(%s)", (ids["teams"],))
        cur.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s", (ids["competition"],))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (ids["competition"],))


def client_for(user_id: int, role: str) -> TestClient:
    from fbi.api.app import create_app
    from fbi.api.security import optional_principal

    app = create_app()
    who = dataclasses.replace(principal(role, user_id=user_id))
    app.dependency_overrides[optional_principal] = lambda: who
    return TestClient(app, headers=SAME_SITE)


def test_a_user_sees_only_qualified_cards_and_the_unpriced_view(world: dict[str, Any]) -> None:
    user = client_for(world["user"], "USER")
    priced, unpriced, nothing = world["fixtures"]
    a = user.get(f"/api/v1/matches/{priced}/analysis").json()
    assert a["status"] == "ok" and a["data"]["audience"] == "user"
    assert [c["market"] for c in a["data"]["cards"]] == ["1X2"] and a["data"]["withheld"] == 2
    assert a["data"]["cards"][0]["ai"] is None and a["data"]["cards"][0]["verdict"] == "recommended", \
        "in shadow a user sees nothing the AI decided"
    assert a["data"]["analyzed_by_llm"] is False and a["data"]["missing"] == ["absences"]
    b = user.get(f"/api/v1/matches/{unpriced}/analysis").json()["data"]
    assert b["market_observed"] is False and b["cards"][0]["verdict"] == "no_market" and b["cards"][0]["odds"] is None
    empty = user.get(f"/api/v1/matches/{nothing}/analysis").json()
    assert empty["status"] == "empty" and empty["data"] is None and empty["reason"] == "no_analysis_yet"
    assert user.get(f"/api/v1/matches/{priced}/analysis", params={"preview": "shadow"}).status_code == 403
    owner = client_for(world["user"], "SUPER_ADMIN")
    full = owner.get(f"/api/v1/matches/{priced}/analysis", params={"preview": "shadow"}).json()["data"]
    assert full["audience"] == "evaluation" and len(full["cards"]) == 3 and full["withheld"] == 0
    assert full["cards"][0]["ai"]["decision"] == "APPROVE", "the owner's preview shows the review"


def test_the_admin_views_are_the_owners_and_never_show_a_key(world: dict[str, Any]) -> None:
    user = client_for(world["user"], "USER")
    owner = client_for(world["user"], "SUPER_ADMIN")
    priced = world["fixtures"][0]
    paths = ["/api/v1/admin/ai/overview", "/api/v1/admin/ai/reviews", f"/api/v1/admin/ai/reviews/{world['review']}",
             f"/api/v1/admin/ai/packets/{priced}", "/api/v1/admin/ai/evidence", "/api/v1/admin/ai/costs",
             "/api/v1/admin/ai/shadow", "/api/v1/admin/ai/memory", "/api/v1/admin/ai/run-requests",
             "/api/v1/admin/evolution/dashboard"]
    for path in paths:
        assert user.get(path).status_code == 403, path
        res = owner.get(path)
        assert res.status_code == 200, (path, res.text)
        assert "sk-must-never-leak" not in res.text, path
    overview = owner.get("/api/v1/admin/ai/overview").json()["data"]
    assert overview["settings"]["tiers"]["analysis"] == {"provider": "anthropic", "model": "claude-haiku-5-5",
                                                         "key_present": True}
    assert overview["enforcement"]["enforced"] is False
    reviews = owner.get("/api/v1/admin/ai/reviews", params={"fixture_id": priced, "day": "2033-10-01"}).json()["data"]
    assert [r["id"] for r in reviews] == [world["review"]]
    detail = owner.get(f"/api/v1/admin/ai/reviews/{world['review']}").json()["data"]
    assert detail["packet"]["packet_hash"] == f"{priced:064d}" and detail["review"]["decision"] == "APPROVE"
    costs = owner.get("/api/v1/admin/ai/costs").json()["data"]
    assert {s["profile"] for s in costs["simulation"]} >= {"economico", "equilibrado", "maxima_calidad"}
    assert costs["budget"]["state"] == "NORMAL" and len(costs["worst_case"]) == len(costs["simulation"])
    assert owner.get("/api/v1/admin/ai/reviews/99999999").status_code == 404
    assert owner.get("/api/v1/admin/ai/reviews", params={"engine": "magic"}).status_code == 422


def test_the_owner_queues_a_run_and_at_most_five_wait(world: dict[str, Any]) -> None:
    owner = client_for(world["user"], "SUPER_ADMIN")
    assert client_for(world["user"], "USER").post("/api/v1/admin/ai/run-requests", json={}).status_code == 403
    for _ in range(5):
        res = owner.post("/api/v1/admin/ai/run-requests", json={"kind": "analysis", "fixture_id": world["fixtures"][0]})
        assert res.status_code == 200, res.text
        assert res.json()["data"]["status"] == "queued"
    assert owner.post("/api/v1/admin/ai/run-requests", json={"kind": "learning"}).status_code == 409
    listed = owner.get("/api/v1/admin/ai/run-requests").json()["data"]
    assert len(listed) >= 5 and listed[0]["status"] == "queued"
    assert owner.post("/api/v1/admin/ai/run-requests", json={"kind": "everything"}).status_code == 422


def test_promotion_needs_the_typed_confirmation_and_a_done_experiment(world: dict[str, Any],
                                                                      migrated_database: str) -> None:
    owner = client_for(world["user"], "SUPER_ADMIN")
    created = owner.post("/api/v1/admin/evolution/hypotheses",
                         json={"title": "API test promotion", "hypothesis": "Una hipótesis", "rationale": "Un motivo",
                               "target": "pick_engine"})
    assert created.status_code == 200, created.text
    hid = created.json()["data"]["id"]
    try:
        assert owner.post(f"/api/v1/admin/evolution/hypotheses/{hid}/promote", json={}).status_code == 422
        assert owner.post(f"/api/v1/admin/evolution/hypotheses/{hid}/promote",
                          json={"confirm": "PROMOTE"}).status_code == 409
        res = owner.post(f"/api/v1/admin/evolution/hypotheses/{hid}/decision", json={"decision": "investigate"})
        assert res.json()["data"]["status"] == "INVESTIGATING"
        res = owner.post(f"/api/v1/admin/evolution/hypotheses/{hid}/decision", json={"decision": "approve_experiment"})
        assert res.json()["data"]["status"] == "ACCEPTED"
        listed = {h["id"]: h for h in owner.get("/api/v1/admin/evolution").json()["data"]["hypotheses"]}
        assert listed[hid]["target"] == "pick_engine" and [s["to"] for s in listed[hid]["stage_history"]] == \
            ["INVESTIGATING", "ACCEPTED"]
    finally:
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            conn.execute("DELETE FROM analytics.research_hypotheses WHERE id = %s", (hid,))
