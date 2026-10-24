"""The scoreboard of the stored family forecasts in a real database (plan F11): the rows the writer stored, graded on what the match turned out to be.

The pure parts are in tests/unit/test_families_score.py. Here: a match is forecast before it kicks off, it is played, and the scoreboard reads
the last forecast stored before the kick-off, the counts through the door the families read outcomes through, and grades the one against the other."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.families import forecast, score
from fbi.odds.quote_taxonomy import sync_definitions
from tests.integration.conftest import Seed

from .knowledge_world import World
from .test_families_forecast import AT, catalogue, played, run, upcoming

pytestmark = pytest.mark.integration

KICKOFF = AT + timedelta(days=1)
NOW = AT + timedelta(days=4)


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


def play(w: World, fixture_id: int, *, goals: tuple[int, int] = (3, 1), ht: tuple[int, int] = (2, 0), corners: tuple[int, int] = (7, 4),
         yellows: tuple[int, int] = (2, 3), reds: tuple[int, int] = (0, 1)) -> None:
    """The match is over: its result, its half-time score and the statistics of the two sides."""
    w.db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fixture_id,))
    w.result(fixture_id, goals, ht=ht, settled=KICKOFF + timedelta(hours=3), kickoff=KICKOFF)
    for side, c, y, r in (("home", corners[0], yellows[0], reds[0]), ("away", corners[1], yellows[1], reds[1])):
        w.team_stats(fixture_id, side, corners=c, yellow_cards=y, red_cards=r)


def market(report: dict[str, Any], model: str, key: str, line: float, selection: str) -> dict[str, Any]:
    return next(x for x in report["models"][model]["markets"] if (x["key"], x["line"], x["selection"]) == (key, line, selection))


def test_the_forecasts_of_a_match_that_was_played_are_graded_on_what_happened(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    play(w, fid)
    report = score.score(db, now=NOW, days=14, wait_hours=30)
    assert set(report["models"]) == {"family-goals_halves", "family-corners_ft", "family-cards_lines_ft", "family-yellow_ft"}
    assert all(m["fixtures"] == 1 and m["rows"] > 0 for m in report["models"].values())
    assert report["left_out"] == {"pushed": 0, "ungradable": 0}
    corners = "family-corners_ft"  # 11 corners: 7 for the home side, 4 for the away side
    assert market(report, corners, "CORNERS_OU", 10.5, "Over")["observed"] == 1.0
    assert market(report, corners, "CORNERS_OU", 11.5, "Over")["observed"] == 0.0
    assert market(report, corners, "CORNERS_OU_HOME", 6.5, "Over")["observed"] == 1.0
    assert market(report, corners, "CORNERS_1X2", 0, "Home")["observed"] == 1.0
    halves = "family-goals_halves"  # 2-0 at the break, 3-1 at the end: 2 goals in each half
    assert market(report, halves, "HTFT", 0, "Home/Home")["observed"] == 1.0
    assert market(report, halves, "HTFT", 0, "Draw/Draw")["observed"] == 0.0
    assert market(report, halves, "HSH", 0, "Draw")["observed"] == 1.0
    assert market(report, halves, "1X2_1H", 0, "Home")["observed"] == 1.0
    assert market(report, "family-cards_lines_ft", "CARDS_OU", 5.5, "Over")["observed"] == 1.0, "2 + 3 yellows and one red are 6 cards"
    assert market(report, "family-yellow_ft", "YELLOW_OU", 4.5, "Over")["observed"] == 1.0, "and 5 of them yellow"


def test_the_probability_graded_is_the_one_stored_the_last_before_the_kick_off(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    before = db.execute("SELECT p FROM models.match_forecasts WHERE fixture_id = %s AND market_key = 'CORNERS_OU' AND selection = 'Over' AND line = 10.5 "
                        "AND model_name = 'family-corners_ft'", (fid,)).fetchall()
    assert len(before) == 1
    # a row stored AFTER the kick-off (a re-run that should not exist) must never be what the match is graded with
    db.execute("INSERT INTO models.match_forecasts (version, known_at, fixture_id, family, market_key, selection, line, model_name, model_version_id, "
               "data_cutoff_ts, p_model, p, p_push, calibration, basis, input_hash, code_version) "
               "SELECT version, %s, fixture_id, family, market_key, selection, line, model_name, model_version_id, data_cutoff_ts, 0.999, 0.999, p_push, "
               "calibration, basis, input_hash, code_version FROM models.match_forecasts "
               "WHERE fixture_id = %s AND market_key = 'CORNERS_OU' AND selection = 'Over' AND line = 10.5 AND model_name = 'family-corners_ft'",
               (KICKOFF + timedelta(minutes=5), fid))
    play(w, fid)
    report = score.score(db, now=NOW, days=14, wait_hours=30)
    assert market(report, "family-corners_ft", "CORNERS_OU", 10.5, "Over")["mean_p"] == pytest.approx(float(before[0][0]))


def test_a_match_with_no_forecast_or_too_recent_or_without_its_statistics_is_not_graded(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    play(w, fid)
    assert score.score(db, now=KICKOFF + timedelta(hours=20), days=14, wait_hours=30)["models"] == {}, "the statistics have not settled yet"
    assert score.score(db, now=NOW, days=2, wait_hours=30)["models"] == {}, "the match kicked off more than two days before"
    assert score.score(db, now=NOW, days=14, wait_hours=30, model="family-yellow_ft")["models"].keys() == {"family-yellow_ft"}
    other = upcoming(w, 2, 3)  # forecast, but its statistics never arrive
    run(db, [other])
    w.db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (other,))
    w.result(other, (1, 0), ht=(0, 0), settled=KICKOFF + timedelta(hours=3), kickoff=KICKOFF)
    report = score.score(db, now=NOW, days=14, wait_hours=30)
    assert report["models"]["family-goals_halves"]["fixtures"] == 2, "the goals of both matches are known"
    assert report["models"]["family-corners_ft"]["fixtures"] == 1, "the corners of the second are not"
    assert report["left_out"]["ungradable"] > 0 and report["left_out"]["pushed"] == 0


def test_the_report_is_text_and_json_ready(db: psycopg.Connection[Any], w: World) -> None:
    import json

    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    play(w, fid)
    report = score.score(db, now=NOW, days=14, wait_hours=30)
    json.dumps(report, default=str)
    text = score.render(report, min_rows=1)
    assert "family-corners_ft: 1 matches" in text and "log loss" in text and "calibration gap" in text


def price(db: psycopg.Connection[Any], extraction: int, fixture_id: int, book: int, over: str, under: str, line: str, when: datetime) -> None:
    """One book's over/under of the corners of the match (provider bet 45) at an instant."""
    definition = db.execute("SELECT id FROM market.market_definitions WHERE provider_bet_id = 45 AND scope = 'prematch'").fetchall()[0][0]
    for selection, odds in (("Over", over), ("Under", under)):
        db.execute("INSERT INTO market.odds_quotes (fixture_id, bookmaker_id, definition_id, selection, line, odds_decimal, captured_at, minutes_to_ko, "
                   "extraction_id) VALUES (%s, %s, %s, %s, %s, %s, %s, 60, %s)", (fixture_id, book, definition, selection, line, odds, when, extraction))


def test_the_forecasts_are_set_against_the_books_at_the_last_price_and_a_day_before(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])
    play(w, fid)  # 11 corners: the over of 10.5 won
    sync_definitions(db, names={})
    db.execute("UPDATE market.market_definitions SET market_key = 'CORNERS_OU' WHERE provider_bet_id = 45 AND scope = 'prematch'")
    extraction = db.execute("INSERT INTO market.odds_extractions (payload_hash, extractor_version, provider_fixture_id, fetched_at, stamped_by, status) "
                            "VALUES (%s, 'qx-test', 1, %s, 'fetch', 'ok') RETURNING id", (w.hash, KICKOFF - timedelta(days=2))).fetchall()[0][0]
    books = w.books(3)
    for book in books:  # even prices two days before; an hour before, the over has shortened
        price(db, extraction, fid, book, "1.90", "1.90", "10.5", KICKOFF - timedelta(days=2))
        price(db, extraction, fid, book, "1.70", "2.20", "10.5", KICKOFF - timedelta(hours=1))
    price(db, extraction, fid, books[0], "3.00", "1.40", "10.5", KICKOFF + timedelta(hours=1))  # after the kick-off: never read
    for book in books[:2]:  # two books only on this line: not a consensus
        price(db, extraction, fid, book, "2.40", "1.55", "11.5", KICKOFF - timedelta(days=2))
    stored = {(sel): float(p) for sel, p in db.execute(
        "SELECT selection, p FROM models.match_forecasts WHERE fixture_id = %s AND market_key = 'CORNERS_OU' AND line = 10.5 AND model_name = "
        "'family-corners_ft'", (fid,)).fetchall()}

    report = score.score(db, now=NOW, days=14, wait_hours=30)
    entry = report["versus"]["models"]["family-corners_ft"]
    close, h24 = entry["close"], entry["h24"]
    assert (close["n"], close["fixtures"], close["mean_books"]) == (2, 1, 3) and (h24["n"], h24["fixtures"]) == (2, 1)
    assert close["log_loss_market"] == pytest.approx(-math.log(2.2 / 3.9)), "an hour before: the over at 2.2 / (1.7 + 2.2) of every book"
    assert h24["log_loss_market"] == pytest.approx(math.log(2)), "two days before: even prices"
    model_loss = (-math.log(stored["Over"]) - math.log(1 - stored["Under"])) / 2  # the over won, the under lost
    assert close["log_loss_model"] == pytest.approx(model_loss) == pytest.approx(h24["log_loss_model"])
    assert close["market_minus_model"] == pytest.approx(close["log_loss_market"] - model_loss)
    assert [(x["ref"], x["key"]) for x in entry["by_key"]] == [("close", "CORNERS_OU"), ("h24", "CORNERS_OU")]
    assert set(report["versus"]["models"]) == {"family-corners_ft"}, "the other families have no price in this world"
    text = score.render(report, min_rows=1)
    assert "against the market" in text and "family-corners_ft close" in text and "market minus model" in text
    assert "versus" not in score.score(db, now=NOW, days=14, wait_hours=30, market=False)
    assert score.score(db, now=NOW, days=14, wait_hours=30, min_books=4)["versus"]["models"] == {}, "four books are asked for and three quoted"


def test_the_bets_use_the_forecast_of_a_day_before_and_the_prices_of_that_day(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    fid = upcoming(w)
    run(db, [fid])  # stored at AT, exactly a day before the kick-off
    play(w, fid)  # 11 corners: the over of 10.5 won
    where = "fixture_id = %s AND market_key = 'CORNERS_OU' AND selection = 'Over' AND line = 10.5 AND model_name = 'family-corners_ft'"
    early = float(db.execute(f"SELECT p FROM models.match_forecasts WHERE {where}", (fid,)).fetchall()[0][0])
    # a later forecast (6 h before) that says the opposite: the scoreboard grades with it, a bet taken a day before could not have known it
    db.execute("INSERT INTO models.match_forecasts (version, known_at, fixture_id, family, market_key, selection, line, model_name, model_version_id, "
               "data_cutoff_ts, p_model, p, p_push, calibration, basis, input_hash, code_version) "
               "SELECT version, %s, fixture_id, family, market_key, selection, line, model_name, model_version_id, data_cutoff_ts, 0.001, 0.001, p_push, "
               f"calibration, basis, input_hash, code_version FROM models.match_forecasts WHERE {where}", (KICKOFF - timedelta(hours=6), fid))
    since, until = NOW - timedelta(days=14), NOW - timedelta(hours=30)
    lead = timedelta(hours=24)
    over_105 = (fid, "CORNERS_OU", Decimal("10.5"), "Over")
    pick = [r for r in score.load_forecasts(db, since=since, until=until, lead=lead) if (r.fixture_id, r.key, r.line, r.selection) == over_105]
    last = [r for r in score.load_forecasts(db, since=since, until=until) if (r.fixture_id, r.key, r.line, r.selection) == over_105]
    assert [round(r.p, 6) for r in pick] == [round(early, 6)] and pick[0].known_at == AT, "a day before: the forecast of a day before"
    assert [r.p for r in last] == [0.001], "the scoreboard's: the last one before the kick-off"
    assert not [r for r in score.load_forecasts(db, since=since, until=until, lead=timedelta(hours=25)) if r.fixture_id == fid], "none from 25 h before"

    sync_definitions(db, names={})
    db.execute("UPDATE market.market_definitions SET market_key = 'CORNERS_OU' WHERE provider_bet_id = 45 AND scope = 'prematch'")
    extraction = db.execute("INSERT INTO market.odds_extractions (payload_hash, extractor_version, provider_fixture_id, fetched_at, stamped_by, status) "
                            "VALUES (%s, 'qx-test', 1, %s, 'fetch', 'ok') RETURNING id", (w.hash, KICKOFF - timedelta(days=2))).fetchall()[0][0]
    # three books a day before pay the over 10 % over the model's probability (a margin of 6 % behind the under); an hour before it has shortened
    over = round(1.10 / early, 2)
    under = round(1 / (1.06 - 1 / over), 2)
    for book in w.books(3):
        price(db, extraction, fid, book, str(over), str(under), "10.5", KICKOFF - timedelta(days=2))
        price(db, extraction, fid, book, "1.70", "2.20", "10.5", KICKOFF - timedelta(hours=1))
    report = score.score(db, now=NOW, days=14, wait_hours=30)
    entry = report["bets"]["models"]["family-corners_ft"]
    assert (entry["taken"], entry["n"], entry["fixtures"], entry["no_closing_line"], entry["verdict"]) == (1, 1, 1, 0, "TOO_FEW")
    assert entry["believed"] == pytest.approx(over * early - 1) and entry["believed"] >= 0.03, "the value the forecast of a day before saw"
    assert entry["at_pick"] == pytest.approx(over * under / (over + under) - 1), "the same price at the books' probability that day: the over"
    assert entry["clv"] == pytest.approx(over * 2.20 / 3.90 - 1), "and at the last price before the kick-off"
    assert entry["return"] == pytest.approx(over - 1) and entry["hit_rate"] == 1.0 and entry["mean_odds"] == pytest.approx(over)
    assert report["bets"]["criterion"]["min_bets"] == 300 and entry["needed"] == 299
    assert set(report["bets"]["models"]) == {"family-goals_halves", "family-corners_ft", "family-cards_lines_ft", "family-yellow_ft"}
    assert all(m["taken"] == 0 for name, m in report["bets"]["models"].items() if name != "family-corners_ft"), "no other family has a price"
    text = score.render(report, min_rows=1)
    assert "the plan's criterion for a family to decide in shadow" in text and "family-corners_ft: 1 bets in 1 matches (299 short of 300)" in text

    assert score.score(db, now=NOW, days=14, wait_hours=30, min_ev=0.5)["bets"]["models"]["family-corners_ft"]["taken"] == 0, "a floor of 50 %: no bet"
    assert score.score(db, now=NOW, days=14, wait_hours=30, min_books=4)["bets"]["models"]["family-corners_ft"]["taken"] == 0
    assert "bets" not in score.score(db, now=NOW, days=14, wait_hours=30, market=False)
