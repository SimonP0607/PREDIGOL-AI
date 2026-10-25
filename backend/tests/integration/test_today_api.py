"""Today, for Home (plan UX, A9) in a real database: the matches around today with the likely result PrediGol forecast, labelled,
one line of the reading and the suggested leagues; and why the day has no published pick - from the published set's own funnel,
never from evaluation picks. The transaction is rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.services import forecast as forecast_service
from fbi.api.services import reading as reading_service
from fbi.api.services import today as service
from fbi.picks.daily import DAY_TZ
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.integration.test_match_forecast import World, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration


def client(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, *, forecast: bool = True,
           reading: bool = True) -> TestClient:
    monkeypatch.setenv(forecast_service.USERS_SWITCH, "1" if forecast else "0")
    monkeypatch.setenv(reading_service.USERS_SWITCH, "1" if reading else "0")
    app = signed_in(create_app(), "USER")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def noon_today() -> datetime:
    """Noon of the product day (Bogotá) now: a match of «today» whatever the hour the test runs."""
    return datetime.combine(datetime.now(UTC).astimezone(DAY_TZ).date(), time(12, 0), tzinfo=DAY_TZ)


def other_competition(db: psycopg.Connection[Any], seed: Seed) -> int:
    comp = scalar(db.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                             "is_tracked) VALUES (999001, 'Liga de Prueba', 'league', 'club', 'domestic_league', true) "
                             "RETURNING id"))
    return int(scalar(db.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2025) RETURNING id",
                                 (comp,))))


def test_the_matches_around_today_with_the_forecast_labelled_a_line_of_the_reading_and_the_suggested_leagues(
        db: psycopg.Connection[Any], world: World, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    now = datetime.now(UTC)
    upcoming = world.fixture(now + timedelta(hours=3))
    for model in ("poisson", "dixon_coles"):
        world.predict_all(upcoming, model)
    world.write(upcoming, at=now - timedelta(hours=1))
    db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) "
               "VALUES (%s, 'packet-v8', %s, %s, %s, %s)",
               (upcoming, now - timedelta(hours=2), now - timedelta(hours=2), "b" * 64,
                Jsonb({"fixture": {"home": {"name": "Manchester United"}, "away": {"name": "Liverpool"}},
                       "stakes": {"away": {"rank": 1, "pressure": "title"}}})))
    finished = world.fixture(now - timedelta(hours=20))
    db.execute("UPDATE core.fixtures SET status_group = 'finished', status_short = 'FT' WHERE id = %s", (finished,))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 2, 1)", (finished,))
    season = other_competition(db, seed)
    elsewhere = int(scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
        "VALUES (9900001, %s, %s, %s, %s) RETURNING id",
        (season, seed.away_team_id, seed.home_team_id, now + timedelta(hours=5)))))

    r = client(db, monkeypatch).get("/api/v1/today")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    data = body["data"]
    matches = {m["fixture_id"]: m for m in data["matches"]["data"]}
    assert {upcoming, finished, elsewhere} <= set(matches)
    up = matches[upcoming]
    assert up["suggested"] is True, "the Premier League is one of the suggested leagues"
    assert up["forecast"] == {"outcome": "home", "probability": "0.500", "calibrated": False}
    assert up["has_reading"] is True
    assert up["headline"]["code"] == "stakes_pressure" and up["headline"]["params"]["pressure"] == "title"
    assert up["headline"]["params"]["team"] == "Liverpool" and up["headline"]["ref"] == "packet:stakes.away"
    done = matches[finished]
    assert (done["goals_home"], done["goals_away"], done["status"]) == (2, 1, "FT")
    other = matches[elsewhere]
    assert other["suggested"] is False and other["has_reading"] is False and other["forecast"] is None
    assert "Premier League" in [c["name"] for c in data["suggested"]] and data["suggested_team"] == "Colombia"
    kickoffs = [m["kickoff_at"] for m in data["matches"]["data"]]
    assert kickoffs == sorted(kickoffs), "kick-off order: the reader's day is cut in the reader's zone"

    # the owner's switches: off, the forecast and the reading's line are gone from the list too
    hidden = client(db, monkeypatch, forecast=False, reading=False).get("/api/v1/today").json()["data"]
    up = next(m for m in hidden["matches"]["data"] if m["fixture_id"] == upcoming)
    assert up["forecast"] is None and up["headline"] is None and up["has_reading"] is False


def test_a_day_without_published_picks_says_why_from_the_published_sets_funnel(
        db: psycopg.Connection[Any], world: World, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    world.fixture(noon_today())
    no_pick = client(db, monkeypatch).get("/api/v1/today").json()["data"]["no_pick"]
    assert no_pick["status"] == "ok"
    reason = no_pick["data"]
    assert reason["state"] == "none" and reason["reason"] == "no_qualified_candidates" and reason["matches"] >= 1
    assert reason["day"] == noon_today().date().isoformat()


def test_a_day_without_matches_says_so(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = false")
    body = client(db, monkeypatch).get("/api/v1/today").json()["data"]
    assert body["matches"]["status"] == "empty" and body["matches"]["code"] == "no_matches"
    assert body["no_pick"]["data"]["state"] == "none" and body["no_pick"]["data"]["reason"] == "no_matches"


def test_the_furthest_stage_and_its_commonest_reason() -> None:
    from collections import Counter

    from fbi.picks.funnel import Stage
    stages = [Stage("data", 9, 7, Counter({"too_close_to_kickoff": 2})), Stage("market", 7, 5, Counter({"no_price": 2})),
              Stage("model", 5, 5), Stage("calibration", 5, 4, Counter({"no_interval": 1})),
              Stage("value", 4, 1, Counter({"non_positive_ev": 3})), Stage("risk", 1, 0, Counter({"odds_above_cap": 1})),
              Stage("context", 0, 0), Stage("selection", 0, 0)]
    assert service.deepest(stages) == ("risk", "odds_above_cap"), "the furthest stage anything entered"
    assert service.deepest([Stage("data", 0, 0)]) == (None, None)
