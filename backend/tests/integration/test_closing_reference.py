"""WHICH price is "the close" (plan F8.7, ``fbi.market.closing_reference``): the last Shin consensus before kick-off for the fair probability,
the provider's last pre-match price of the SAME bookmaker for the price move - and the first one is the one ``intel.outcomes`` has always
used for the closing-line value of a decision, so the post-mortem and the outcome of a decision can never quote two different closes.

The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.intel import outcomes
from fbi.market import closing_reference

from .conftest import Seed
from .helpers import scalar
from .test_daily_records import AT
from .test_postmortem_v6 import Pm

pytestmark = pytest.mark.integration


def pm_world(db: psycopg.Connection[Any], seed: Seed) -> Pm:
    return Pm(db, seed, investigation=False)


def test_the_close_is_the_last_shin_consensus_before_kickoff_and_nothing_else(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = pm_world(db, seed)
    for minutes, p, method in ((300, "0.40", "shin"), (175, "0.45", "shin"), (60, "0.47", "shin"), (30, "0.99", "proportional"),
                               (-10, "0.90", "shin")):
        pm.consensus("F3", "OU", "Over", "2.5", p, minutes, method=method)
    key = pm.key("F3", "OU", "Over", "2.5")
    close = closing_reference.closing_probabilities(db, [key])[key]
    assert (close.p_fair, close.minutes_to_ko, close.far) == (0.47, 60, False), \
        "the newest Shin snapshot BEFORE kick-off: not a later one, not another de-vigging method"
    assert close.evidence() == {"reference": closing_reference.REFERENCE, "as_of": close.as_of.isoformat(), "minutes_to_ko": 60,
                                "far": False, "best_odds": 2.0}
    assert closing_reference.closing_probabilities(db, [pm.key("F3", "OU", "Under", "2.5")]) == {}, "no consensus: no close, never an invention"


def test_a_close_captured_more_than_two_hours_before_kickoff_says_it_is_far(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = pm_world(db, seed)
    pm.consensus("F3", "OU", "Over", "2.5", "0.45", 120)
    pm.consensus("F4", "OU", "Over", "2.5", "0.45", 121)
    near, far = pm.key("F3", "OU", "Over", "2.5"), pm.key("F4", "OU", "Over", "2.5")
    got = closing_reference.closing_probabilities(db, [near, far])
    assert (got[near].far, got[far].far) == (False, True), "120 minutes is near, 121 is far"


def test_the_close_of_a_selection_is_the_one_the_outcome_of_a_decision_uses(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = pm_world(db, seed)
    for minutes, p in ((300, "0.40"), (175, "0.45"), (60, "0.47"), (-10, "0.90")):
        pm.consensus("F3", "OU", "Over", "2.5", p, minutes)
    # the decision layer's own outcomes: a decision on a pick that was settled
    cases = [("F1", "1X2", "Draw", "0"), ("F3", "OU", "Over", "2.5"), ("F4", "OU", "Under", "2.5")]  # the last has no consensus before kick-off
    pm.consensus("F4", "OU", "Under", "2.5", "0.60", -5)
    for name, market, selection, line in cases:
        decision = pm.decide(name, market, selection, line, pick=name)
        pick = pm.w.picks[name]
        pm.cur.execute("INSERT INTO picks.pick_results (pick_id,result_status,profit_units,settled_at,settlement_basis,rule_version) "
                       "VALUES (%s,'loss',-1,%s,'regulation_90','settle-v3')", (pick, AT + timedelta(hours=20)))
        assert decision > 0
    assert outcomes.settle_decisions(db, at=AT + timedelta(days=1)) == 3
    for name, market, selection, line in cases:
        key = pm.key(name, market, selection, line)
        row = db.execute("SELECT o.close_p_fair, o.close_as_of, o.close_minutes_to_ko FROM intel.decision_outcomes o "
                         "JOIN intel.decisions d ON d.id = o.decision_id WHERE d.fixture_id = %s AND d.market_key = %s AND d.selection = %s "
                         "AND d.line = %s", (key[0], market, selection, line)).fetchone()
        assert row is not None
        close = closing_reference.closing_probabilities(db, [key]).get(key)
        if row[0] is None:
            assert close is None, f"{name}: the outcome had no close and the reference found one"
        else:
            assert close is not None, f"{name}: the outcome had a close and the reference found none"
            assert (Decimal(str(close.p_fair)), close.as_of, close.minutes_to_ko) == (row[0], row[1], row[2]), name


def test_the_price_move_is_measured_against_the_last_price_of_the_same_bookmaker(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = pm_world(db, seed)
    pm.book_close("F3", pm.book, "1X2", "Home", "0", "2.000", 20)
    pm.book_close("F3", pm.other, "1X2", "Home", "0", "1.800", 95)
    first, second = (pm.f["F3"], pm.book, "1X2", "Home", Decimal("0")), (pm.f["F3"], pm.other, "1X2", "Home", Decimal("0"))
    missing = (pm.f["F3"], pm.book, "1X2", "Away", Decimal("0"))
    got = closing_reference.same_book_closes(db, [first, second, missing])
    assert got == {first: closing_reference.BookClose(2.0, 20), second: closing_reference.BookClose(1.8, 95)}, \
        "each book has its own last price; a book that was not read has none"


def test_a_batch_longer_than_the_chunk_is_mapped_back_to_the_right_selections(db: psycopg.Connection[Any], seed: Seed,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    pm = pm_world(db, seed)
    monkeypatch.setattr(closing_reference, "BATCH", 2)
    keys = []
    for n, line in enumerate(("0.5", "1.5", "2.5", "3.5", "4.5")):
        pm.consensus("F3", "OU", "Over", line, f"0.{9 - n}0", 60)
        keys.append(pm.key("F3", "OU", "Over", line))
    got = closing_reference.closing_probabilities(db, keys)
    assert {k[3]: v.p_fair for k, v in got.items()} == {Decimal("0.5"): 0.9, Decimal("1.5"): 0.8, Decimal("2.5"): 0.7, Decimal("3.5"): 0.6,
                                                         Decimal("4.5"): 0.5}
    assert scalar(db.execute("SELECT 1")) == 1
