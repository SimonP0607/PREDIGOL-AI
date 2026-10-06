"""End to end over HTTP: one match before kick-off, in play, and finished - with in-play odds that are shown while it
is played and kept nowhere afterwards (revisions 0068/0069), and pre-match odds that are never touched.

    pre-match   Match Center and Odds show the pre-match prices; the live board is empty; no in-play section
    live        the live board shows score, minute, events, statistics and the CURRENT 1X2 / Over-Under prices;
                the Match Center's in-play panel shows the current book and the last move of each price
    finished    the result, events and statistics stay; the in-play book is purged and says so; every pre-match
                snapshot is still there; Picks and Odds answer as before
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config import reset_cache
from fbi.odds.live_repository import STALE_AFTER, LiveOddsRepository
from fbi.providers.api_football.live import LiveFixtureState, LiveOddsQuote
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in

KO = datetime(2030, 3, 9, 15, 0, tzinfo=UTC)
PROVIDER_FIXTURE = 66001


@pytest.fixture(scope="module")
def match(migrated_database: str, seed: Seed) -> Iterator[dict[str, Any]]:
    ids: dict[str, Any] = {"dsn": migrated_database}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                    "competition_type, is_tracked) VALUES (66039, 'Lifecycle League', 'Spain', 'league', 'club', "
                    "'domestic_league', true) RETURNING id")
        ids["competition"] = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2029, true) "
                    "RETURNING id", (ids["competition"],))
        ids["season"] = scalar(cur)
        teams = []
        for pid, name in ((66101, "Life Home"), (66102, "Life Away")):
            cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (pid, name))
            teams.append(scalar(cur))
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                    "kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'NS', 'scheduled') "
                    "RETURNING id", (PROVIDER_FIXTURE, ids["season"], teams[0], teams[1], KO))
        ids["fixture"] = scalar(cur)
        books = []
        for pb, name in ((66901, "Life Book A"), (66902, "Life Book B")):
            cur.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id",
                        (pb, name))
            books.append(scalar(cur))
        cur.execute("INSERT INTO market.markets (key, name, n_outcomes, has_line, is_exclusive, line_is_signed) "
                    "VALUES ('OU', 'Over/Under', 2, true, true, false) ON CONFLICT DO NOTHING RETURNING key")
        ids["added_markets"] = [r[0] for r in cur.fetchall()]
        for h, at in (("life-odds-1", KO - timedelta(hours=24)), ("life-odds-2", KO - timedelta(hours=3))):
            cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, "
                        "file_path, bytes) VALUES (%s, %s, '/odds', %s, 200, 'x', 1)", (h, seed.run_id, at))
            for book, home in ((books[0], Decimal("2.10")), (books[1], Decimal("2.05"))):
                for sel, odds in (("Home", home), ("Draw", Decimal("3.40")), ("Away", Decimal("3.60"))):
                    cur.execute("INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, "
                                "line, odds_decimal, captured_at, minutes_to_ko, source, payload_hash) VALUES "
                                "(%s, %s, '1X2', %s, 0, %s, %s, %s, 'prematch', %s)",
                                (ids["fixture"], book, sel, odds, at, int((KO - at).total_seconds() // 60), h))
        cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, "
                    "bytes) VALUES ('life-fx', %s, '/fixtures', %s, 200, 'x', 1)", (seed.run_id, KO))
        cur.execute("SELECT count(*) FROM market.odds_snapshots WHERE fixture_id = %s", (ids["fixture"],))
        ids["prematch_rows"] = scalar(cur)
    ids["books"] = books
    yield ids
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        f = ids["fixture"]
        cur.execute("DELETE FROM market.live_odds_current")
        cur.execute("DELETE FROM market.live_fixture_current")
        for table in ("core.fixture_live_states", "core.fixture_events", "core.fixture_team_stats",
                      "core.fixture_results", "market.odds_snapshots", "market.market_consensus"):
            cur.execute(f"DELETE FROM {table} WHERE fixture_id = %s", (f,))
        cur.execute("DELETE FROM core.fixtures WHERE id = %s", (f,))
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE hash IN ('life-odds-1', 'life-odds-2', 'life-fx')")
        cur.execute("DELETE FROM market.bookmakers WHERE provider_bookmaker_id IN (66901, 66902)")
        cur.execute("DELETE FROM core.teams WHERE provider_team_id IN (66101, 66102)")
        cur.execute("DELETE FROM core.competition_seasons WHERE id = %s", (ids["season"],))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (ids["competition"],))
        cur.execute("DELETE FROM market.markets WHERE key = ANY(%s)", (ids["added_markets"],))


@pytest.fixture()
def client(match: dict[str, Any]) -> Iterator[TestClient]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", match["dsn"].replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    from fbi.api.app import create_app

    try:
        with TestClient(signed_in(create_app()), headers=SAME_SITE) as c:
            yield c
    finally:
        mp.undo()
        reset_cache()
        set_clock(SystemClock())


def get(client: TestClient, path: str) -> dict[str, Any]:
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:300])
    body: dict[str, Any] = response.json()
    return body


def _live_tick(dsn: str, at: datetime, minute: int, score: tuple[int, int], home: str, over: str) -> None:
    state = LiveFixtureState(provider_fixture_id=PROVIDER_FIXTURE, captured_at=at, payload_hash=f"life-live-{minute}",
                             elapsed_minute=minute, score_home=score[0], score_away=score[1],
                             status_long="First Half" if minute <= 45 else "Second Half", markets_offered=2,
                             values_offered=5)

    def q(bet: int, key: str, sel: str, odds: str, line: str = "0", main: bool | None = None) -> LiveOddsQuote:
        return LiveOddsQuote(provider_fixture_id=PROVIDER_FIXTURE, provider_bet_id=bet, market_key=key, selection=sel,
                             line=Decimal(line), odds_decimal=Decimal(odds), is_suspended=False, is_main_line=main,
                             elapsed_minute=minute, elapsed_seconds=f"{minute}:00", score_home=score[0],
                             score_away=score[1], status_long=state.status_long, is_stopped=False, is_blocked=False,
                             provider_updated_at=at, captured_at=at, payload_hash=state.payload_hash)

    quotes = [q(59, "1X2", "Home", home), q(59, "1X2", "Draw", "3.80"), q(59, "1X2", "Away", "5.50"),
              q(36, "OU", "Over", over, "2.5", True), q(36, "OU", "Under", "1.70", "2.5", True)]
    with psycopg.connect(dsn) as conn:
        LiveOddsRepository(conn).write([state], quotes)
        conn.commit()


def test_one_match_before_during_and_after_kick_off(client: TestClient, match: dict[str, Any]) -> None:
    f, dsn = match["fixture"], match["dsn"]

    # -- pre-match ------------------------------------------------------------------------------------------
    set_clock(FrozenClock(KO - timedelta(hours=2)))
    center = get(client, f"/api/v1/matches/{f}/center")["data"]
    assert center["live_odds"]["status"] != "ok" and center["live_odds"]["reason"]
    odds = get(client, f"/api/v1/odds/fixtures/{f}")["data"]
    assert odds["series"]["status"] == "ok" and odds["series"]["data"], "the pre-match series is shown"
    assert any(row["id"] == f for row in get(client, "/api/v1/odds?limit=200")["data"])
    board = get(client, "/api/v1/live")
    assert board["status"] == "empty" and not board["data"]["matches"]

    # -- live -----------------------------------------------------------------------------------------------
    t1 = KO + timedelta(minutes=20)
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("UPDATE core.fixtures SET status_short = '1H', status_group = 'live' WHERE id = %s", (f,))
        cur.execute("INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, goals_home, "
                    "goals_away, payload_hash) VALUES (%s, %s, '1H', 20, 1, 0, 'life-fx')", (f, t1))
        cur.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, player_name, "
                    "event_type, detail, payload_hash, fetched_at) VALUES (%s, 'api-football', 1, 17, 'home', "
                    "'A. Striker', 'Goal', 'Normal Goal', 'life-fx', %s)", (f, t1))
        for side, shots in (("home", 6), ("away", 2)):
            cur.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, payload_hash, "
                        "fetched_at) VALUES (%s, %s, 'api-football', %s, 'life-fx', %s)", (f, side, shots, t1))
    _live_tick(dsn, t1, 20, (1, 0), "1.55", "1.62")
    _live_tick(dsn, t1 + timedelta(seconds=30), 20, (1, 0), "1.50", "1.62")  # the home price moves
    set_clock(FrozenClock(t1 + timedelta(seconds=40)))

    board = get(client, "/api/v1/live")
    assert board["status"] == "ok"
    live = next(m for m in board["data"]["matches"] if m["fixture_id"] == f)
    assert (live["goals_home"], live["goals_away"], live["elapsed"]) == (1, 0, 20)
    assert live["events"] and live["events"][0]["type"] == "Goal"
    assert {s["side"] for s in live["statistics"]} == {"home", "away"}
    prices = {(q["market_key"], q["selection"]): Decimal(q["odds"]) for q in live["main_odds"]}
    assert prices[("1X2", "Home")] == Decimal("1.50"), "the CURRENT price, not the first one"
    assert prices[("OU", "Over")] == Decimal("1.62")
    assert live["data_status"] == "ok"

    center = get(client, f"/api/v1/matches/{f}/center")["data"]
    assert center["live_odds"]["status"] == "ok"
    assert len(center["live_odds"]["data"]) == 5, "one row per selection being quoted, never a series"
    moves = center["live_movement"]["data"] if center["live_movement"]["status"] == "ok" else []
    assert [(m["selection"], m["kind"], Decimal(m["previous_odds"]), Decimal(m["odds"])) for m in moves] == [
        ("Home", "moved", Decimal("1.55"), Decimal("1.50"))]
    assert {s["source"] for s in center["live_states"]["data"]} == {"fixture_feed", "odds_feed"}
    with psycopg.connect(dsn) as conn:
        assert scalar(conn.execute("SELECT count(*) FROM market.live_odds_current")) == 5

    # -- finished -------------------------------------------------------------------------------------------
    end = KO + timedelta(minutes=115)
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (f,))
        cur.execute("INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, goals_home, "
                    "goals_away, payload_hash) VALUES (%s, %s, 'FT', 90, 2, 1, 'life-fx')", (f, end))
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 2, 1)", (f,))
    with psycopg.connect(dsn) as conn:
        purged = LiveOddsRepository(conn).purge_stale(at=end + STALE_AFTER)
        conn.commit()
        assert (purged.fixtures, purged.quotes) == (1, 5)
        assert scalar(conn.execute("SELECT count(*) FROM market.live_odds_current")) == 0
        assert scalar(conn.execute("SELECT count(*) FROM market.odds_snapshots WHERE fixture_id = %s", (f,))) == (
            match["prematch_rows"]), "every pre-match snapshot is still there"
    set_clock(FrozenClock(end + STALE_AFTER + timedelta(minutes=1)))

    center = get(client, f"/api/v1/matches/{f}/center")["data"]
    assert center["status_group"] == "finished"
    assert center["live_odds"]["status"] != "ok" and "not kept" in center["live_odds"]["reason"]
    assert center["events"]["status"] == "ok" and center["statistics"]["status"] == "ok"
    assert [s["source"] for s in center["live_states"]["data"]] == ["fixture_feed", "fixture_feed"]
    view = get(client, f"/api/v1/matches/{f}")["data"]
    assert (view["match"]["score"]["home"], view["match"]["score"]["away"]) == (2, 1)
    odds = get(client, f"/api/v1/odds/fixtures/{f}")["data"]
    assert odds["series"]["status"] == "ok" and odds["series"]["data"]
    assert get(client, "/api/v1/live")["status"] == "empty"
    picks = client.get("/api/v1/picks")
    assert picks.status_code == 200 and picks.json()["status"] in ("ok", "empty")
