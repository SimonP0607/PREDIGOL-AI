"""A user's parlay keeps the exact odds of each leg and when they were captured (plan CUOTAS, phase 6).

The odds the user was shown are kept with the time the user's screen gives; without odds the newest consensus price is
taken and its own time is kept. Settlement still reads only the stored odds. Every test runs in a transaction that is rolled
back."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg

from fbi.api.services.records import user_parlays
from fbi.userdata import records as userdata

from .conftest import Seed
from .test_daily_records import AT, World


def _user(db: psycopg.Connection[Any]) -> int:
    row = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                     "('odds-kept@test.local', 'Odds kept', '$argon2id$x') RETURNING id").fetchone()
    assert row is not None
    return int(row[0])


def _legs(db: psycopg.Connection[Any], uid: int) -> list[Any]:
    answer = user_parlays(db, user_id=uid, limit=10)
    assert answer.data is not None
    return list(answer.data[0].legs)


def test_without_odds_the_newest_price_and_its_own_time_are_kept(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    uid = _user(db)
    userdata.create_parlay(db, user_id=uid, name=None, at=AT, legs=[
        userdata.LegIn(w.fixtures["F4"], "1X2", "Home", Decimal(0)),
        userdata.LegIn(w.fixtures["F5"], "1X2", "Home", Decimal(0))])
    for leg in _legs(db, uid):
        assert leg.odds_source == "current"
        assert leg.odds == Decimal("2.300")
        assert leg.odds_captured_at == AT - timedelta(minutes=30), "the price's own time, not the time of saving"


def test_the_odds_shown_are_kept_with_the_time_given(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    uid = _user(db)
    shown_at = AT - timedelta(minutes=10)
    saved = userdata.create_parlay(db, user_id=uid, name=None, at=AT, legs=[
        userdata.LegIn(w.fixtures["F4"], "1X2", "Home", Decimal(0), Decimal("2.40"), shown_at),
        userdata.LegIn(w.fixtures["F5"], "1X2", "Home", Decimal(0))])
    assert saved["combined_odds"] == Decimal("5.520"), "2.40 as shown x 2.30 current"
    first, second = _legs(db, uid)
    assert (first.odds, first.odds_source, first.odds_captured_at) == (Decimal("2.400"), "shown", shown_at)
    assert (second.odds, second.odds_source) == (Decimal("2.300"), "current")
    snapshot = db.execute("SELECT snapshot FROM picks.user_parlay_legs WHERE leg_no = 1 AND user_parlay_id = %s",
                          (saved["id"],)).fetchone()
    assert snapshot is not None and snapshot[0]["price"]["odds"] == "2.300", "the price now stays beside the one shown"


def test_odds_shown_without_a_time_keep_no_invented_time(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    uid = _user(db)
    userdata.create_parlay(db, user_id=uid, name=None, at=AT, legs=[
        userdata.LegIn(w.fixtures["F4"], "1X2", "Home", Decimal(0), Decimal("2.40")),
        userdata.LegIn(w.fixtures["F5"], "1X2", "Home", Decimal(0))])
    first = _legs(db, uid)[0]
    assert (first.odds_source, first.odds_captured_at) == ("shown", None)


def test_a_capture_time_in_the_future_is_refused(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    checked = userdata.validate_parlay(db, [
        userdata.LegIn(w.fixtures["F4"], "1X2", "Home", Decimal(0), Decimal("2.40"), AT + timedelta(minutes=5)),
        userdata.LegIn(w.fixtures["F5"], "1X2", "Home", Decimal(0))], at=AT)
    assert not checked.ok and [e["code"] for e in checked.errors] == ["odds_time_in_future"]
    assert checked.errors[0]["leg"] == 1
