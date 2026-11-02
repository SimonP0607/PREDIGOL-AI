"""Plan F0, defect 7: ONE definition of the closing-line value (``fbi.market.closing_value``, ``clv-v1``).

Two numbers were called "CLV" in the code and the learning put them side by side: the price against the same bookmaker's
closing price (margin in both) and the price at the closing fair probability (margin removed). They are four points
apart on average, and each was judged by its own threshold. These tests pin both formulas, their relation and the
thresholds, so that a number can never again be called by the other's name."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.market import closing_value as cv


def test_clv_is_the_price_taken_at_the_closing_fair_probability() -> None:
    assert cv.clv(2.10, 0.52) == pytest.approx(0.092)  # the case of tests/integration/test_intel.py: 2.10 x 0.52 - 1
    assert cv.clv(Decimal("2.10"), Decimal("0.52")) == Decimal("0.0920")
    assert cv.clv(2.0, 0.5) == 0.0, "a fair price: nothing gained, nothing lost"
    assert cv.clv(1.90, 0.50) == pytest.approx(-0.05), "a price under fair value"


def test_the_price_move_is_the_price_against_the_same_bookmakers_close() -> None:
    assert cv.price_move(2.10, 2.00) == pytest.approx(0.05)
    assert cv.price_move(Decimal("2.10"), Decimal("2.00")) == Decimal("0.05")
    assert cv.price_move(1.80, 2.00) == pytest.approx(-0.10), "the price drifted OUT after we took 1.80: against us"
    assert cv.price_move(2.0, 2.0) == 0.0


def test_a_margin_is_in_the_clv_and_not_in_the_price_move() -> None:
    """A fair two-way market (0.5 / 0.5) and a bookmaker with a 5 % margin: its price for either side is 1/(0.5 x 1.05).
    A selection taken at that price and unmoved at the close has a price move of 0 - and a CLV of minus the margin's
    share. That is what a price under fair value IS; and why the two cannot share a threshold."""
    margin = 0.05
    close_odds = 1 / (0.5 * (1 + margin))
    taken = close_odds  # nothing moved
    assert cv.price_move(taken, close_odds) == pytest.approx(0.0)
    assert cv.clv(taken, 0.5) == pytest.approx(1 / (1 + margin) - 1)
    assert cv.clv(taken, 0.5) < -0.04


def test_the_two_are_related_by_the_closing_margin() -> None:
    """clv = (1 + price_move) x (p_close x close_odds) - 1, for any odds, close and probability."""
    for odds, close, p in [(2.10, 2.00, 0.47), (3.4, 3.3, 0.28), (1.65, 1.7, 0.60), (5.0, 4.0, 0.22)]:
        assert cv.clv(odds, p) == pytest.approx((1 + cv.price_move(odds, close)) * (p * close) - 1)


def test_a_price_move_threshold_is_not_a_clv_threshold() -> None:
    """-3 % of price move is about -7 % of CLV with a closing margin of 4.5 %: the numbers cannot share a threshold."""
    close_odds = 2.0
    p_close = 1 / (close_odds * 1.045)  # the fair probability behind a 4.5 % margin on this price
    taken = close_odds * (1 + cv.MOVED_AGAINST)
    assert cv.price_move(taken, close_odds) == pytest.approx(cv.MOVED_AGAINST)
    assert cv.clv(taken, p_close) == pytest.approx(-0.0717, abs=2e-4)
    assert cv.clv(taken, p_close) < cv.MOVED_AGAINST - 0.04, "more than four points below the price move"


def test_thresholds_are_the_ones_the_post_mortems_already_used() -> None:
    assert cv.GOOD == 0.01, "pm-v3 and later: above +1 % GOOD, below -1 % BAD"
    assert cv.MOVED_AGAINST == -0.03, "pm-v2: a price move of 3 % or more against = MARKET_ERROR"
    assert cv.VERSION == "clv-v1"


@pytest.mark.parametrize(("value", "expected"), [
    (0.0101, "GOOD"), (0.01, "NEUTRAL"), (0.0, "NEUTRAL"), (-0.01, "NEUTRAL"), (-0.0101, "BAD"),
    (None, "UNKNOWN"), (float("nan"), "UNKNOWN"),
])
def test_the_quality_of_a_decision_price_from_its_clv(value: float | None, expected: str) -> None:
    assert cv.quality(value) == expected
