"""A match's bets settle the minute it ends, the wait is recorded, a pre-match record cannot be rewritten, a pick
stays on the board as it was taken once its match starts, and its line value is measured (9 Oct 2026).

Built on the world of test_daily_records (AT 2032-08-01 12:00 UTC; F1 kicks off at AT+2h, qualified, 2.30)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.api.services.product import picks_board
from fbi.api.services.records import daily_board
from fbi.picks.daily import build_daily_sets
from fbi.picks.engine import settle_open_picks
from fbi.picks.fast_settlement import fill_line_value, settle_fixtures
from fbi.picks.product_settlement import settle_products

from .conftest import Seed
from .test_daily_records import AT, World

KO = AT + timedelta(hours=2)


def _state(db: psycopg.Connection[Any], fixture: int, at: Any, code: str, minute: int | None, home: int,
           away: int) -> None:
    db.execute("INSERT INTO core.fixture_live_states (fixture_id, observed_at, status_short, elapsed, goals_home, "
               "goals_away, payload_hash) VALUES (%s, %s, %s, %s, %s, %s, 'h1')",
               (fixture, at, code, minute, home, away))


def test_a_match_that_ends_is_settled_at_once_and_its_wait_recorded(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    f1 = w.fixtures["F1"]
    _state(db, f1, KO + timedelta(minutes=100), "2H", 90, 1, 0)
    _state(db, f1, KO + timedelta(minutes=110), "FT", 90, 1, 0)
    w.result("F1", 1, 0)

    report = settle_fixtures(db, [f1, f1], path="live_follow", at=KO + timedelta(hours=2))
    assert (report.fixtures, report.picks, report.deferred) == (1, 1, [])
    assert report.items == 2, "the qualified set's item and the evaluation set's item"
    assert db.execute("SELECT result_status, profit_units FROM picks.pick_results WHERE pick_id = %s",
                      (w.picks["F1"],)).fetchone() == ("win", Decimal("1.3000"))
    row = db.execute("SELECT path, last_in_play_at, observed_finished_at, delay_seconds, picks_settled, "
                     "items_settled FROM picks.settlement_latency WHERE fixture_id = %s", (f1,)).fetchone()
    assert row is not None
    assert row[0] == "live_follow"
    assert row[1] == KO + timedelta(minutes=100) and row[2] == KO + timedelta(minutes=110)
    assert row[3] is not None and row[3] >= 0
    assert (row[4], row[5]) == (1, 2)

    # The pipeline's pass afterwards finds nothing left on that match, and settles nothing twice.
    again = settle_open_picks(db, run_id=None, fixture_ids=[f1])
    assert (again.open_picks, again.settled) == (0, 0)
    assert settle_products(db, at=KO + timedelta(hours=3), fixture_ids=[f1]).by_fixture == {}
    # Another match is untouched.
    assert db.execute("SELECT status FROM picks.picks WHERE id = %s", (w.picks["F3"],)).fetchone() == ("qualified",)


def test_a_match_not_over_settles_nothing_and_records_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    f1 = w.fixtures["F1"]
    db.execute("UPDATE core.fixtures SET status_short = '2H', status_group = 'live' WHERE id = %s", (f1,))
    report = settle_fixtures(db, [f1], path="live_follow", at=KO + timedelta(minutes=50))
    assert (report.fixtures, report.picks, report.items) == (0, 0, 0)
    assert db.execute("SELECT count(*) FROM picks.settlement_latency WHERE fixture_id = %s", (f1,)).fetchone() == (0,)


def test_a_prematch_record_cannot_be_rewritten(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    attempts = [
        ("UPDATE picks.picks SET market_odds = 9.99 WHERE id = %s", w.picks["F1"]),
        ("UPDATE picks.picks SET odds_captured_at = odds_captured_at - interval '1 hour' WHERE id = %s",
         w.picks["F1"]),
        ("UPDATE picks.picks SET created_at = created_at - interval '1 minute' WHERE id = %s", w.picks["F1"]),
        ("UPDATE picks.pick_candidates SET market_odds = 9.99 WHERE fixture_id = %s", w.fixtures["F1"]),
        ("UPDATE picks.daily_set_items SET odds = 9.99 WHERE fixture_id = %s", w.fixtures["F1"]),
        ("UPDATE picks.daily_set_items SET rank = 5 WHERE fixture_id = %s", w.fixtures["F1"]),
    ]
    for sql, key in attempts:
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation), db.transaction():
            db.execute(sql, (key,))
    # What may change still does: a pick's status, an item's result.
    db.execute("UPDATE picks.picks SET status = 'shadow', status_changed_at = now() WHERE id = %s", (w.picks["F1"],))
    w.result("F1", 0, 2)
    assert settle_products(db, at=KO + timedelta(hours=3)).items == 2


def test_a_started_match_keeps_its_prematch_pick_as_taken(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    f1 = w.fixtures["F1"]
    moment = KO + timedelta(minutes=60)
    db.execute("UPDATE core.fixtures SET status_short = '2H', status_group = 'live' WHERE id = %s", (f1,))
    _state(db, f1, moment - timedelta(minutes=1), "2H", 55, 1, 0)
    w.price("F1", "1.40", moment - timedelta(minutes=2))  # an in-play consensus must not re-price the pick

    board = picks_board(db, include_shadow=False, competition_id=None, market=None, min_odds=None,
                        max_odds=None, hours=72, at=moment).data
    assert board is not None
    assert w.picks["F1"] not in [p.pick_id for p in board.picks], "re-priced picks are the matches still to come"
    started = {s.pick_id: s for s in board.started}
    assert set(started) == {w.picks["F1"]}, "F4-F6 are shadow and have not started; F2/F3 have not started"
    s = started[w.picks["F1"]]
    assert (s.phase, s.status, s.odds_taken, s.live_minute, s.live_home, s.live_away) == (
        "live", "qualified", Decimal("2.300"), 55, 1, 0)
    assert s.taken_at < s.kickoff_at and s.created_at < s.kickoff_at
    assert s.result_status is None and s.evaluations == 1

    # The day's card says the match is live, with its minute - not just "Pendiente".
    day = daily_board(db, day=None, include_shadow=False, at=moment).data
    assert day is not None and day.set is not None
    item = next(i for i in day.set.items if i.match.fixture_id == f1)
    assert (item.match.phase, item.match.live_minute, item.status) == ("live", 55, "PENDING")

    # After the final whistle and the fast settlement: the result beside the same record.
    _state(db, f1, KO + timedelta(minutes=112), "FT", 90, 2, 0)
    w.result("F1", 2, 0)
    settle_fixtures(db, [f1], path="live_follow", at=KO + timedelta(hours=2))
    later = picks_board(db, include_shadow=False, competition_id=None, market=None, min_odds=None,
                        max_odds=None, hours=72, at=KO + timedelta(hours=3)).data
    assert later is not None
    done = next(x for x in later.started if x.pick_id == w.picks["F1"])
    assert (done.phase, done.result_status, done.profit_units, done.odds_taken, done.status) == (
        "finished", "win", Decimal("1.3000"), Decimal("2.300"), "qualified")
    assert (done.score_home, done.score_away, done.live_minute) == (2, 0, None)

    # A match's own page finds it whenever it is asked.
    week = picks_board(db, include_shadow=False, competition_id=None, market=None, min_odds=None, max_odds=None,
                       hours=72, at=KO + timedelta(days=6), fixture_id=f1).data
    assert week is not None and [x.pick_id for x in week.started] == [w.picks["F1"]]


def test_line_value_against_the_same_bookmakers_last_prematch_price(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    f1 = w.fixtures["F1"]
    db.execute("INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, "
               "odds_decimal, captured_at, minutes_to_ko, source, payload_hash) VALUES "
               "(%s, %s, '1X2', 'Home', 0, 2.10, %s, 10, 'prematch', 'h1')",
               (f1, seed.bookmaker_id, KO - timedelta(minutes=10)))
    db.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, "
               "p_fair, n_bookmakers, overround, best_odds, best_bookmaker_id) VALUES "
               "(%s, '1X2', 'Home', 0, %s, 'shin', 0.46, 5, 0.05, 2.15, %s)",
               (f1, KO - timedelta(minutes=10), seed.bookmaker_id))
    assert fill_line_value(db, at=KO + timedelta(hours=1)) == 0, "waits for the provider's final pre-match price"
    assert fill_line_value(db, at=KO + timedelta(hours=7)) >= 1
    row = db.execute("SELECT near_close_odds, near_close_minutes_to_ko, lv_raw, lv_devigged, is_validated_close "
                     "FROM picks.pick_line_value WHERE pick_id = %s", (w.picks["F1"],)).fetchone()
    assert row == (Decimal("2.100"), 10, Decimal("0.095238"), Decimal("0.058000"), False)
    assert fill_line_value(db, at=KO + timedelta(hours=8)) == 0, "written once"
