"""Plan F11 - the family forecasts against the market: the consensus of the books, and the comparison, checked against numbers worked by hand."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from fbi.families import score, versus
from fbi.families.versus import Quote

D = Decimal
KNOWN = datetime(2035, 3, 1, 12, tzinfo=UTC)


def quote(book: int, selection: str, odds: float, *, line: str = "9.5", kind: str = "over_under", key: str = "CORNERS_OU", fixture: int = 1,
          ref: str = "close") -> Quote:
    return Quote(ref, fixture, book, key, kind, selection, D(line), odds)


def test_only_a_line_that_cannot_push_is_compared() -> None:
    for line, expected in (("0", True), ("0.00", True), ("9.5", True), ("10.50", True), ("10", False), ("10.25", False), ("10.75", False)):
        assert versus.comparable(D(line)) is expected, line


def test_the_consensus_is_the_mean_of_the_complete_books_each_de_vigged_on_its_own() -> None:
    quotes = [
        quote(1, "Over", 1.80), quote(1, "Under", 2.10),    # 2.10 / 3.90 = 0.538462 for the over
        quote(2, "Over", 1.90), quote(2, "Under", 2.00),    # 2.00 / 3.90 = 0.512821
        quote(3, "Over", 1.30), quote(3, "Under", 1.30),    # a margin of 54 %: not a price
        quote(4, "Over", 2.20), quote(4, "Under", 2.20),    # a margin below zero: stale or broken
        quote(5, "Over", 1.95),                             # half a book
    ]
    fair = versus.consensus(quotes)
    over, books = fair[("close", 1, "CORNERS_OU", D("9.5"), "Over")]
    assert books == 2 and over == pytest.approx((2.10 / 3.90 + 2.00 / 3.90) / 2)
    under, _ = fair[("close", 1, "CORNERS_OU", D("9.5"), "Under")]
    assert under == pytest.approx(1 - over), "the two sides of a book share the whole probability"
    assert len(fair) == 2


def test_three_outcomes_are_de_vigged_together_and_a_kind_without_a_consensus_is_left_alone() -> None:
    quotes = [quote(1, "Home", 2.0, line="0", kind="one_x_two", key="CORNERS_1X2"), quote(1, "Draw", 3.5, line="0", kind="one_x_two", key="CORNERS_1X2"),
              quote(1, "Away", 4.0, line="0", kind="one_x_two", key="CORNERS_1X2"),
              quote(1, "Home", 1.5, line="0", kind="double_chance", key="CORNERS_DC"), quote(1, "Draw", 1.5, line="0", kind="double_chance", key="CORNERS_DC")]
    fair = versus.consensus(quotes)
    book = 1 / 2.0 + 1 / 3.5 + 1 / 4.0
    assert fair[("close", 1, "CORNERS_1X2", D(0), "Home")][0] == pytest.approx(0.5 / book)
    assert fair[("close", 1, "CORNERS_1X2", D(0), "Draw")][0] == pytest.approx((1 / 3.5) / book)
    assert sum(p for (ref, _, key, _, _), (p, _) in fair.items() if key == "CORNERS_1X2") == pytest.approx(1.0)
    assert not [k for k in fair if k[2] == "CORNERS_DC"], "double chance sums to two: it has to be mapped, not de-vigged"


def test_each_moment_has_its_own_consensus_and_so_does_each_line() -> None:
    quotes = [quote(1, "Over", 1.80), quote(1, "Under", 2.10), quote(1, "Over", 2.10, ref="h24"), quote(1, "Under", 1.80, ref="h24"),
              quote(1, "Over", 1.50, line="8.5"), quote(1, "Under", 2.60, line="8.5")]
    fair = versus.consensus(quotes)
    assert fair[("close", 1, "CORNERS_OU", D("9.5"), "Over")][0] == pytest.approx(2.10 / 3.90)
    assert fair[("h24", 1, "CORNERS_OU", D("9.5"), "Over")][0] == pytest.approx(1.80 / 3.90)
    assert fair[("close", 1, "CORNERS_OU", D("8.5"), "Over")][0] == pytest.approx(2.60 / 4.10)


def graded(fixture: int, p: float, won: int, *, line: str = "9.5", selection: str = "Over", model: str = "family-corners_ft", key: str = "CORNERS_OU") -> score.Graded:
    return score.Graded(score.Row(fixture, model, key, D(line), selection, p, KNOWN), won)


def fair_of(p: float, books: int = 3, *, fixtures: range = range(1, 5), line: str = "9.5", ref: str = "close", key: str = "CORNERS_OU") -> dict[versus.FairKey, tuple[float, int]]:
    return {(ref, f, key, D(line), "Over"): (p, books) for f in fixtures}


def test_the_comparison_is_the_log_loss_of_each_and_their_difference_by_match() -> None:
    # the model says 0.6 on four matches and the market 0.5; the over happens on three of them
    rows = [graded(1, 0.6, 1), graded(2, 0.6, 1), graded(3, 0.6, 1), graded(4, 0.6, 0)]
    block = versus.versus(rows, fair_of(0.5))["models"]["family-corners_ft"]["close"]
    assert block["n"] == 4 and block["fixtures"] == 4 and block["mean_books"] == 3
    assert block["log_loss_market"] == pytest.approx(math.log(2))
    assert block["log_loss_model"] == pytest.approx(-(3 * math.log(0.6) + math.log(0.4)) / 4)
    # the model gains ln(1.2) = 0.182322 on each win and loses ln(0.8) = 0.223144 on the loss: 0.080955 on average
    assert block["market_minus_model"] == pytest.approx((3 * 0.1823216 - 0.2231436) / 4, abs=1e-6)
    # sqrt(3 * (0.1823216 - 0.0809547)^2 + (-0.2231436 - 0.0809547)^2) / 4
    assert block["se"] == pytest.approx(0.0877856, abs=1e-5)
    assert block["mean_p_model"] == pytest.approx(0.6) and block["mean_p_market"] == pytest.approx(0.5) and block["observed"] == pytest.approx(0.75)


def test_the_two_sides_of_a_line_of_one_match_are_one_observation_for_the_standard_error() -> None:
    over, under = graded(1, 0.6, 1), graded(1, 0.4, 0, selection="Under")
    fair = {("close", 1, "CORNERS_OU", D("9.5"), "Over"): (0.5, 3), ("close", 1, "CORNERS_OU", D("9.5"), "Under"): (0.5, 3)}
    both = versus.versus([over, under], fair)["models"]["family-corners_ft"]["close"]
    alone = versus.versus([over], fair)["models"]["family-corners_ft"]["close"]
    assert both["n"] == 2 and both["fixtures"] == 1
    assert both["market_minus_model"] == pytest.approx(alone["market_minus_model"]), "mirror images: the same difference twice"
    assert both["se"] == 0.0 == alone["se"], "one match, one cluster: the spread around the mean is nil"


def test_what_the_market_cannot_say_is_left_out_not_counted() -> None:
    rows = [graded(1, 0.6, 1), graded(2, 0.6, 1, line="10"), graded(3, 0.6, 1, line="10.25"), graded(4, 0.6, 1), graded(5, 0.6, 1)]
    fair = {**fair_of(0.5, fixtures=range(1, 5)), ("close", 4, "CORNERS_OU", D("9.5"), "Over"): (0.5, 2)}   # match 4 has two books only
    fair.update({("close", 2, "CORNERS_OU", D("10"), "Over"): (0.5, 3), ("close", 3, "CORNERS_OU", D("10.25"), "Over"): (0.5, 3)})
    block = versus.versus(rows, fair)["models"]["family-corners_ft"]["close"]
    assert block["n"] == 1, "a line that can push, a consensus of two books, a match with no price: none is compared"
    assert versus.versus(rows, fair, min_books=2)["models"]["family-corners_ft"]["close"]["n"] == 2
    assert versus.versus(rows, {})["models"] == {}


def test_the_two_moments_and_each_market_are_reported_apart() -> None:
    rows = [graded(1, 0.6, 1), graded(1, 0.7, 1, key="CORNERS_OU_HOME"), graded(2, 0.6, 0)]
    fair = {**fair_of(0.5, fixtures=range(1, 3)), **fair_of(0.55, fixtures=range(1, 3), ref="h24"), **fair_of(0.5, fixtures=range(1, 2), key="CORNERS_OU_HOME")}
    entry = versus.versus(rows, fair)["models"]["family-corners_ft"]
    assert entry["close"]["n"] == 3 and entry["h24"]["n"] == 2
    assert {(x["ref"], x["key"], x["n"]) for x in entry["by_key"]} == {("close", "CORNERS_OU", 2), ("close", "CORNERS_OU_HOME", 1), ("h24", "CORNERS_OU", 2)}


def test_a_model_that_knows_more_than_the_market_wins_and_one_that_knows_less_loses() -> None:
    better = [graded(i, 0.8, 1) for i in range(1, 5)] + [graded(i, 0.2, 0) for i in range(5, 9)]
    market = fair_of(0.55, fixtures=range(1, 5)) | fair_of(0.45, fixtures=range(5, 9))
    assert versus.versus(better, market)["models"]["family-corners_ft"]["close"]["market_minus_model"] > 0.2
    worse = [graded(i, 0.2, 1) for i in range(1, 5)] + [graded(i, 0.8, 0) for i in range(5, 9)]
    assert versus.versus(worse, market)["models"]["family-corners_ft"]["close"]["market_minus_model"] < -0.5


def test_the_text_says_who_was_better_and_by_how_much() -> None:
    empty = versus.versus([], {})
    assert "no graded row has a consensus of 3+ books" in versus.render(empty)
    rows = [graded(i, 0.6, i % 2) for i in range(1, 81)]
    report = versus.versus(rows, fair_of(0.5, fixtures=range(1, 81)))
    text = versus.render(report, min_rows=50)
    assert "family-corners_ft close: 80 rows of 80 matches" in text and "market minus model" in text
    assert "CORNERS_OU" in text and "model said  60.0 %  market  50.0 %" in text
    assert "CORNERS_OU" not in versus.render(report, min_rows=100), "a market with few rows is not named"


def test_no_match_means_no_query() -> None:
    class Unused:
        def cursor(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("nothing to look up, nothing to ask the database")

    assert versus.load_quotes(Unused(), fixtures=[], keys=["CORNERS_OU"], since=KNOWN) == []  # type: ignore[arg-type]
    assert versus.load_quotes(Unused(), fixtures=[1], keys=[], since=KNOWN) == []  # type: ignore[arg-type]
