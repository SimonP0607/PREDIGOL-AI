"""The consensus of the real close in a real database (RP-1.4, migration 0179): built from the last prices stamped in the last hour, never from a
match with fewer than three books, written once, and the value of a settled decision against it stored beside the one it always had - which is not
touched. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.market import closing_consensus as cc

from .conftest import Seed
from .helpers import scalar
from .test_daily_records import AT
from .test_postmortem_v6 import Pm

pytestmark = pytest.mark.integration

NOW = AT + timedelta(days=2)
PRICES = (("2.10", "3.40", "3.60"), ("2.05", "3.50", "3.70"), ("2.15", "3.30", "3.50"))


def world(db: psycopg.Connection[Any], seed: Seed) -> tuple[Pm, list[int]]:
    pm = Pm(db, seed, investigation=False, scenarios=False)
    books = [pm.book, pm.other]
    for n in (21, 22):
        pm.cur.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id", (n, f"Book {n}"))
        books.append(int(scalar(pm.cur)))
    return pm, books


def close(pm: Pm, name: str, book: int, prices: tuple[str, str, str], minutes: int) -> None:
    for sel, odds in zip(("Home", "Draw", "Away"), prices, strict=True):
        pm.book_close(name, book, "1X2", sel, "0", odds, minutes)


def test_the_last_hour_of_prices_makes_the_consensus_and_older_prices_do_not(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm, books = world(db, seed)
    for b, prices, minutes in zip(books[:3], PRICES, (10, 25, 55), strict=True):
        close(pm, "F3", b, prices, minutes)
    close(pm, "F3", books[3], ("1.50", "5.00", "9.00"), 90)  # a book whose last price is older than the hour: out
    made = cc.run(db, at=NOW, days=5)
    assert made["rows"] > 0
    row = db.execute("SELECT p_fair, n_bookmakers, minutes_to_ko, newest_minutes_to_ko FROM market.near_close_consensus WHERE fixture_id = %s "
                     "AND selection = 'Home' AND devig_method = 'shin'", (pm.f["F3"],)).fetchone()
    assert row is not None
    assert (row[1], row[2], row[3]) == (3, 25, 10), "three books, the median of 10/25/55 and the nearest"
    assert Decimal("0.40") < row[0] < Decimal("0.52")
    assert cc.run(db, at=NOW, days=5) == {"matches": 0, "rows": 0}, "the second pass finds nothing to do: written once"


def test_a_match_with_two_books_has_no_consensus_and_does_not_hold_back_the_next(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm, books = world(db, seed)
    for b, prices in zip(books[:2], PRICES, strict=False):
        close(pm, "F1", b, prices, 15)
    for b, prices in zip(books[:3], PRICES, strict=True):
        close(pm, "F2", b, prices, 15)
    cc.run(db, at=NOW, days=5)
    got = {int(r[0]) for r in db.execute("SELECT DISTINCT fixture_id FROM market.near_close_consensus").fetchall()}
    assert got == {pm.f["F2"]}


def test_a_settled_decision_is_valued_against_the_real_close_beside_its_old_value(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm, books = world(db, seed)
    for b, prices in zip(books[:3], PRICES, strict=True):
        close(pm, "F3", b, prices, 20)
    decision = pm.decide("F3", "1X2", "Home", "0", odds="2.30")
    other = pm.decide("F1", "1X2", "Home", "0", odds="2.30")  # no prices read for F1: no real close, never an invention
    pm.settle(decision, "win", "0.050000", "F3")
    pm.settle(other, "loss", "-0.020000", "F1")
    assert cc.step(db, at=NOW)["decisions"] == 1
    row = db.execute("SELECT real_p_fair, real_minutes_to_ko, n_bookmakers, clv_real, reference FROM intel.decision_real_close "
                     "WHERE decision_id = %s", (decision,)).fetchone()
    assert row is not None
    p = row[0]
    assert row[1:3] == (20, 3) and row[4] == cc.REFERENCE
    assert row[3] == (Decimal("2.30") * p - 1).quantize(Decimal("0.000001")), "clv-v1: odds x the closing fair probability - 1"
    assert db.execute("SELECT count(*) FROM intel.decision_real_close WHERE decision_id = %s", (other,)).fetchone() == (0,)
    assert db.execute("SELECT clv FROM intel.decision_outcomes WHERE decision_id = %s", (decision,)).fetchone() == (Decimal("0.050000"),), \
        "the value against the reference that was always used is not rewritten"
    assert cc.settle(db, at=NOW) == 0, "a second pass writes nothing"


def test_the_value_against_the_real_close_is_append_only(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm, books = world(db, seed)
    for b, prices in zip(books[:3], PRICES, strict=True):
        close(pm, "F3", b, prices, 20)
    decision = pm.decide("F3", "1X2", "Home", "0", odds="2.30")
    pm.settle(decision, "win", "0.05", "F3")
    cc.step(db, at=NOW)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE intel.decision_real_close SET clv_real = 0 WHERE decision_id = %s", (decision,))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("DELETE FROM intel.decision_real_close WHERE decision_id = %s", (decision,))


def test_the_measure_compares_the_two_references_and_the_acceptance(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm, books = world(db, seed)
    for name, minutes in (("F1", 10), ("F2", 20), ("F3", 28), ("F4", 50)):
        for b, prices in zip(books[:3], PRICES, strict=True):
            close(pm, name, b, prices, minutes)
        pm.consensus(name, "1X2", "Home", "0", "0.45", 170)
    cc.run(db, at=NOW, days=5)
    doc = cc.measure(db, since=NOW - timedelta(days=5), until=NOW)
    assert (doc["matches_with_price"], doc["matches_with_real_close"], doc["within_target"]) == (4, 4, 3)
    assert doc["share_within_target"] == 0.75 and doc["meets_acceptance"] is False, "75 % is under the plan's 80 %"
    assert doc["real_median_minutes"] == 24 and doc["prior_median_minutes"] == 170
