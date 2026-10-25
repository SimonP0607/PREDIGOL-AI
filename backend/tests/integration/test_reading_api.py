"""The structured reading of a match over HTTP (plan UX, A9) in a real database: six sections of facts, each with its reference,
read from the match packet PrediGol Intelligence stored and from the forecast a reader may see - and nothing of what a reader is
never shown (the text of a rumour, a link, a price, a bookmaker, a model's name, an edge). The transaction is rolled back."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.services import forecast as forecast_service
from fbi.api.services import reading as service
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.integration.test_match_forecast import AT, World, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration

RUMOUR = "Se dice que el portero titular no viajó con el equipo"
LINK = "https://rumours.example/portero"

CONTENT: dict[str, Any] = {
    "fixture": {"competition": "Premier League", "round": "Regular Season - 9", "neutral": False,
                "home": {"name": "Manchester United"}, "away": {"name": "Liverpool"}},
    "phase": {},
    "stakes": {"home": {"rank": 4, "zone": "europe", "gap_up": None, "zone_above": None, "gap_down": 3,
                        "zone_below": None, "pressure": "europe"},
               "away": {"rank": 1, "zone": "title", "gap_up": None, "gap_down": 2, "zone_below": "europe",
                        "pressure": "title"}},
    "scenarios": {"table": {"after": {
        "home_win": {"home": {"points": 20, "rank_best": 2, "rank_worst": 4}, "away": {"points": 22, "rank_best": 1, "rank_worst": 2}},
        "draw": {"home": {"points": 18, "rank_best": 4, "rank_worst": 5}, "away": {"points": 23, "rank_best": 1, "rank_worst": 1}},
        "away_win": {"home": {"points": 17, "rank_best": 4, "rank_worst": 6}, "away": {"points": 25, "rank_best": 1, "rank_worst": 1}},
    }}},
    "form": {"home": {"n": 5, "sequence": "WWDLW", "ppg": 2.0, "gf_pg": 1.8, "ga_pg": 1.0},
             "away": {"n": 5, "sequence": "WWWWD", "ppg": 2.6, "gf_pg": 2.4, "ga_pg": 0.6}},
    "schedule": {"home": {"rest_days": 3.0, "matches_last_14d": 4, "next_match": {"days_after": 4.0, "competition": "UEFA Europa League"}},
                 "away": {"rest_days": 6.0, "matches_last_14d": 2, "next_match": None},
                 "calendar": {"complete": True}, "flags": ["home_short_rest", "home_rest_disadvantage"]},
    "h2h": {"n": 8, "n_effective": 2.4, "relevance": "baja",
            "record": {"n": 8, "home_side_wins": 2, "draws": 3, "away_side_wins": 3}},
    "dossier": {"teams": {"home": {"home": {"n": 4, "wins": 3, "draws": 1, "losses": 0},
                                   "all": {"xg_for": 1.71, "xg_against": 1.02, "n_stats": 9},
                                   "streaks": {"unbeaten": 5}},
                          "away": {"away": {"n": 4, "wins": 2, "draws": 1, "losses": 1}, "all": {}, "streaks": {}}},
                "players": {"home": [{"name": "Bruno Fernandes", "goals": 4, "minutes": 810, "assists": 2}],
                            "away": [{"name": "Mohamed Salah", "goals": 7, "minutes": 900, "assists": 3}]},
                "context": {"derby": False}},
    "absences": {"home": {"players": [{"name": "Lisandro Martínez", "key": True, "type": "Missing Fixture"},
                                      {"name": "Tom Heaton", "key": False, "type": "Missing Fixture"}]},
                 "away": {"players": []}},
    "lineups": {"confirmed": False},
    "market": {"observed": True, "selections": [
        {"market": "1X2", "selection": "Home", "line": "0", "p_fair": 0.318, "best_odds": 3.05, "bookmaker": "Bet365",
         "n_bookmakers": 11, "opening_p_fair": 0.352},
        {"market": "1X2", "selection": "Draw", "line": "0", "p_fair": 0.262, "best_odds": 3.70, "bookmaker": "Bet365",
         "n_bookmakers": 11, "opening_p_fair": 0.255},
        {"market": "1X2", "selection": "Away", "line": "0", "p_fair": 0.420, "best_odds": 2.30, "bookmaker": "Pinnacle",
         "n_bookmakers": 11, "opening_p_fair": 0.393},
        {"market": "OU", "selection": "Over", "line": "2.5", "p_fair": 0.585, "best_odds": 1.66, "bookmaker": "Bet365",
         "n_bookmakers": 9},
        {"market": "OU", "selection": "Under", "line": "2.5", "p_fair": 0.415, "best_odds": 2.35, "bookmaker": "Bet365",
         "n_bookmakers": 9}]},
    "models": {"dixon_coles": {"selections": [{"market": "1X2", "selection": "Home", "p": 0.5, "edge_vs_market": 0.18}]}},
    "elo": {"home": 1810, "away": 1905},
    "quality": {"competition_score": {"class": "FULL"}},
    "evidence": [{"status": "RUMOR", "claim": RUMOUR, "url": LINK, "source": "rumours.example"},
                 {"status": "CONTRADICTORY", "claim": "Dos fuentes no coinciden en la alineación", "url": LINK},
                 {"status": "CONFIRMED", "claim": "Lisandro Martínez, baja por lesión", "url": LINK}],
}


def client(db: psycopg.Connection[Any], role: str, monkeypatch: pytest.MonkeyPatch, *, users: bool = True) -> TestClient:
    monkeypatch.setenv(service.USERS_SWITCH, "1" if users else "0")
    monkeypatch.setenv(forecast_service.USERS_SWITCH, "1")
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def url(fid: int, preview: bool = False) -> str:
    return f"/api/v1/matches/{fid}/reading" + ("?preview=shadow" if preview else "")


def match_with_forecast(world: World) -> int:  # noqa: F811
    fid = world.fixture()
    for model in ("poisson", "dixon_coles"):
        world.predict_all(fid, model)
    world.write(fid)
    return fid


def store_packet(db: psycopg.Connection[Any], fid: int, content: dict[str, Any], missing: list[str]) -> None:
    db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, missing) "
               "VALUES (%s, 'packet-v8', %s, %s, %s, %s, %s)",
               (fid, AT, AT + timedelta(minutes=1), "a" * 64, Jsonb(content), missing))


def sections(body: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {s["key"]: s["facts"] for s in body["data"]["sections"]}


def codes(facts: list[dict[str, Any]]) -> list[str]:
    return [f["code"] for f in facts]


def test_a_reader_gets_six_sections_of_facts_each_with_its_reference_and_nothing_a_reader_is_never_shown(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fid = match_with_forecast(world)
    store_packet(db, fid, CONTENT, ["stats"])
    r = client(db, "USER", monkeypatch).get(url(fid))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    data = body["data"]
    assert data["version"] == "reading-v1" and data["complete"] is True and data["fixture_id"] == fid
    assert data["data_at"] is not None and data["forecast_at"] is not None
    got = sections(body)
    assert list(got) == ["summary", "context", "data", "market", "risks", "conclusion"]
    for facts in got.values():
        assert all(f["ref"].startswith(("packet", "forecast")) for f in facts), facts

    assert codes(got["summary"]) == ["match_intro", "expected_result"]
    expected = got["summary"][1]["params"]
    assert expected == {"outcome": "home", "team": "Manchester United", "probability": 0.5, "calibrated": False}
    assert {"stakes_zone", "stakes_pressure", "table_after", "rest_days", "next_match"} <= set(codes(got["context"]))
    assert len([f for f in got["context"] if f["code"] == "table_after"]) == 3, "one line per result"
    rest = next(f for f in got["context"] if f["code"] == "rest_days" and f["params"]["side"] == "home")["params"]
    assert rest["days"] == 3.0 and rest["matches_14d"] == 4 and rest["at_most"] is False, "a whole calendar: the real rest"
    data_codes = codes(got["data"])
    assert data_codes.count("form") == 2 and "h2h" in data_codes and "xg" in data_codes and "streak_unbeaten" in data_codes
    absences = next(f for f in got["data"] if f["code"] == "key_absences")["params"]
    assert absences == {"side": "home", "team": "Manchester United", "count": 1, "players": ["Lisandro Martínez"]}
    favourite = next(f for f in got["market"] if f["code"] == "market_favourite")["params"]
    assert favourite["outcome"] == "away" and favourite["probability"] == 0.42 and favourite["bookmakers"] == 11
    moved = next(f for f in got["market"] if f["code"] == "market_moved")["params"]
    assert (moved["outcome"], moved["opening"], moved["now"]) == ("home", 0.352, 0.318), "the biggest move since the opening"
    risk_codes = codes(got["risks"])
    for code in ("lineups_unconfirmed", "short_rest", "rest_disadvantage", "contradictory_news", "rumours", "h2h_weak",
                 "not_checked", "uncalibrated"):
        assert code in risk_codes, code
    assert next(f for f in got["risks"] if f["code"] == "rumours")["params"] == {"count": 1}, "how many, never what"
    assert next(f for f in got["risks"] if f["code"] == "not_checked")["params"] == {"blocks": ["stats"]}
    likely = {f["params"]["market"]: f["params"] for f in got["conclusion"] if f["code"] == "likely"}
    assert set(likely) == {"1X2", "OU", "BTTS"}
    assert likely["OU"]["outcome"] == "over" and likely["OU"]["line"] == "2.5"

    text = r.text.lower()
    for never in (RUMOUR.lower(), LINK, "rumours.example", "bet365", "pinnacle", "best_odds", "fair_odds", "dixon",
                  "poisson", "edge", "elo", "1810", "3.05", "value", "seguro", "fijo", "garantizado"):
        assert never not in text, never


def test_a_match_without_a_packet_has_a_shorter_reading_that_says_so(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fid = match_with_forecast(world)
    body = client(db, "USER", monkeypatch).get(url(fid)).json()
    assert body["status"] == "ok" and body["data"]["complete"] is False and body["data"]["data_at"] is None
    got = sections(body)
    assert list(got) == ["summary", "risks", "conclusion"]
    assert codes(got["summary"]) == ["match_intro", "expected_result"], "the names a reader knows, even without a packet"
    assert codes(got["risks"])[0] == "no_context_yet"
    assert [f["params"]["market"] for f in got["conclusion"] if f["code"] == "likely"] == ["1X2", "OU", "BTTS"]


def test_risks_are_never_empty_and_a_match_without_a_forecast_says_why(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fid = world.fixture()
    quiet = {"fixture": CONTENT["fixture"], "lineups": {"confirmed": True},
             "evidence": [{"status": "CONFIRMED", "claim": "x"}], "market": {"observed": False, "selections": []}}
    store_packet(db, fid, quiet, [])
    got = sections(client(db, "USER", monkeypatch).get(url(fid)).json())
    assert codes(got["risks"]) == ["none_found"], "nothing stood out: said, never left empty"
    assert codes(got["market"]) == ["market_unpriced"]
    assert codes(got["summary"]) == ["match_intro", "forecast_missing"]
    assert codes(got["conclusion"]) == ["no_forecast"]


def test_the_switch_the_preview_and_an_unknown_match(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fid = match_with_forecast(world)
    off = client(db, "USER", monkeypatch, users=False).get(url(fid))
    assert off.status_code == 200 and off.json()["status"] == "not_available" and off.json()["reason"]
    admin = client(db, "SUPER_ADMIN", monkeypatch, users=False)
    assert admin.get(url(fid)).json()["status"] == "not_available", "without the preview the owner sees what a reader would"
    assert admin.get(url(fid, preview=True)).json()["status"] == "ok"
    refused = client(db, "USER", monkeypatch).get(url(fid, preview=True))
    assert refused.status_code == 403
    assert client(db, "USER", monkeypatch).get(url(999_999_999)).status_code == 404
    # the forecast's own switch: off, the reading neither shows nor leaks it
    monkeypatch.setenv(forecast_service.USERS_SWITCH, "0")
    app = signed_in(create_app(), "USER")
    app.dependency_overrides[get_db] = lambda: db
    hidden = TestClient(app, headers=SAME_SITE).get(url(fid)).json()
    got = sections(hidden)
    assert codes(got["summary"]) == ["match_intro", "forecast_missing"]
    assert got["summary"][1]["params"] == {"reason": "hidden"}
    assert "conclusion" not in got and "uncalibrated" not in codes(got["risks"])
