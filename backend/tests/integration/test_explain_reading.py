"""«Explícame» on a match's forecast and its risks (plan UX, B9), over HTTP in a real database, on the forecast world of F5 and
the reading of A9 (``test_reading_api``) - the transaction rolled back.

* «¿Qué significa este pronóstico?»: what a forecast is, each market's likely outcome with every probability, whether it is
  calibrated and why a forecast is not a pick - and nothing a reader is never shown (a model's name, a fair price, an edge). A
  match without a forecast says why with the reading's own fact; the forecast's switch hides it, the owner's preview does not.
* «¿Qué puede salir mal?»: the risks of the structured reading, each with its reference; an incomplete reading says so; the
  reading's switch hides them; a rumour's text or link never appears.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.routers import explain as explain_router
from fbi.api.services import forecast as forecast_service
from fbi.api.services import reading as reading_service
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.integration.test_match_forecast import World, world  # noqa: F401  (the fixture and the data)
from tests.integration.test_reading_api import (
    CONTENT,
    LINK,
    RUMOUR,
    match_with_forecast,
    store_packet,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def fresh_limit() -> Iterator[None]:
    explain_router.LIMIT.reset()
    yield
    explain_router.LIMIT.reset()


def client(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, role: str = "USER", *, forecast: bool = True,
           reading: bool = True) -> TestClient:
    monkeypatch.setenv(forecast_service.USERS_SWITCH, "1" if forecast else "0")
    monkeypatch.setenv(reading_service.USERS_SWITCH, "1" if reading else "0")
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def ask(c: TestClient, fid: int, intent: str, **params: Any) -> dict[str, Any]:
    r = c.get("/api/v1/explain", params={"entity": "match", "id": fid, "intent": intent, **params})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    data: dict[str, Any] = r.json()["data"]
    return data


def says(answer: dict[str, Any]) -> list[str]:
    return [line["say"] or f"fact:{line['fact']['code']}" for line in answer["lines"]]


def teams(db: psycopg.Connection[Any], fid: int) -> tuple[str, str]:
    row = db.execute("SELECT th.name, ta.name FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id "
                     "JOIN core.teams ta ON ta.id = f.away_team_id WHERE f.id = %s", (fid,)).fetchone()
    assert row is not None
    return str(row[0]), str(row[1])


def test_what_the_forecast_means(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    fid = match_with_forecast(world)
    answer = ask(client(db, monkeypatch), fid, "forecast")
    assert answer["answered"] is True and answer["links"] == ["glossary"]
    assert {"forecast", "probability", "calibrated"} <= set(answer["terms"])
    assert says(answer) == ["forecast_what", "forecast_market", "forecast_market", "forecast_market",
                            "forecast_uncalibrated", "forecast_not_pick"]
    markets = [line["params"] for line in answer["lines"] if line["say"] == "forecast_market"]
    assert [(m["market"], m["line"]) for m in markets] == [("1X2", 0.0), ("OU", 2.5), ("BTTS", 0.0)]
    result = markets[0]
    home, away = teams(db, fid)
    assert (result["home"], result["away"]) == (home, away)
    assert (result["likely"], result["p"], result["calibrated"]) == ("Home", 0.5, False)
    assert result["selections"] == ["Home", "Draw", "Away"] and abs(sum(result["probabilities"]) - 1) < 0.01
    for m in markets:
        assert m["p"] == max(m["probabilities"]) and m["likely"] == m["selections"][m["probabilities"].index(m["p"])]
    text = str(answer).lower()
    for never in ("dixon", "poisson", "fair_odds", "model_probability", "edge", "bet365"):
        assert never not in text, never


def test_a_match_without_a_forecast_says_why_and_the_switch_hides_it(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    bare = world.fixture()
    none = ask(client(db, monkeypatch), bare, "forecast")
    assert none["answered"] is False and says(none) == ["fact:forecast_missing"]
    assert none["lines"][0]["fact"]["params"]["reason"] and none["lines"][0]["fact"]["ref"] == "forecast"
    fid = match_with_forecast(world)
    hidden = ask(client(db, monkeypatch, forecast=False), fid, "forecast")
    assert hidden["answered"] is False and says(hidden) == ["forecast_hidden"]
    owner = ask(client(db, monkeypatch, "SUPER_ADMIN", forecast=False), fid, "forecast", preview="shadow")
    assert owner["answered"] is True and "forecast_market" in says(owner), "the owner's preview does not depend on it"


def test_what_can_go_wrong_in_a_match(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    fid = match_with_forecast(world)
    store_packet(db, fid, CONTENT, ["stats"])
    answer = ask(client(db, monkeypatch), fid, "risks")
    assert answer["answered"] is True and says(answer)[0] == "risks_intro"
    facts = [line["fact"] for line in answer["lines"] if line["fact"]]
    assert {"lineups_unconfirmed", "short_rest", "rumours", "not_checked"} <= {f["code"] for f in facts}
    assert all(f["ref"].startswith(("packet", "forecast")) for f in facts), "every risk with its reference"
    assert "risks_incomplete" not in says(answer), "the reading is complete"
    text = answer.__repr__().lower()
    for never in (RUMOUR.lower(), LINK, "rumours.example", "bet365", "dixon", "1810"):
        assert never not in text, never


def test_an_incomplete_reading_says_so_and_its_switch_hides_the_risks(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    fid = match_with_forecast(world)
    early = ask(client(db, monkeypatch), fid, "risks")
    assert says(early) == ["risks_intro", "fact:no_context_yet", "fact:uncalibrated", "risks_incomplete"], \
        "without the match's context: said, never left empty - and the forecast's own risk, its number uncalibrated"
    hidden = ask(client(db, monkeypatch, reading=False), fid, "risks")
    assert hidden["answered"] is False and says(hidden) == ["risks_hidden"]
    owner = ask(client(db, monkeypatch, "SUPER_ADMIN", reading=False), fid, "risks", preview="shadow")
    assert "fact:no_context_yet" in says(owner)
    unknown = client(db, monkeypatch).get("/api/v1/explain", params={"entity": "match", "id": 999_999_999, "intent": "risks"})
    assert unknown.status_code == 404
    assert int(scalar(db.execute("SELECT count(*) FROM ai.match_packets WHERE fixture_id = %s", (fid,)))) == 0
