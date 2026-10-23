"""A finished match put together as one object, over HTTP (plan F7): who sees it, what a user is never shown, what the Admin Console's
preview adds, and what is said when there is nothing to show."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.api.app import create_app
from fbi.api.contracts import knowledge as contract
from fbi.api.deps import get_db
from fbi.api.services import knowledge as service
from fbi.knowledge import builder, layers, reader
from tests.integration.signed_in import SAME_SITE, signed_in

from .conftest import Seed
from .knowledge_world import KICKOFF, NOW, World, ev, goal

pytestmark = pytest.mark.integration


def client(db: psycopg.Connection[Any], role: str | None, monkeypatch: pytest.MonkeyPatch, *, users: bool = True) -> TestClient:
    monkeypatch.setenv(service.USERS_SWITCH, "1" if users else "0")
    monkeypatch.setattr(service, "now", lambda: NOW)
    app = create_app()
    if role is not None:
        signed_in(app, role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def url(fid: int, preview: bool = False) -> str:
    return f"/api/v1/matches/{fid}/knowledge" + ("?preview=shadow" if preview else "")


def built_golden(db: psycopg.Connection[Any], seed: Seed) -> tuple[World, int]:
    w = World(db, seed)
    fid = w.golden()
    assert builder.build_many(db, [fid], commit=False).built == 1
    return w, fid


def knowledge_of(body: dict[str, Any]) -> dict[str, Any]:
    assert body["status"] == "ok" and body["data"]["knowledge"]["status"] == "ok", body
    data: dict[str, Any] = body["data"]["knowledge"]["data"]
    return data


# ── who sees it ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_user_gets_nothing_until_the_owner_decides_and_then_only_the_facts(db: psycopg.Connection[Any], seed: Seed,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    _, fid = built_golden(db, seed)

    off = client(db, "USER", monkeypatch, users=False).get(url(fid))
    assert off.status_code == 200
    assert off.json()["status"] == "not_available" and off.json()["data"] is None and off.json()["reason"], "said, not left blank"
    assert "Man 501" not in off.text and "mk-v1" not in off.text, "nothing of the match leaves while it is off"

    on = client(db, "USER", monkeypatch, users=True).get(url(fid))
    assert on.status_code == 200
    body = on.json()
    k = knowledge_of(body)
    assert body["data"]["fixture_id"] == fid and body["data"]["status_group"] == "finished"
    assert body["data"]["stored"] is None, "no row as stored beside it"
    assert (k["version"], k["completeness"], k["quality"]) == ("mk-v1", "complete", {"events_give_the_score": True, "doubts": []})
    assert body["meta"]["data_as_of"] is not None
    assert [name for name in k if k[name] and isinstance(k[name], dict) and "status" in k[name]] == [
        "result", "team_stats", "events", "players", "tactics", "market"], "the layers of facts, and no other"
    assert all(k[name]["status"] == "ok" for name in ("result", "team_stats", "events", "players", "tactics", "market"))

    # the preview is not a user's to ask for, whether or not users see the knowledge
    for users in (False, True):
        refused = client(db, "USER", monkeypatch, users=users).get(url(fid, preview=True))
        assert refused.status_code == 403, "403 for an account without the shadow-preview permission"
        assert "Man 501" not in refused.text and "c8_picks" not in refused.text


def test_a_user_is_told_the_facts_layer_by_layer(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    _, fid = built_golden(db, seed)
    k = knowledge_of(client(db, "USER", monkeypatch).get(url(fid)).json())

    result = k["result"]["data"]
    assert (result["match_status"], result["reg"], result["ht"], result["outcome"], result["total"], result["btts"]) == (
        "FT", [2, 1], [1, 0], "Home", 3, True)
    assert (result["decided_by"], result["final"], result["pen"], result["tie"], result["neutral"], result["corrected"]) == (
        "regulation", None, None, None, False, False)

    stats = k["team_stats"]["data"]
    assert (stats["home"]["shots"], stats["home"]["on_target"], stats["home"]["possession"], stats["home"]["xg"]) == (14, 6, 54.5, 1.87)
    assert (stats["away"]["shots"], stats["away"]["red"], stats["away"]["off_target"]) == (9, 0, None), "a figure the provider did not give is null"

    events = k["events"]["data"]
    assert events["rules"] == "events-v1" and events["n"] == 8 and events["check"]["reg"] is True and events["check"]["listed"] is None
    assert [(e["minute"], e["side"], e["kind"], e["player"]) for e in events["goals"]] == [
        (12, "home", "goal", 501), (70, "away", "penalty_goal", 602), (85, "home", "goal", 505)]
    assert [e["kind"] for e in events["cards"]] == ["yellow", "yellow", "second_yellow"]
    assert [(e["kind"], e["minute"]) for e in events["var"]] == [("var_goal_cancelled", 88)]
    assert events["by_period"] == {"1H": [1, 0], "2H": [1, 1]} and events["shootout"] == [] and events["missed"] == []

    players = k["players"]["data"]
    assert [(p["player_id"], p["rating"], p["goals"]) for p in players["home"]["top"]] == [(505, 8.4, 1), (501, 8.1, 1), (504, 6.9, 0)]
    assert (players["home"]["started"], players["home"]["came_on"], players["home"]["captain_id"]) == (4, 1, 501)
    assert players["goals_with_no_player"] == 0

    tactics = k["tactics"]["data"]
    assert (tactics["home"]["formation"], tactics["away"]["formation"]) == ("4-3-3", "4-4-2")
    assert tactics["home"]["substitutions"] == [{"minute": 80, "lead": 0}]
    assert tactics["story"]["first_goal"] == {"minute": 12, "side": "home"} and tactics["story"]["lead_changes"] == 0
    assert tactics["story"]["minutes"] == {"home_ahead": 63, "level": 27, "away_ahead": 0}
    assert tactics["story"]["first_dismissal"] == {"minute": 60, "side": "home", "lead": 1}

    market = k["market"]["data"]["markets"]
    assert list(market) == ["1X2", "OU", "BTTS"], "the order of the board, not the database's"
    home = market["1X2"]
    assert home["probabilities"]["Home"] == [0.45, 0.5] and home["books"] == 10 and home["minutes_to_kickoff"] == 20 and home["line"] is None
    assert home["final"] == {"odds": {"Away": 4.4, "Draw": 3.5, "Home": 1.85}, "books": 4, "at": "2034-05-02T17:35:00Z", "minutes_to_kickoff": 85}
    assert market["OU"]["line"] == 2.5 and market["OU"]["final"]["odds"]["Over"] == 1.95


def test_what_the_build_keeps_to_itself_never_reaches_a_user(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    """A user is shown the facts of the match through the models of the contract and nothing else: not where a layer was read from, not
    the decision layer's lines, the picks, the post-mortems, the coach's key, the corrections of the result or the hashes of the row."""
    w, fid = built_golden(db, seed)
    w.revision(fid, KICKOFF + timedelta(hours=5))
    builder.build_many(db, [fid], commit=False)
    stored = db.execute("SELECT layers FROM intel.match_knowledge WHERE fixture_id = %s ORDER BY id DESC LIMIT 1", (fid,)).fetchone()
    assert stored is not None and "revisions" in stored[0][layers.C1_RESULT]["data"] and "coach" in stored[0][layers.C5_TACTICS]["data"]["home"], (
        "the row does have them: the test is about what is left out")

    text = client(db, "USER", monkeypatch).get(url(fid)).text
    keys: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                keys.add(key)
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    walk(json.loads(text))
    assert not keys & {"sources", "coach", "decisions", "picks", "postmortem", "verdict", "profit", "clv", "edge", "stake", "inputs_hash",
                       "content_hash", "revisions", "supersedes", "layers", "chain", "c1_result", "c8_picks", "c9_postmortem", "c7_context"}, keys
    for word in ("core.", "intel.", "market.", "c1_result", "c8_picks", "c9_postmortem", "c7_context", "Coach Home", "name:coach", "MERECIDO",
                 "PICK_PREMIUM", "RECHAZADO", "decided_by_the_owner"):
        assert word not in text, f"{word!r} reached a user"
    assert json.loads(text)["data"]["knowledge"]["data"]["result"]["data"]["corrected"] is True, "that the result was corrected is said; how, is not"


def test_the_markets_keep_the_order_of_the_board_whatever_order_the_row_keeps(db: psycopg.Connection[Any], seed: Seed,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    fid = w.golden()
    opening, closing = KICKOFF - timedelta(days=6), KICKOFF - timedelta(minutes=20)
    for selection, p_open, p_close in (("Home", 0.50, 0.55), ("Away", 0.50, 0.45)):
        w.quote(fid, "AH", selection, -0.5, p_open, opening)
        w.quote(fid, "AH", selection, -0.5, p_close, closing)
    assert builder.build_many(db, [fid], commit=False).built == 1
    stored = db.execute("SELECT layers FROM intel.match_knowledge WHERE fixture_id = %s", (fid,)).fetchone()
    assert stored is not None and list(stored[0][layers.C6_MARKET]["data"]) != ["1X2", "OU", "BTTS", "AH"], "the row keeps its keys in the database's order"

    markets = knowledge_of(client(db, "USER", monkeypatch).get(url(fid)).json())["market"]["data"]["markets"]
    assert list(markets) == ["1X2", "OU", "BTTS", "AH"]
    assert markets["AH"]["line"] == -0.5 and markets["AH"]["final"] is None, "nobody quoted its last prices: said as nothing"
    assert markets["AH"]["probabilities"] == {"Away": [0.5, 0.45], "Home": [0.5, 0.55]}


# ── the Admin Console's preview ──────────────────────────────────────────────────────────────────────────────────────────


def test_the_admin_preview_adds_the_row_as_stored_and_the_chain_of_rebuilds(db: psycopg.Connection[Any], seed: Seed,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    _, fid = built_golden(db, seed)
    admin = client(db, "SUPER_ADMIN", monkeypatch, users=False)

    plain = admin.get(url(fid))  # without the preview the admin sees what a user would: the switch decides
    assert plain.json()["status"] == "not_available" and plain.json()["data"] is None

    body = admin.get(url(fid, preview=True)).json()
    k = knowledge_of(body)
    stored = body["data"]["stored"]
    assert k["completeness"] == "complete" and k["result"]["data"]["reg"] == [2, 1], "the same facts a user would be given"
    assert list(stored["layers"]) and set(stored["layers"]) == set(layers.LAYERS), "all nine layers, as stored"
    assert stored["layers"][layers.C7_CONTEXT] == {"status": "off", "notes": ["decided_by_the_owner"]}
    assert stored["layers"][layers.C8_PICKS]["data"]["decisions"]["top"][0]["state"] == "PICK_PREMIUM"
    assert stored["layers"][layers.C9_POSTMORTEM]["data"]["items"][0]["verdict"] == "MERECIDO"
    assert stored["layers"][layers.C5_TACTICS]["data"]["home"]["coach"] == "name:coach home"
    assert "core.fixture_events" in stored["layers"][layers.C3_EVENTS]["sources"]
    assert len(stored["inputs_hash"]) == len(stored["content_hash"]) == 64 and stored["supersedes"] is None
    assert [c["id"] for c in stored["chain"]] == [stored["id"]] and stored["chain"][0]["content_hash"] == stored["content_hash"]

    # the provider re-reads the match and its figures changed: a new row that names the one it replaced, and the newest is what the match is
    db.execute("UPDATE core.fixture_team_stats SET shots = 15 WHERE fixture_id = %s AND team_side = 'home'", (fid,))
    assert builder.build_many(db, [fid], commit=False).built == 1
    again = admin.get(url(fid, preview=True)).json()
    newest = again["data"]["stored"]
    assert newest["id"] > stored["id"] and newest["supersedes"] == stored["id"]
    assert [c["id"] for c in newest["chain"]] == [stored["id"], newest["id"]]
    assert [c["supersedes"] for c in newest["chain"]] == [None, stored["id"]]
    assert newest["content_hash"] != stored["content_hash"]
    assert knowledge_of(again)["team_stats"]["data"]["home"]["shots"] == 15

    users = client(db, "USER", monkeypatch).get(url(fid)).json()
    assert knowledge_of(users)["team_stats"]["data"]["home"]["shots"] == 15 and users["data"]["stored"] is None


def test_the_row_is_read_as_of_the_moment_asked(db: psycopg.Connection[Any], seed: Seed) -> None:
    """``at`` is the moment the question is asked about: what the match was, as PrediGol had put it together by then."""
    _, fid = built_golden(db, seed)
    first = db.execute("SELECT built_at FROM intel.match_knowledge WHERE fixture_id = %s", (fid,)).fetchone()
    assert first is not None
    built = first[0]
    before = service.match_knowledge(db, fid, preview=True, at=built - timedelta(seconds=1))
    assert before.data is not None and before.data.knowledge.data is None and before.data.knowledge.code in {"not_settled_yet", "no_build_yet"}
    after = service.match_knowledge(db, fid, preview=True, at=built + timedelta(seconds=1))
    assert after.data is not None and after.data.knowledge.data is not None


# ── when there is nothing to show ────────────────────────────────────────────────────────────────────────────────────────


def test_a_match_with_no_knowledge_says_why(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    live = w.match(NOW - timedelta(hours=1), group="live", status="2H", goals=None)
    fresh = w.match(NOW - timedelta(hours=10), goals=(1, 0))
    unbuilt = w.golden()
    elsewhere = w.golden(KICKOFF + timedelta(hours=1))
    db.execute("UPDATE core.competition_seasons SET competition_id = (SELECT id FROM core.competitions WHERE provider_league_id = 98971) "
               "WHERE id = %s", (w.season,))
    other = db.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, is_tracked) "
                       "VALUES (98972, 'Not Followed', 'Colombia', 'league', 'club', 'domestic_league', false) RETURNING id").fetchone()
    assert other is not None
    season = db.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2034, true) RETURNING id",
                        (other[0],)).fetchone()
    assert season is not None
    db.execute("UPDATE core.fixtures SET competition_season_id = %s WHERE id = %s", (season[0], elsewhere))

    asked = client(db, "USER", monkeypatch)
    why = {}
    for name, fid in (("live", live), ("fresh", fresh), ("unbuilt", unbuilt), ("elsewhere", elsewhere)):
        body = asked.get(url(fid)).json()
        assert body["status"] == "ok" and body["data"]["fixture_id"] == fid, "the match is there; what is missing is its knowledge"
        section = body["data"]["knowledge"]
        assert section["status"] == "not_available" and section["data"] is None and section["reason"], "a reason a person can read"
        assert body["data"]["stored"] is None
        why[name] = section["code"]
    assert why == {"live": "not_finished", "fresh": "not_settled_yet", "unbuilt": "no_build_yet", "elsewhere": "not_followed"}

    missing = asked.get(url(999999999))
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert asked.get("/api/v1/matches/0/knowledge").status_code == 422, "an id is a positive number"


def test_only_a_signed_in_account_asks(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    _, fid = built_golden(db, seed)
    anonymous = client(db, None, monkeypatch).get(url(fid))
    assert anonymous.status_code == 401 and "Man 501" not in anonymous.text


# ── what the build can leave out, and what the contract cannot read ─────────────────────────────────────────────────────


def test_a_match_with_only_its_result_has_every_other_layer_missing(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    fid = World(db, seed).match()
    assert builder.build_many(db, [fid], commit=False).built == 1
    k = knowledge_of(client(db, "USER", monkeypatch).get(url(fid)).json())
    assert k["completeness"] == "minimal" and k["result"]["status"] == "ok" and k["result"]["data"]["reg"] == [2, 1]
    for name in ("team_stats", "events", "players", "tactics", "market"):
        assert k[name]["status"] == "missing" and k[name]["data"] is None, name
    assert k["events"]["notes"] == ["no_events"] and k["quality"]["events_give_the_score"] is None


def test_a_match_with_no_result_row_is_minimal_and_says_so(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    fid = World(db, seed).match(goals=None)
    assert builder.build_many(db, [fid], commit=False).built == 1
    k = knowledge_of(client(db, "USER", monkeypatch).get(url(fid)).json())
    assert k["completeness"] == "minimal" and k["result"]["status"] == "missing" and k["result"]["data"] is None
    assert k["result"]["notes"] == ["no_result_row"] and "no_result" in k["quality"]["doubts"]


def test_a_match_decided_on_penalties_tells_how(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    fid = w.match(KICKOFF, goals=(2, 2), ft=(1, 1), et=(1, 1), pen=(4, 3), ht=(1, 0), status="PEN")
    lines = [goal(0, 20, "home", 501), goal(1, 70, "away", 601), goal(2, 100, "home", 502), goal(3, 115, "away", 602)]
    scored = {"home": [True, True, True, False, True], "away": [True, True, False, True, False]}
    for kick in range(5):
        for side, player in (("home", 510 + kick), ("away", 610 + kick)):
            lines.append(ev(len(lines), 120, side, "Goal", "Penalty" if scored[side][kick] else "Missed Penalty", player=player,
                            name=f"Man {player}", comments="Penalty Shootout"))
    w.events(fid, lines)
    builder.build_many(db, [fid], commit=False)

    k = knowledge_of(client(db, "USER", monkeypatch).get(url(fid)).json())
    result, events = k["result"]["data"], k["events"]["data"]
    assert (result["match_status"], result["reg"], result["final"], result["pen"], result["decided_by"]) == ("PEN", [1, 1], [2, 2], [4, 3], "penalties")
    assert events["by_period"] == {"1H": [1, 0], "2H": [0, 1], "ET": [1, 1], "PEN": [4, 3]}
    assert len(events["shootout"]) == 10 and {e["period"] for e in events["shootout"]} == {"PEN"}
    assert [e["kind"] for e in events["shootout"]].count("shootout_miss") == 3
    assert all(e["period"] != "PEN" for e in events["goals"]), "a kick of the shoot-out is not a goal of the match"


def test_a_leg_of_a_tie_says_what_the_tie_came_to_only_when_it_closed_it(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    fid = w.match(KICKOFF, home=0, away=1, goals=(1, 0), status="FT")
    stage = db.execute(
        "INSERT INTO core.competition_stages (competition_season_id, stage, ordinal, phase, base_stage, kind, role, rule, numbered, fixtures, "
        "first_kickoff_at, last_kickoff_at, ties, stages_version, ties_version, build_hash) VALUES (%s, 'Final', 1, 'knockout', 'Final', 'knockout', "
        "'final', 'test', false, 1, %s, %s, 1, 'stages-v1', 'ties-v1', 'x') RETURNING id", (w.season, KICKOFF, KICKOFF)).fetchone()
    assert stage is not None
    tie = db.execute(
        "INSERT INTO core.ties (stage_id, team_a_id, team_b_id, format, status, legs, played, aggregate_a, aggregate_b, winner_team_id, decided_by, "
        "winner_check, version) VALUES (%s, %s, %s, 'single', 'decided', 1, 1, 1, 0, %s, 'normal_time', 'confirmed', 'ties-v1') RETURNING id",
        (stage[0], w.team[0], w.team[1], w.team[0])).fetchone()
    assert tie is not None
    db.execute("UPDATE core.fixtures SET tie_id = %s, stage_id = %s, leg = 1 WHERE id = %s", (tie[0], stage[0], fid))
    builder.build_many(db, [fid], commit=False)

    k = knowledge_of(client(db, "USER", monkeypatch).get(url(fid)).json())
    assert k["result"]["data"]["tie"] == {"format": "single", "legs": 1, "leg": 1, "aggregate": [1, 0], "winner": "home",
                                          "decided_by": "normal_time", "shootout": None, "contradicted": False}


def insert_row(db: psycopg.Connection[Any], fid: int, *, changed: dict[str, Any]) -> None:
    """A row as an older or a broken build could have left it: the layers of the real build, with some of them replaced."""
    built = layers.build(reader.read(db, [fid])[fid].inputs)
    stored = {**built.layers, **changed}
    db.execute("INSERT INTO intel.match_knowledge (fixture_id, version, supersedes, known_at, inputs_hash, content_hash, completeness, layers, "
               "quality) VALUES (%s, %s, NULL, %s, %s, %s, %s, %s, %s)",
               (fid, built.version, built.known_at, "a" * 64, layers.content_hash(stored, built.quality, built.completeness),
                built.completeness, Jsonb(stored), Jsonb(built.quality)))


def test_a_layer_the_contract_cannot_read_is_reported_missing_and_the_rest_is_given(db: psycopg.Connection[Any], seed: Seed,
                                                                                   monkeypatch: pytest.MonkeyPatch,
                                                                                   caplog: pytest.LogCaptureFixture) -> None:
    fid = World(db, seed).golden()
    insert_row(db, fid, changed={
        layers.C4_PLAYERS: {"status": "ok", "known_at": "2034-05-02T22:00:00Z", "sources": ["x"], "data": {"home": {"listed": "many"}}},
        layers.C6_MARKET: {"status": "ok", "known_at": "2034-05-02T22:00:00Z", "data": {"1X2": {"p": {"Home": [0.4]}}}, "notes": ["odd"]},
        layers.C2_TEAM_STATS: {"status": "mystery", "data": {"home": {"shots": 1}}},
    })
    body = client(db, "USER", monkeypatch).get(url(fid)).json()
    k = knowledge_of(body)
    assert k["players"] == {"status": "missing", "known_at": "2034-05-02T22:00:00Z", "notes": ["unreadable"], "data": None}
    assert k["market"]["status"] == "missing" and k["market"]["notes"] == ["odd", "unreadable"] and k["market"]["data"] is None
    assert k["team_stats"]["status"] == "missing" and k["team_stats"]["data"] is None, "a status the rules do not have is not believed"
    assert k["result"]["status"] == "ok" and k["events"]["status"] == "ok" and k["tactics"]["status"] == "ok", "the layers that can be read are given"


def test_a_field_the_build_adds_later_is_not_shown_until_the_contract_names_it(db: psycopg.Connection[Any], seed: Seed,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    fid = World(db, seed).golden()
    built = layers.build(reader.read(db, [fid])[fid].inputs)
    result = json.loads(json.dumps(built.layers[layers.C1_RESULT]))
    result["data"]["referee_opinion"] = "a field of a later version"
    result["data"]["tie"] = {"format": "single", "legs": 1, "secret": 1}
    stats = json.loads(json.dumps(built.layers[layers.C2_TEAM_STATS]))
    stats["data"]["home"]["held_back"] = 99
    insert_row(db, fid, changed={layers.C1_RESULT: result, layers.C2_TEAM_STATS: stats})
    text = client(db, "USER", monkeypatch).get(url(fid)).text
    assert "referee_opinion" not in text and "secret" not in text and "held_back" not in text and "a field of a later version" not in text
    assert json.loads(text)["data"]["knowledge"]["data"]["result"]["data"]["tie"]["format"] == "single"


# ── the contract and the rules it reads ─────────────────────────────────────────────────────────────────────────────────


def test_the_service_reads_the_rules_the_worker_writes() -> None:
    assert service.VERSION == layers.VERSION == "mk-v1"
    assert service.SETTLE == builder.SETTLE
    assert service.USERS_SWITCH == "FBI_KNOWLEDGE_USERS"
    assert set(service.MARKET_ORDER) == set(layers.MARKETS)


def test_every_figure_the_team_layer_keeps_has_a_place_in_the_contract() -> None:
    assert set(layers.TEAM_STAT_KEYS.values()) == set(contract.TeamFigures.model_fields), "a figure kept and not named would never be shown"
    stored_event_keys = {"seq", "kind", "period", "minute", "extra", "side", "player_side", "player", "name", "assist", "assist_name", "pair", "flags"}
    assert stored_event_keys == set(contract.EventLine.model_fields)
