"""GET /matches/{id}/markets/catalog over the real application and a migrated database (plan Partidos y Match Center, F4a).

The prices are seeded the way production makes them: RAW /odds bodies read by the real extractor into market.odds_quotes, and
the asks of the capture in market.odds_asks. The case the route exists for is A -> B -> A: RAW keeps body A once, so the newest
quote rows are B's, and the price in force is A's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.odds.quote_extract import run_extraction
from fbi.storage.payload_store import PayloadStore
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.integration.test_odds_quotes_extract import add_fixture, add_payload, bet

KO = datetime(2026, 10, 20, 19, 0, tzinfo=UTC)
T1, T2, T3 = KO - timedelta(hours=30), KO - timedelta(hours=20), KO - timedelta(hours=10)
PID = 830001


def body(over_bet365: str, over_pinnacle: str) -> dict[str, Any]:
    """One answer: two bookmakers, the five-market 1X2, corners (total and the double chance under 307 AND 339), cards."""
    return {"get": "odds", "results": 1, "paging": {"current": 1, "total": 1}, "response": [{
        "fixture": {"id": PID, "date": KO.isoformat(), "timestamp": int(KO.timestamp())},
        "update": (KO - timedelta(days=1)).isoformat(),
        "bookmakers": [
            {"id": 8, "name": "Bet365", "bets": [
                bet(1, "Match Winner", ("Home", "2.10"), ("Draw", "3.40"), ("Away", "3.60")),
                bet(45, "Corners Over Under", ("Over 9.5", over_bet365), ("Under 9.5", "1.90")),
                bet(307, "Corners. Double Chance", ("Home/Draw", "1.30")),
                bet(80, "Cards Over/Under", ("Over 4.5", "1.85")),
            ]},
            {"id": 11, "name": "Pinnacle", "bets": [
                bet(45, "Corners Over Under", ("Over 9.5", over_pinnacle), ("Under 9.5", "1.85")),
                bet(339, "Corners. Double Chance", ("Home/Draw", "1.33"), ("Draw/Away", "1.70")),
            ]},
        ],
    }]}


def ask(db: psycopg.Connection, asked_at: datetime, payload_hash: str | None, results: int = 1) -> None:
    db.execute("INSERT INTO market.odds_asks (provider_fixture_id, asked_at, minutes_to_ko, window_minutes, results, "
               "quotes, payload_hash) VALUES (%s, %s, %s, NULL, %s, 0, %s)",
               (PID, asked_at, int((KO - asked_at).total_seconds() // 60), results, payload_hash))


def seeded(db: psycopg.Connection, seed: Seed, root: Path) -> tuple[int, str, str]:
    """The match, bodies A (T1) and B (T2) in RAW and structured, and the asks T1 -> A, T2 -> B, T3 -> A again."""
    fixture_id = add_fixture(db, seed, PID, KO)
    store = PayloadStore(root)
    a = add_payload(db, seed, store, body("1.90", "1.95"), fixture=PID, fetched_at=T1)
    b = add_payload(db, seed, store, body("2.20", "2.15"), fixture=PID, fetched_at=T2)
    report = run_extraction(db, root, commit=False, limit=50, since=KO - timedelta(days=5), until=KO)
    assert report.payloads_ok == 2, report.as_dict()
    ask(db, T1, a)
    ask(db, T2, b)
    ask(db, T3, a)  # the provider answered A again: RAW keeps no second copy, the ask says so
    return fixture_id, a, b


@pytest.fixture()
def client(db: psycopg.Connection) -> TestClient:
    app = signed_in(create_app(), "USER")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def url(fixture_id: int, category: str | None = None) -> str:
    return f"/api/v1/matches/{fixture_id}/markets/catalog" + (f"?category={category}" if category else "")


def at(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def test_after_a_b_a_a_user_reads_a(db: psycopg.Connection, seed: Seed, tmp_path: Path, client: TestClient) -> None:
    fixture_id, _a, b = seeded(db, seed, tmp_path)
    # the trap: the newest rows of the corners total are B's
    newest = scalar(db.execute(
        "SELECT q.odds_decimal FROM market.odds_quotes q JOIN market.market_definitions d ON d.id = q.definition_id "
        "JOIN market.bookmakers k ON k.id = q.bookmaker_id WHERE q.fixture_id = %s AND d.provider_bet_id = 45 "
        "AND q.selection = 'Over' AND k.provider_bookmaker_id = 11 ORDER BY q.captured_at DESC LIMIT 1", (fixture_id,)))
    assert str(newest) == "2.150"

    res = client.get(url(fixture_id))
    assert res.status_code == 200, res.text
    env = res.json()
    data = env["data"]
    assert env["status"] == "ok" and data["state"] == "priced"
    assert at(data["checked_at"]) == T3 and not data["newer_answer_pending"] and not data["partial"]
    assert data["category"] is None and data["markets"] == []
    assert [(c["key"], c["markets"], c["bookmakers"]) for c in data["categories"]] == [
        ("result", 1, 1), ("corners", 2, 2), ("cards", 1, 1)]

    corners = client.get(url(fixture_id, "corners")).json()["data"]
    by_key = {m["key"]: m for m in corners["markets"]}
    assert list(by_key) == ["corners_over_under.FT.match", "corners_double_chance.FT.match"]
    over = next(s for s in by_key["corners_over_under.FT.match"]["selections"] if s["selection"] == "Over")
    assert (over["best_odds"], over["bookmaker"], over["bookmakers"]) == ("1.950", "Pinnacle", 2), "A's price, not B's"
    assert [b["odds"] for b in over["books"]] == ["1.950", "1.900"]
    assert at(over["captured_at"]) == T3, "in force since the ask that brought A back"

    dc = by_key["corners_double_chance.FT.match"]
    assert dc["bet_ids"] == [307, 339] and dc["market_key"] is None and dc["bookmakers"] == 2
    one_x = next(s for s in dc["selections"] if s["selection"] == "1X")
    assert [(b["bookmaker"], b["bet_id"]) for b in one_x["books"]] == [("Pinnacle", 339), ("Bet365", 307)]

    result = client.get(url(fixture_id, "result")).json()["data"]["markets"]
    assert [(m["key"], m["market_key"]) for m in result] == [("result_1x2.FT.match", "1X2")]

    # nothing was rewritten or deleted: B's rows are still there
    assert scalar(db.execute("SELECT count(*) FROM market.odds_quotes q JOIN market.odds_extractions x "
                             "ON x.id = q.extraction_id WHERE x.payload_hash = %s", (b,))) > 0


def test_a_newer_ask_answered_by_b_puts_b_in_force(db: psycopg.Connection, seed: Seed, tmp_path: Path,
                                                   client: TestClient) -> None:
    fixture_id, _a, b = seeded(db, seed, tmp_path)
    ask(db, KO - timedelta(hours=4), b)
    corners = client.get(url(fixture_id, "corners")).json()["data"]
    over = next(s for m in corners["markets"] for s in m["selections"]
                if m["code"] == "corners_over_under" and s["selection"] == "Over")
    assert over["best_odds"] == "2.200" and over["bookmaker"] == "Bet365"


def test_an_empty_newest_answer_leaves_nothing_in_force(db: psycopg.Connection, seed: Seed, tmp_path: Path,
                                                         client: TestClient) -> None:
    fixture_id, _a, _b = seeded(db, seed, tmp_path)
    empty = add_payload(db, seed, PayloadStore(tmp_path), {"get": "odds", "results": 0, "response": []}, fixture=PID,
                        fetched_at=KO - timedelta(hours=3), results=0)
    ask(db, KO - timedelta(hours=3), empty, results=0)
    env = client.get(url(fixture_id, "corners")).json()
    assert env["status"] == "empty" and env["data"]["state"] == "withdrawn"
    assert env["data"]["categories"] == [] and env["data"]["markets"] == []


def test_an_ask_after_kick_off_is_not_pre_match(db: psycopg.Connection, seed: Seed, tmp_path: Path,
                                                client: TestClient) -> None:
    fixture_id, _a, b = seeded(db, seed, tmp_path)
    ask(db, KO + timedelta(minutes=30), b)
    data = client.get(url(fixture_id)).json()["data"]
    assert at(data["checked_at"]) == T3


def test_a_match_never_asked_is_empty_and_an_unknown_one_is_404(db: psycopg.Connection, seed: Seed,
                                                                 client: TestClient) -> None:
    fixture_id = add_fixture(db, seed, PID + 1, KO)
    env = client.get(url(fixture_id)).json()
    assert env["status"] == "empty" and env["data"]["state"] == "never_asked"
    assert client.get(url(10**9)).status_code == 404
    assert client.get(url(fixture_id, "players")).status_code == 422, "a closed list of categories"


def test_signed_out_is_refused(db: psycopg.Connection, seed: Seed) -> None:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    assert TestClient(app, headers=SAME_SITE).get(url(seed.fixture_id)).status_code == 401
