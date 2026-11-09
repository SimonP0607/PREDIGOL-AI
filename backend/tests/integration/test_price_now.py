"""The price of a pick now beside the price it was taken at (plan CUOTAS, phase 6).

On the world of ``test_daily_records`` (AT = 2032-08-01 12:00 UTC; F1 2 h later at 2.30, captured 30 minutes before AT). A pick of
the day and a pick a reader saved show the newest price with its hour and freshness while the match is still to be played, and
nothing once it has started: the record as it was taken is never re-priced. Every test runs in a transaction that is rolled back.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg

from fbi.api.cache import clear
from fbi.api.services.price_now import change, freshness, has_price_now
from fbi.api.services.product import PRICE_FRESH
from fbi.api.services.records import daily_board, user_picks
from fbi.picks.daily import build_daily_sets, product_day
from fbi.userdata import records as userdata

from .conftest import Seed
from .test_daily_records import AT, World


def _item(db: psycopg.Connection[Any], w: World, name: str, *, at: Any) -> Any:
    clear()
    board = daily_board(db, day=product_day(AT), include_shadow=True, at=at).data
    assert board is not None and board.set is not None
    return next(i for i in board.set.items if i.match.fixture_id == w.fixtures[name])


def test_a_pick_of_the_day_shows_the_price_now_with_its_hour(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    w.price("F1", "2.07", AT + timedelta(minutes=20))
    item = _item(db, w, "F1", at=AT + timedelta(minutes=30))
    assert item.odds == Decimal("2.300"), "the frozen price is not touched"
    assert item.price_now is not None
    assert item.price_now.odds == Decimal("2.070")
    assert item.price_now.as_of == AT + timedelta(minutes=20)
    assert item.price_now.freshness == "fresh"
    assert item.price_now.change == Decimal("-0.1000"), "2.07 / 2.30 - 1"
    assert "bookmaker" not in item.price_now.model_dump(), "a price now is a reference, not an offer"


def test_an_old_price_now_says_it_is_old(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    item = _item(db, w, "F3", at=AT + timedelta(hours=3))  # F3 kicks off 6 h after AT
    assert item.price_now is not None and item.price_now.as_of == AT - timedelta(minutes=30)
    assert item.price_now.freshness == "stale", "captured three and a half hours earlier"


def test_a_started_match_has_no_price_now(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    item = _item(db, w, "F1", at=AT + timedelta(hours=3))
    assert item.price_now is None


def test_a_saved_pick_compares_the_price_the_reader_counts(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    row = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                     "('price-now@test.local', 'Price now', '$argon2id$x') RETURNING id").fetchone()
    assert row is not None
    uid = int(row[0])
    userdata.save_pick(db, user_id=uid, fixture_id=w.fixtures["F4"], market_key="1X2", selection="Home",
                       line=Decimal(0), at=AT, user_odds=Decimal("2.50"))
    userdata.save_pick(db, user_id=uid, fixture_id=w.fixtures["F5"], market_key="1X2", selection="Home",
                       line=Decimal(0), at=AT)
    w.price("F4", "2.00", AT + timedelta(minutes=10))
    picks = user_picks(db, user_id=uid, status=None, limit=10, at=AT + timedelta(minutes=15)).data
    assert picks is not None
    by_fixture = {p.match.fixture_id: p for p in picks}
    own = by_fixture[w.fixtures["F4"]]
    assert own.price_now is not None and own.price_now.odds == Decimal("2.000")
    assert own.price_now.change == Decimal("-0.2000"), "against the reader's own 2.50, not the 2.30 we showed"
    shown = by_fixture[w.fixtures["F5"]]
    assert shown.price_now is not None and shown.price_now.change == Decimal("0.0000"), "2.30 then, 2.30 now"


def test_the_rules_of_the_price_now() -> None:
    assert freshness(AT - PRICE_FRESH, AT) == "fresh", "the picks board's own limit (one hour)"
    assert freshness(AT - PRICE_FRESH - timedelta(seconds=1), AT) == "aging"
    assert freshness(AT - timedelta(hours=3, seconds=1), AT) == "stale"
    assert change(Decimal("2.30"), Decimal("2.30")) == Decimal("0.0000")
    assert has_price_now("NS", AT + timedelta(hours=1), AT)
    assert not has_price_now("NS", AT - timedelta(minutes=1), AT), "kick-off passed"
    assert not has_price_now("FT", AT + timedelta(hours=1), AT), "finished"
