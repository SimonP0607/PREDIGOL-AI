"""PM-10-03 over the real application: a match's statistics by half answer 404 while ``FBI_MATCH_HALVES`` is off; on, only the statistics
the competition has built (>= 90 % of >= 5 matches asked) are in the answer, a figure the provider did not send is null, and a match
without halves or a competition without a decision says why instead of drawing a zero."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.cache import clear as clear_cache
from fbi.api.deps import get_db
from tests.integration.conftest import Seed
from tests.integration.signed_in import SAME_SITE, signed_in

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
ROUTE = "/api/v1/matches/{f}/period-stats"


def client(db: psycopg.Connection) -> TestClient:
    app = signed_in(create_app(), "USER")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def make_fixture(db: psycopg.Connection, seed: Seed, season_id: int, n: int) -> int:
    row = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                     "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                     (990_000 + n, season_id, seed.home_team_id, seed.away_team_id, NOW - timedelta(days=n))).fetchone()
    assert row is not None
    return int(row[0])


def ask(db: psycopg.Connection, fixture: int, filled: list[str]) -> None:
    db.execute("INSERT INTO core.fixture_period_asks (fixture_id, channel, asked_at, outcome, filled, sums_ok, sums_off, payload_hash) "
               "VALUES (%s, 'closing', %s, 'with_halves', %s, %s, '{}', %s)", (fixture, NOW, filled, filled, None))


def halves(db: psycopg.Connection, seed: Seed, fixture: int, *, corners_first_home: int | None = 4) -> None:
    for side, period, corners, shots, fouls in (("home", "1h", corners_first_home, 6, 7), ("away", "1h", 2, 4, 8), ("home", "2h", 3, 5, 6),
                                                ("away", "2h", 1, 3, 9)):
        db.execute("INSERT INTO core.fixture_team_stats_period (fixture_id, team_side, period, source, corners, shots, fouls, payload_hash, "
                   "fetched_at) VALUES (%s, %s, %s, 'api-football', %s, %s, %s, %s, %s)",
                   (fixture, side, period, corners, shots, fouls, seed.payload_hash, NOW))
    for side, corners, shots, fouls in (("home", 7, 11, 13), ("away", 3, 7, 17)):
        db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, corners, shots, fouls, payload_hash, fetched_at) "
                   "VALUES (%s, %s, 'api-football', %s, %s, %s, %s, %s)", (fixture, side, corners, shots, fouls, seed.payload_hash, NOW))


def test_off_the_route_answers_404(db: psycopg.Connection, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_MATCH_HALVES", raising=False)
    clear_cache()
    assert client(db).get(ROUTE.format(f=seed.fixture_id)).status_code == 404


def test_only_the_statistics_the_competition_built_are_served(db: psycopg.Connection, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_MATCH_HALVES", "1")
    clear_cache()
    fixtures = [make_fixture(db, seed, seed.season_id, n) for n in range(1, 7)]
    for fid in fixtures:  # six asked: corners and shots came in all, fouls in four (67 %: not built)
        ask(db, fid, ["corners", "shots"] + (["fouls"] if fid in fixtures[:4] else []))
    halves(db, seed, fixtures[0])
    answer = client(db).get(ROUTE.format(f=fixtures[0]))
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["status"] == "ok" and body["data"]["asked"] == 6 and body["data"]["built"] == ["shots", "corners"]
    periods = {p["period"]: {f["key"]: (f["home"], f["away"]) for f in p["figures"]} for p in body["data"]["periods"]}
    assert periods["total"] == {"shots": (11.0, 7.0), "corners": (7.0, 3.0)}
    assert periods["1h"] == {"shots": (6.0, 4.0), "corners": (4.0, 2.0)}
    assert periods["2h"] == {"shots": (5.0, 3.0), "corners": (3.0, 1.0)}
    assert "fouls" not in periods["total"], "a statistic that is not built is not served"


def test_a_figure_not_sent_is_null_never_zero(db: psycopg.Connection, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_MATCH_HALVES", "1")
    clear_cache()
    fixtures = [make_fixture(db, seed, seed.season_id, n) for n in range(1, 7)]
    for fid in fixtures:
        ask(db, fid, ["corners", "shots"])
    halves(db, seed, fixtures[0], corners_first_home=None)
    figures = {f["key"]: f for p in client(db).get(ROUTE.format(f=fixtures[0])).json()["data"]["periods"] if p["period"] == "1h"
               for f in p["figures"]}
    assert figures["corners"]["home"] is None and figures["corners"]["away"] == 2.0


def test_a_match_without_halves_and_a_competition_without_a_decision_say_why(db: psycopg.Connection, seed: Seed,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_MATCH_HALVES", "1")
    clear_cache()
    fixtures = [make_fixture(db, seed, seed.season_id, n) for n in range(1, 7)]
    for fid in fixtures[:5]:
        ask(db, fid, ["corners"])
    no_halves = client(db).get(ROUTE.format(f=fixtures[5])).json()
    assert no_halves["status"] == "not_available" and no_halves["reason"] == "partido_sin_mitades" and no_halves["data"]["built"] == ["corners"]
    clear_cache()
    db.execute("DELETE FROM core.fixture_period_asks WHERE fixture_id = ANY(%s)", (fixtures[2:],))
    young = client(db).get(ROUTE.format(f=fixtures[5])).json()
    assert young["status"] == "not_available" and young["reason"] == "sin_estadisticas_por_mitad" and young["data"]["built"] == []
    assert client(db).get(ROUTE.format(f=999_999_999)).status_code == 404
