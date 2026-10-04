"""The records API over HTTP: a user saves a pick, builds a parlay, reads the history; the day's
board answers honestly; the shadow preview stays the owner's. Committed in 2033 and removed."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config import reset_cache
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, principal

NOW = datetime(2033, 9, 1, 15, tzinfo=UTC)


@pytest.fixture()
def world(migrated_database: str, seed: Seed) -> Iterator[dict[str, Any]]:
    ids: dict[str, Any] = {"fixtures": [], "teams": []}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO auth.users (email, display_name, password_hash, timezone) VALUES "
                    "('records-api@test.local', 'Records API', '$argon2id$x', 'America/Bogota') RETURNING id")
        ids["user"] = scalar(cur)
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                    "is_tracked) VALUES (97501, 'Records League', 'league', 'club', 'domestic_league', true) "
                    "RETURNING id")
        ids["competition"] = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2033, true) "
                    "RETURNING id", (ids["competition"],))
        season = scalar(cur)
        for n in range(2):
            teams = []
            for side in (0, 1):
                cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                            (975000 + 2 * n + side, f"R{n}-{side}"))
                teams.append(scalar(cur))
            ids["teams"].extend(teams)
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                        "away_team_id, kickoff_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (7350100 + n, season, teams[0], teams[1], NOW + timedelta(hours=5 + n)))
            fid = scalar(cur)
            ids["fixtures"].append(fid)
            for sel, odds in (("Home", "2.20"), ("Draw", "3.30"), ("Away", "3.40")):
                cur.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, "
                            "devig_method, p_fair, n_bookmakers, overround, best_odds, best_bookmaker_id) VALUES "
                            "(%s, '1X2', %s, 0, %s, 'shin', 0.33, 4, 0.05, %s, %s)",
                            (fid, sel, NOW - timedelta(minutes=20), odds, seed.bookmaker_id))
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    set_clock(FrozenClock(NOW))
    yield ids
    set_clock(SystemClock())
    mp.undo()
    reset_cache()
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM auth.users WHERE id = %s", (ids["user"],))
        cur.execute("DELETE FROM market.market_consensus WHERE fixture_id = ANY(%s)", (ids["fixtures"],))
        cur.execute("DELETE FROM core.fixtures WHERE id = ANY(%s)", (ids["fixtures"],))
        cur.execute("DELETE FROM core.teams WHERE id = ANY(%s)", (ids["teams"],))
        cur.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s", (ids["competition"],))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (ids["competition"],))


def client_for(user_id: int, role: str = "USER", headers: dict[str, str] | None = None) -> TestClient:
    from fbi.api.app import create_app
    from fbi.api.security import optional_principal

    app = create_app()
    who = dataclasses.replace(principal(role, user_id=user_id), timezone="America/Bogota")
    app.dependency_overrides[optional_principal] = lambda: who
    return TestClient(app, headers=SAME_SITE if headers is None else headers)


def test_a_user_saves_builds_and_reads_back(world: dict[str, Any]) -> None:
    c = client_for(world["user"])
    f1, f2 = world["fixtures"]
    res = c.post("/api/v1/me/picks", json={"fixture_id": f1, "market_key": "1X2", "selection": "Home",
                                           "user_odds": "2.25"})
    assert res.status_code == 201, res.text
    saved_id = res.json()["data"]["id"]
    assert c.post("/api/v1/me/picks", json={"fixture_id": f1, "market_key": "1X2",
                                            "selection": "Home"}).status_code == 409
    assert c.post("/api/v1/me/picks", json={"fixture_id": f1, "market_key": "1X2",
                                            "selection": "home"}).status_code == 422
    listed = c.get("/api/v1/me/picks").json()["data"]
    assert [p["id"] for p in listed] == [saved_id]
    assert listed[0]["snapshot"]["price"]["odds"] == "2.200" and listed[0]["user_odds"] == "2.250"

    check = c.post("/api/v1/me/parlays/validate", json={"legs": [
        {"fixture_id": f1, "market_key": "1X2", "selection": "Home"},
        {"fixture_id": f1, "market_key": "1X2", "selection": "Draw"}]}).json()["data"]
    assert check["ok"] is False and check["errors"][0]["code"] == "same_fixture"
    built = c.post("/api/v1/me/parlays", json={"name": "Dos", "legs": [
        {"fixture_id": f1, "market_key": "1X2", "selection": "Home"},
        {"fixture_id": f2, "market_key": "1X2", "selection": "Away"}]})
    assert built.status_code == 201 and built.json()["data"]["combined_odds"] == "7.480"
    parlays = c.get("/api/v1/me/parlays").json()["data"]
    assert len(parlays) == 1 and parlays[0]["status"] == "READY" and len(parlays[0]["legs"]) == 2

    hist = c.get("/api/v1/me/history", params={"period": "today"}).json()
    assert hist["data"]["groups"]["my_picks"]["pending"] == 1
    assert hist["data"]["groups"]["my_parlays"]["total"] == 1
    assert hist["data"]["timezone"] == "America/Bogota"

    board = c.get("/api/v1/daily").json()
    assert board["data"]["source"] == "qualified" and board["data"]["evaluation_mode"] is False
    assert c.get("/api/v1/daily", params={"preview": "shadow"}).status_code == 403
    assert c.get("/api/v1/me/history", params={"preview": "shadow"}).status_code == 403

    assert c.patch(f"/api/v1/me/picks/{saved_id}", json={"user_odds": "2.40"}).status_code == 204
    assert c.get("/api/v1/me/picks").json()["data"][0]["user_odds"] == "2.400"
    assert c.patch(f"/api/v1/me/picks/{saved_id}", json={"user_odds": "0.9"}).status_code == 422
    assert c.delete(f"/api/v1/me/picks/{saved_id}").status_code == 204
    assert c.get("/api/v1/me/picks").json()["data"] == []

    parlay_id = parlays[0]["id"]
    assert client_for(999999).delete(f"/api/v1/me/parlays/{parlay_id}").status_code == 422, "not theirs"
    assert c.delete(f"/api/v1/me/parlays/{parlay_id}").status_code == 204
    assert c.get("/api/v1/me/parlays").json()["data"] == []


def test_after_kickoff_a_pick_and_a_parlay_are_history(world: dict[str, Any]) -> None:
    c = client_for(world["user"])
    f1, f2 = world["fixtures"]
    saved = c.post("/api/v1/me/picks", json={"fixture_id": f1, "market_key": "1X2", "selection": "Away"})
    built = c.post("/api/v1/me/parlays", json={"legs": [
        {"fixture_id": f1, "market_key": "1X2", "selection": "Draw"},
        {"fixture_id": f2, "market_key": "1X2", "selection": "Draw"}]})
    assert saved.status_code == 201 and built.status_code == 201
    set_clock(FrozenClock(NOW + timedelta(hours=5, minutes=1)))  # f1 has kicked off
    later = client_for(world["user"])
    pick_id, parlay_id = saved.json()["data"]["id"], built.json()["data"]["id"]
    assert later.patch(f"/api/v1/me/picks/{pick_id}", json={"user_odds": "3.10"}).status_code == 422
    assert later.delete(f"/api/v1/me/picks/{pick_id}").status_code == 422
    assert later.delete(f"/api/v1/me/parlays/{parlay_id}").status_code == 422


def test_writes_need_the_same_site_header_and_touch_only_the_users_own(world: dict[str, Any]) -> None:
    bare = client_for(world["user"], headers={})
    f1 = world["fixtures"][0]
    assert bare.post("/api/v1/me/picks", json={"fixture_id": f1, "market_key": "1X2",
                                               "selection": "Home"}).status_code == 403
    owner = client_for(world["user"])
    saved = owner.post("/api/v1/me/picks", json={"fixture_id": f1, "market_key": "1X2", "selection": "Draw"})
    other = client_for(999999)
    assert other.delete(f"/api/v1/me/picks/{saved.json()['data']['id']}").status_code == 422
    assert other.get("/api/v1/me/picks").json()["data"] == []
