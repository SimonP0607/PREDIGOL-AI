"""The odds explorer's endpoints over the real application and a migrated database (plan Cuotas, BE-011).

Three matches of the next day, each with a real answer of the audit stored in RAW, read by the real extractor, asked by the
capture and built into the current-price book by ``fbi.odds.book`` - the way production makes them. One of them was asked 30 h
before its kick-off and never since: its prices are stale (they missed the T-12 h window), shown dimmed, never parlay-ready and
left out of ``sort=edge``. A fourth match is three days away, outside the board's 24 hours."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.odds.book import build
from fbi.odds.quote_extract import run_extraction
from fbi.storage.payload_store import PayloadStore
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.integration.test_odds_book import ask, real_body
from tests.integration.test_odds_quotes_extract import add_payload

NOW = datetime(2026, 10, 22, 14, 0, tzinfo=UTC)
KO = {"A": NOW + timedelta(hours=5), "B": NOW + timedelta(hours=7), "C": NOW + timedelta(hours=20),
      "D": NOW + timedelta(days=3)}
ASKED = {"A": NOW - timedelta(hours=1), "B": KO["B"] - timedelta(hours=30), "C": NOW - timedelta(hours=2),
         "D": NOW - timedelta(hours=1)}
ANSWER = {"A": "premier_league", "B": "serie_a", "C": "copa_del_rey", "D": "primera_a"}
LEAGUES = {"A": (5001, "Liga Uno", "Peru"), "B": (135, "Serie A", "Italy"), "C": (2, "UEFA Champions League", "World"),
           "D": (5002, "Primera A", "Colombia")}
TEAMS = {"A": ("Alianza", "Universitario"), "B": ("Juventus", "Milan"), "C": ("Sevilla", "Betis"),
         "D": ("Millonarios", "Santa Fe")}
PIDS = {"A": 860001, "B": 860002, "C": 860003, "D": 860004}


@dataclass
class World:
    db: psycopg.Connection
    fixtures: dict[str, int]
    competitions: dict[str, int]
    payloads: dict[str, str]


@pytest.fixture()
def world(db: psycopg.Connection, seed: Seed, tmp_path: Path) -> Iterator[World]:
    store = PayloadStore(tmp_path)
    fixtures, competitions, payloads = {}, {}, {}
    for name, (league, comp_name, country) in LEAGUES.items():
        comp = scalar(db.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                                 "competition_type, is_tracked) VALUES (%s, %s, %s, 'league', 'club', 'domestic_league', true) "
                                 "ON CONFLICT (provider_league_id) DO UPDATE SET name = EXCLUDED.name, country = EXCLUDED.country "
                                 "RETURNING id", (league, comp_name, country)))
        season = scalar(db.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) "
                                   "ON CONFLICT (competition_id, season) DO UPDATE SET season = 2026 RETURNING id", (comp,)))
        home, away = (scalar(db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                                        (PIDS[name] * 10 + i, team))) for i, team in enumerate(TEAMS[name]))
        fixtures[name] = int(scalar(db.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id", (PIDS[name], season, home, away, KO[name]))))
        competitions[name] = int(comp)
        payloads[name] = add_payload(db, seed, store, real_body(PIDS[name], KO[name], name=ANSWER[name]), fixture=PIDS[name],
                                     fetched_at=ASKED[name])
    report = run_extraction(db, tmp_path, commit=False, limit=50, now=NOW, since=NOW - timedelta(days=3),
                            until=NOW + timedelta(days=4))
    assert report.payloads_ok == 4, report.as_dict()
    for name in fixtures:
        ask(db, PIDS[name], ASKED[name], payloads[name], kickoff=KO[name])
    built = build(db, tmp_path, list(fixtures.values()), apply=True, now=NOW, commit=False)
    assert built.fixtures_priced == 4 and not built.problems, built.as_dict()
    set_clock(FrozenClock(NOW))
    try:
        yield World(db, fixtures, competitions, payloads)
    finally:
        set_clock(SystemClock())


def client(db: psycopg.Connection, role: str = "USER") -> TestClient:
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def get(c: TestClient, path: str, status: int = 200, **params: Any) -> Any:
    r = c.get(path, params=params)
    assert r.status_code == status, (path, params, r.status_code, r.text[:400])
    return r.json()


def board(c: TestClient, **params: Any) -> dict[str, Any]:
    params.setdefault("market", "result.1x2")
    return dict(get(c, "/api/v1/odds/board", **params)["data"])


def by_fixture(page: dict[str, Any], world: World) -> list[str]:
    names = {v: k for k, v in world.fixtures.items()}
    return [names[r["fixture_id"]] for r in page["rows"]]


# ── /odds/families ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_families_are_those_with_prices_in_the_window(world: World) -> None:
    c = client(world.db)
    data = get(c, "/api/v1/odds/families", hours=24)["data"]
    assert data["window_hours"] == 24 and data["book_enabled"] is False
    families = {f["key"]: f for f in data["families"]}
    assert list(families)[:3] == ["result", "goals", "goals_half"], "the explorer's order"
    result = families["result"]
    assert result["fixtures"] == 3, "A, B and C: D is outside the 24 h"
    one_x_two = next(m for m in result["markets"] if m["key"] == "result.1x2")
    assert one_x_two == {"key": "result.1x2", "family": "result", "kind": "plain", "subject": "match", "periods": ["FT"],
                         "has_line": False, "fair": True, "parlay": True, "fixtures": 3, "max_books": 10}
    halves = next(m for m in families["goals_half"]["markets"] if m["key"] == "result.1x2")
    assert halves["parlay"] is False and set(halves["periods"]) <= {"1H", "2H"}
    assert "players" in families, "the Premier League answer has player markets"
    wider = get(c, "/api/v1/odds/families", hours=72)["data"]
    assert next(f for f in wider["families"] if f["key"] == "result")["fixtures"] == 4
    italy = get(c, "/api/v1/odds/families", hours=24, country="Italy")["data"]
    assert next(f for f in italy["families"] if f["key"] == "result")["fixtures"] == 1
    one = get(c, "/api/v1/odds/families", hours=24, competition=world.competitions["C"])["data"]
    assert {m["max_books"] for f in one["families"] for m in f["markets"]} <= {1, 2, 3}, "the Copa del Rey answer: 3 books"
    nothing = get(c, "/api/v1/odds/families", hours=1)
    assert nothing["status"] == "empty" and nothing["data"]["families"] == []


# ── /odds/board ─────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_board_of_a_market_a_row_per_match_with_its_freshness(world: World) -> None:
    c = client(world.db)
    page = board(c)
    assert by_fixture(page, world) == ["A", "B", "C"] and page["total"] == 3 and page["next_cursor"] is None
    assert page["period"] == "FT" and page["market"]["key"] == "result.1x2" and page["market"]["fixtures"] == 3
    rows = dict(zip(by_fixture(page, world), page["rows"], strict=True))
    assert rows["A"]["state"] == "current" and rows["C"]["state"] == "current"
    assert rows["B"]["state"] == "stale", "asked 30 h before kick-off and not at T-12 h"
    a = rows["A"]
    assert [s["selection"] for s in a["selections"]] == ["Home", "Draw", "Away"] and a["line"] is None and a["lines"] == []
    assert a["home"]["name"] == "Alianza" and a["away"]["name"] == "Universitario"
    assert a["captured_at"].startswith("2026-10-22T13:00") and a["competition_id"] == world.competitions["A"]
    home = a["selections"][0]
    assert isinstance(home["best_odds"], str) and Decimal(home["best_odds"]) > 1 and home["n_books"] == 10
    assert home["fair_odds"] is not None and home["player"] is None
    assert any(s["parlay_ok"] for s in a["selections"]) and not any(s["parlay_ok"] for s in rows["B"]["selections"])
    assert {b["id"] for b in page["bookmakers"]} >= {s["bookmaker_id"] for r in page["rows"] for s in r["selections"]}
    assert all(b["name"] for b in page["bookmakers"])
    assert {x["id"] for x in page["competitions"]} == {world.competitions[n] for n in "ABC"}


def test_the_board_is_paged_on_the_server_with_its_cursor(world: World) -> None:
    c = client(world.db)
    seen: list[str] = []
    params: dict[str, Any] = {"limit": 1}
    for _ in range(4):
        page = board(c, **params)
        seen += by_fixture(page, world)
        assert page["total"] == 3
        if page["next_cursor"] is None:
            break
        params["cursor"] = page["next_cursor"]
    assert seen == ["A", "B", "C"]
    refused = get(c, "/api/v1/odds/board", 422, market="result.1x2", cursor="bm90LWEtY3Vyc29y")
    assert refused["error"]["code"] == "invalid_cursor"
    other_sort = board(c, limit=1)["next_cursor"]
    assert get(c, "/api/v1/odds/board", 422, market="result.1x2", sort="edge", cursor=other_sort)["error"]["code"] == \
        "invalid_cursor"


def test_the_board_orders_by_time_by_the_competition_priority_or_by_edge(world: World) -> None:
    c = client(world.db)
    assert by_fixture(board(c, sort="time"), world) == ["A", "B", "C"]
    assert by_fixture(board(c, sort="competition"), world) == ["B", "C", "A"], \
        "Serie A and the Champions League (group 1 of comp-priority-v1) by name, then the rest"
    edge = board(c, sort="edge")
    assert "B" not in by_fixture(edge, world), "a stale price is never in the order by edge"
    edges = [max(Decimal(s["price_edge"]) for s in r["selections"] if s["price_edge"] is not None and not s["outlier"])
             for r in edge["rows"]]
    assert edges == sorted(edges, reverse=True) and edge["total"] == len(edge["rows"])


def test_the_board_filters_on_the_server(world: World) -> None:
    c = client(world.db)
    assert by_fixture(board(c, q="juve"), world) == ["B"], "a team's name"
    assert by_fixture(board(c, q="liga uno"), world) == ["A"], "a competition's name"
    assert by_fixture(board(c, q="100%_"), world) == [], "the reader's wildcards are literal"
    assert by_fixture(board(c, country="Italy"), world) == ["B"]
    assert by_fixture(board(c, competition=world.competitions["C"]), world) == ["C"]
    assert by_fixture(board(c, bookmaker=11), world) == ["A", "C"], "1xBet does not quote the 1X2 of the Serie A answer"
    assert by_fixture(board(c, bookmaker=8), world) == ["A"]
    assert by_fixture(board(c, min_books=6), world) == ["A"]
    assert by_fixture(board(c, hours=72), world) == ["A", "B", "C", "D"]
    top = max(Decimal(s["best_odds"]) for r in board(c)["rows"] for s in r["selections"])
    assert board(c, odds_min=str(top))["total"] == 1 and board(c, odds_max="1.01")["total"] == 0
    fair = board(c, fair_only="true")
    assert all(any(s["fair_odds"] for s in r["selections"]) for r in fair["rows"])
    empty = get(c, "/api/v1/odds/board", market="result.1x2", q="nobody plays here")
    assert empty["status"] == "empty" and empty["data"]["rows"] == [] and empty["data"]["total"] == 0


def test_a_market_with_lines_shows_each_matchs_main_line_or_the_one_asked_for(world: World) -> None:
    c = client(world.db)
    goals = board(c, market="goals.total")
    for r in goals["rows"]:
        assert r["line"] is not None and Decimal(r["line"]) in {Decimal(x) for x in r["lines"]}
        assert {s["selection"] for s in r["selections"]} == {"Over", "Under"}
    assert {r["line"] for r in goals["rows"]} == {"2.5"}, "2.5 goals first when it is quoted"
    asked = board(c, market="goals.total", line="3.5")
    assert {r["line"] for r in asked["rows"]} == {"3.5"} and asked["rows"]
    ah = board(c, market="result.asian_handicap")["rows"][0]
    home = next(s for s in ah["selections"] if s["selection"] == "Home")
    away = next(s for s in ah["selections"] if s["selection"] == "Away")
    assert Decimal(home["line"]) == Decimal(ah["line"]) == -Decimal(away["line"]), "Home h with Away -h (plan E1)"
    halves = board(c, market="result.1x2", period="1H")
    assert halves["market"]["family"] == "goals_half" and not any(s["parlay_ok"] for r in halves["rows"]
                                                                  for s in r["selections"])


def test_the_board_refuses_what_it_cannot_answer(world: World) -> None:
    c = client(world.db)
    assert get(c, "/api/v1/odds/board", 422, market="corners.everything")["error"]["code"] == "unknown_market"
    assert get(c, "/api/v1/odds/board", 422, market="result.1x2", period="INTERVAL")["error"]["code"] == "unknown_period"
    assert get(c, "/api/v1/odds/board", 422, market="goals.total", line="2.3")["error"]["code"] == "invalid_line"
    assert c.get("/api/v1/odds/board", params={"market": "result.1x2", "limit": 51}).status_code == 422
    assert c.get("/api/v1/odds/board", params={"market": "result.1x2", "sort": "price"}).status_code == 422
    assert c.get("/api/v1/odds/board", params={"market": "DROP TABLE"}).status_code == 422


# ── /matches/{id}/odds-book ─────────────────────────────────────────────────────────────────────────────────────────


def test_a_matchs_book_every_market_line_and_bookmaker(world: World) -> None:
    c = client(world.db)
    data = get(c, f"/api/v1/matches/{world.fixtures['A']}/odds-book")["data"]
    assert data["state"] == "current" and data["fixture_id"] == world.fixtures["A"]
    assert data["captured_at"].startswith("2026-10-22T13:00")
    keys = [f["key"] for f in data["families"]]
    assert keys[:3] == ["result", "goals", "goals_half"] and len(keys) == len(set(keys))
    markets = {(m["info"]["key"], m["period"]): m for f in data["families"] for m in f["markets"]}
    assert len(markets) == 127, "every visible type of the answer"
    total = markets[("goals.total", "FT")]
    assert total["main_line"] == "2.5" and total["info"]["periods"] == ["FT"] and total["info"]["fixtures"] == 1
    for line in total["lines"]:
        for book in line["books"]:
            assert len(book["odds"]) == len(line["selections"])
    one = markets[("result.1x2", "FT")]["lines"][0]
    best = {s["selection"]: Decimal(s["best_odds"]) for s in one["selections"]}
    for book in one["books"]:
        for s, odds in zip(one["selections"], book["odds"], strict=True):
            assert odds is None or Decimal(odds) <= best[s["selection"]]
    assert {b["id"] for b in data["bookmakers"]} == {b["bookmaker_id"] for m in markets.values() for ln in m["lines"]
                                                     for b in ln["books"]}
    scorer = markets.get(("player.anytime_scorer", "FT"))
    assert scorer is not None and scorer["lines"][0]["selections"][0]["selection"] in {"Player", "No Goalscorer"}
    corners = get(c, f"/api/v1/matches/{world.fixtures['A']}/odds-book", family="corners")["data"]
    assert [f["key"] for f in corners["families"]] == ["corners"]
    stale = get(c, f"/api/v1/matches/{world.fixtures['B']}/odds-book", family="result")["data"]
    assert stale["state"] == "stale" and not any(s["parlay_ok"] for m in stale["families"][0]["markets"]
                                                 for ln in m["lines"] for s in ln["selections"])


def test_a_match_without_a_book_and_what_is_refused(world: World, seed: Seed) -> None:
    c = client(world.db)
    none = get(c, f"/api/v1/matches/{seed.fixture_id}/odds-book")
    assert none["status"] == "empty" and none["data"]["state"] == "none" and none["data"]["families"] == []
    assert get(c, "/api/v1/matches/999999999/odds-book", 404)["error"]["code"] == "not_found"
    assert get(c, f"/api/v1/matches/{world.fixtures['A']}/odds-book", 422, family="nothing")["error"]["code"] == \
        "unknown_family"


# ── /odds/fixtures/{id}/movement ────────────────────────────────────────────────────────────────────────────────────


def test_the_movement_of_a_classic_market_comes_from_the_captures_series(world: World) -> None:
    db, fid = world.db, world.fixtures["A"]
    bookmaker = {int(a): int(b) for a, b in db.execute("SELECT provider_bookmaker_id, id FROM market.bookmakers").fetchall()}
    entry = real_body(PIDS["A"], KO["A"])["response"][0]
    for at, bump in ((KO["A"] - timedelta(hours=24), Decimal("0")), (KO["A"] - timedelta(hours=6), Decimal("0.10"))):
        for book in entry["bookmakers"]:
            for bet in book["bets"]:
                if bet["id"] == 1:
                    for v in bet["values"]:
                        db.execute("INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, "
                                   "odds_decimal, captured_at, minutes_to_ko, source, payload_hash) "
                                   "VALUES (%s, %s, '1X2', %s, 0, %s, %s, %s, 'prematch', %s)",
                                   (fid, bookmaker[book["id"]], v["value"], Decimal(v["odd"]) + bump, at,
                                    int((KO["A"] - at).total_seconds() // 60), world.payloads["A"]))
    data = get(client(db), f"/api/v1/odds/fixtures/{fid}/movement", market="result.1x2")["data"]
    assert data["available"] is True and data["source"] == "snapshots" and data["line"] is None
    series = {s["selection"]: s for s in data["series"]}
    assert set(series) == {"Home", "Draw", "Away"}
    home = series["Home"]["points"]
    assert len(home) == 2 and Decimal(home[1]["best_odds"]) > Decimal(home[0]["best_odds"])
    assert {p["bookmaker_id"] for s in data["series"] for p in s["points"]} <= {b["id"] for b in data["bookmakers"]}


def test_the_movement_of_an_extracted_type_comes_from_the_price_clock_and_others_have_none(world: World) -> None:
    c = client(world.db)
    corners = get(c, f"/api/v1/odds/fixtures/{world.fixtures['A']}/movement", market="corners.total")["data"]
    assert corners["available"] is True and corners["source"] == "quotes" and corners["line"] is not None
    assert corners["series"] and all(len(s["points"]) == 1 for s in corners["series"]), "one capture so far"
    players = get(c, f"/api/v1/odds/fixtures/{world.fixtures['A']}/movement", market="player.anytime_scorer")
    assert players["status"] == "not_available" and players["data"]["available"] is False
    assert players["data"]["series"] == []


# ── /admin/odds/health ──────────────────────────────────────────────────────────────────────────────────────────────


def test_the_health_panel_is_the_owners(world: World) -> None:
    data = get(client(world.db, "SUPER_ADMIN"), "/api/v1/admin/odds/health")["data"]
    assert [h["horizon"] for h in data["by_horizon"]] == ["0-6h", "6-24h", "24-72h"]
    near = data["by_horizon"][0]
    assert near["with_book"] >= 1 and near["median_age_min"] is not None
    assert sum(h["stale"] for h in data["by_horizon"]) >= 1, "B missed its T-12 h window"
    assert data["book_rows"] > 0 and data["book_mb"] > 0 and data["quota_limit"] > 0
    assert data["odds_quotes_brake_gb"] == 25.0 and data["default_partition_rows"] >= 0
    assert data["extraction_lag_min"] is not None
    assert client(world.db, "USER").get("/api/v1/admin/odds/health").status_code == 403


def test_auth_me_says_whether_the_page_shows_the_explorer(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.integration.test_pick_states import client as session_client

    monkeypatch.delenv("FBI_ODDS_EXPLORER", raising=False)
    c = session_client(world.db)
    assert c.get("/api/v1/auth/me").json()["odds_explorer"] is False, "off while the line is absent"
    monkeypatch.setenv("FBI_ODDS_EXPLORER", "1")
    assert c.get("/api/v1/auth/me").json()["odds_explorer"] is True
    monkeypatch.setenv("FBI_ODDS_EXPLORER", "maybe")
    assert c.get("/api/v1/auth/me").json()["odds_explorer"] is False, "a value it cannot read is off"
