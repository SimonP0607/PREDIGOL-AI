"""The price rule, a yardstick in shadow (``fbi.decision.price_rule``, plan INT-A10, IA-054), against a real PostgreSQL: the captures of the
window read by match (only Shin, only before the window's end, never a postponed match), the first capture that beats the consensus taken,
the close read by the system's own reference, and the book: a capture's take is the same whether it is read from the consensus or from the
book's RAW body, and a later refresh gives the book a close the captures do not have. Nothing is written."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest

from fbi.decision import book_price, price_rule
from fbi.decision.engine import BOOK
from fbi.market import closing_reference
from fbi.storage.payload_store import PayloadStore
from tests.integration.conftest import Seed

from .test_decision_v2_book_price import book_ask, captured
from .test_decision_v2_replay import writes
from .test_odds_book import KO, T3, T4, real_body
from .test_odds_quotes_extract import add_fixture, add_payload

pytestmark = pytest.mark.integration

PID = 880_321
HOME = ("1X2", "Home", Decimal("0.00"))
KO_A = datetime(2026, 7, 3, 2, 17, tzinfo=UTC)
"""A kick-off no other test uses: the long history's window holds only this test's matches."""


def consensus(db: psycopg.Connection[Any], seed: Seed, fixture_id: int, as_of: Any, odds: float, p: float, *, method: str = "shin",
              selection: str = "Home", books: int = 6) -> None:
    db.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, n_bookmakers, "
               "overround, best_odds, best_bookmaker_id) VALUES (%s, '1X2', %s, 0, %s, %s, %s, %s, 0.05, %s, %s)",
               (fixture_id, selection, as_of, method, p, books, odds, seed.bookmaker_id))


def test_the_long_history_takes_the_first_capture_that_beats_the_consensus_and_measures_it_against_the_systems_close(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    a = add_fixture(db, seed, PID, KO_A)
    postponed = add_fixture(db, seed, PID + 1, KO_A)
    db.execute("UPDATE core.fixtures SET status_short = 'PST' WHERE id = %s", (postponed,))
    consensus(db, seed, a, KO_A - timedelta(hours=48), 2.6, 0.5)                 # outside the window: not a moment of the rule
    consensus(db, seed, a, KO_A - timedelta(hours=30), 2.0, 0.5)                 # no value
    consensus(db, seed, a, KO_A - timedelta(hours=20), 2.2, 0.48)                # taken: +5.6 % over the consensus
    consensus(db, seed, a, KO_A - timedelta(hours=20), 2.9, 0.48, method="proportional")  # another de-vig: never read
    consensus(db, seed, a, KO_A - timedelta(hours=5), 2.1, 0.5)                  # the close: the last Shin consensus before kick-off
    consensus(db, seed, a, KO_A + timedelta(minutes=5), 1.01, 0.99)              # after kick-off: never the close
    consensus(db, seed, a, KO_A - timedelta(hours=20), 2.3, 0.45, selection="Away", books=2)  # two books: thin
    consensus(db, seed, postponed, KO_A - timedelta(hours=20), 2.2, 0.48)

    before = writes(db)
    out = price_rule.report(db, since=KO_A - timedelta(days=2), until=KO_A + timedelta(hours=1))
    assert writes(db) == before, "the report wrote nothing"
    assert out["population"] == {"matches": 1, "matches_with_price": 1, "selections_with_price": 2, "moments": 3}
    assert out["taken"]["selections"] == 1 and out["taken"]["minutes_to_kickoff"]["p50"] == 1200.0
    assert out["measured"]["selections"] == 1 and out["measured"]["without_clv"] == {}
    assert out["clv"]["by_match"]["mean"] == pytest.approx(2.2 * 0.5 - 1) and out["close"]["minutes_to_kickoff"]["p50"] == 300.0
    assert out["close"]["reference"] == {closing_reference.REFERENCE: 1} and out["gate"]["verdict"] == price_rule.PENDING
    assert out["p_drift_pp"]["mean"] == pytest.approx(2.0)


def test_a_capture_is_taken_alike_from_the_consensus_and_from_the_book_and_a_refresh_gives_the_book_a_later_close(
        db: psycopg.Connection[Any], seed: Seed, tmp_path: Path) -> None:
    fixture_id = add_fixture(db, seed, PID, KO)
    captured(db, seed, tmp_path, PID, real_body(PID), T3)
    store = PayloadStore(tmp_path)
    fixtures = {fixture_id: KO}

    before = writes(db)
    from_captures, _ = price_rule.measure_consensus(db, fixtures)
    from_book, seen = price_rule.measure_book(book_price.read(db, store, [fixture_id]))
    assert writes(db) == before
    takes = {m.taken.key: (m.taken.at, m.taken.quote.best_odds, m.taken.quote.p_fair, m.taken.quote.n_bookmakers) for m in from_captures}
    assert takes, "the real answer has prices that beat the consensus"
    assert takes == {m.taken.key: (m.taken.at, m.taken.quote.best_odds, m.taken.quote.p_fair, m.taken.quote.n_bookmakers)
                     for m in from_book}, "the same capture: the same takes, to the digit"
    assert {m.missing for m in from_captures} == {m.missing for m in from_book} == {price_rule.NOT_LATER}, (
        "the capture is its own close: nothing is measured against itself")
    assert seen["moments"] == 1

    later = add_payload(db, seed, store, real_body(PID, bump="0.02"), fixture=PID, fetched_at=T4)
    book_ask(db, PID, T4, later)
    refreshed, _ = price_rule.measure_book(book_price.read(db, store, [fixture_id]))
    measured = [m for m in refreshed if m.clv is not None]
    assert measured and all(m.close is not None and m.close.observed_at == T4 for m in measured)
    again, _ = price_rule.measure_consensus(db, fixtures)
    assert {m.missing for m in again} == {price_rule.NOT_LATER}, "a refresh is not a capture: the captures still have no later close"
    out = price_rule.report(db, since=KO - timedelta(days=2), until=KO + timedelta(hours=1), source=BOOK, store=store)
    assert out["measured"]["selections"] == len(measured) and out["reader"]["unreadable"] == 0
    assert out["close"]["minutes_to_kickoff"]["p50"] == (KO - T4).total_seconds() / 60
