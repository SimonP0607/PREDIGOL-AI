"""The model's figures on the terms of the implied probability and the history (plan EA, EA-202; fbi.market.coherence)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.market import coherence as c


def dec(x: str) -> Decimal:
    return Decimal(x)


def test_a_whole_goal_line_is_shown_without_the_refund() -> None:
    out = c.conditional("over_under", {("Over", dec("1")): 0.792, ("Under", dec("1")): 0.039})
    assert out[("Over", dec("1"))] == pytest.approx(0.792 / 0.831)
    assert sum(v for v in out.values() if v is not None) == pytest.approx(1.0)


def test_a_half_line_is_left_as_it_is() -> None:
    out = c.conditional("over_under", {("Over", dec("2.5")): 0.6, ("Under", dec("2.5")): 0.4})
    assert out[("Over", dec("2.5"))] == pytest.approx(0.6)


def test_a_quarter_line_shows_no_figure() -> None:
    out = c.conditional("over_under", {("Over", dec("2.25")): 0.6, ("Under", dec("2.25")): 0.3})
    assert out == {("Over", dec("2.25")): None, ("Under", dec("2.25")): None}


def test_an_asian_handicap_pairs_the_home_line_with_the_away_negation() -> None:
    figures = {("Home", dec("-1")): 0.40, ("Away", dec("1")): 0.35, ("Home", dec("0")): 0.344, ("Away", dec("0")): 0.381}
    out = c.conditional("asian_handicap", figures)
    assert out[("Home", dec("-1"))] == pytest.approx(0.40 / 0.75)
    assert out[("Away", dec("0"))] == pytest.approx(0.381 / 0.725)


def test_a_side_without_its_pair_is_not_shown() -> None:
    assert c.conditional("draw_no_bet", {("Home", dec("0")): 0.86}) == {("Home", dec("0")): None}


def test_other_kinds_are_untouched() -> None:
    figures = {("Home", dec("0")): 0.5, ("Draw", dec("0")): 0.3, ("Away", dec("0")): 0.2}
    assert c.conditional("one_x_two", figures) == figures


def test_a_double_chance_is_two_outcomes_of_three() -> None:
    outcomes = {"Home": 0.5, "Draw": 0.3, "Away": 0.2}
    values = [c.double_chance(s, outcomes.get) for s in ("1X", "12", "X2")]
    assert values == pytest.approx([0.8, 0.7, 0.5])
    assert c.double_chance_ok([v for v in values if v is not None])
    assert c.double_chance("Home/Away", outcomes.get) == pytest.approx(0.7)
    assert c.double_chance("1X", {"Home": 0.5}.get) is None
    assert not c.double_chance_ok([0.386, 0.158, 0.456]), "three figures that add up to 1 are not a double chance"
