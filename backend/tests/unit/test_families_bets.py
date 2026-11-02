"""Plan F11 - the criterion for a family to decide in shadow: the simulated bets, what they were worth and the verdict, checked against numbers
worked by hand."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.families import bets, score, versus
from fbi.families.versus import Quote
from fbi.market import closing_value

D = Decimal
KNOWN = datetime(2035, 3, 1, 12, tzinfo=UTC)
MODEL = "family-corners_ft"
FAIR = (1.90, 1.90)
"""A margin of 5.3 % and a probability of exactly one half for each side (a book with no margin at all is not a price)."""
DAY_BEFORE = [FAIR, FAIR, (2.00, 1.80)]
"""Two even books and one that pays more for the over: the best over is 2.00 and the consensus of the over (0.5 + 0.5 + 1.80 / 3.80) / 3 = 0.491228."""
P_PICK = (0.5 + 0.5 + 1.80 / 3.80) / 3


def books(prices: list[tuple[float, float]], *, ref: str, fixture: int = 1, line: str = "9.5", key: str = "CORNERS_OU") -> list[Quote]:
    """The over and the under of one line, one book each: ``prices`` is (over, under) per book."""
    out: list[Quote] = []
    for book, (over, under) in enumerate(prices, start=1):
        out.append(Quote(ref, fixture, book, key, "over_under", "Over", D(line), over))
        out.append(Quote(ref, fixture, book, key, "over_under", "Under", D(line), under))
    return out


def forecast(fixture: int, p_over: float, over_won: bool, *, line: str = "9.5", key: str = "CORNERS_OU", model: str = MODEL) -> list[score.Graded]:
    """What the model said a day before about the two sides of a line, and which side the match turned out to be."""
    return [score.Graded(score.Row(fixture, model, key, D(line), "Over", p_over, KNOWN), int(over_won)),
            score.Graded(score.Row(fixture, model, key, D(line), "Under", 1 - p_over, KNOWN), int(not over_won))]


def world(n: int, close: tuple[float, float], *, p_over: float = 0.55, over_won: bool = True) -> tuple[list[score.Graded], list[Quote]]:
    """``n`` matches with the same story: ``DAY_BEFORE`` a day before, three books at ``close`` at the last price, the model at ``p_over``."""
    rows: list[score.Graded] = []
    quotes: list[Quote] = []
    for fixture in range(1, n + 1):
        rows += forecast(fixture, p_over, over_won)
        quotes += books(DAY_BEFORE, ref="h24", fixture=fixture) + books([close] * 3, ref="close", fixture=fixture)
    return rows, quotes


def prices(quotes: list[Quote]) -> tuple[dict[versus.FairKey, tuple[float, int]], dict[versus.FairKey, tuple[float, int]]]:
    """What the comparison keeps of the quotes: the consensus of the books and their best price."""
    return versus.consensus(quotes), versus.best_prices(quotes)


def simulate(rows: list[score.Graded], quotes: list[Quote], *, min_ev: float = bets.MIN_EV, min_books: int = versus.MIN_BOOKS) -> list[bets.Bet]:
    return bets.simulate(rows, *prices(quotes), min_ev=min_ev, min_books=min_books)


def report(rows: list[score.Graded], quotes: list[Quote], *, min_ev: float = bets.MIN_EV, min_books: int = versus.MIN_BOOKS,
           min_bets: int = bets.MIN_BETS) -> dict[str, Any]:
    return bets.report(rows, *prices(quotes), min_ev=min_ev, min_books=min_books, min_bets=min_bets)


def test_the_constants_are_the_plans_criterion() -> None:
    assert bets.MIN_BETS == 300 and bets.MIN_EV == 0.03
    assert bets.PICK_REF == "h24" and bets.CLOSE_REF == "close" and timedelta(hours=24) == bets.PICK_LEAD
    assert {bets.PICK_REF, bets.CLOSE_REF} <= {ref for ref, _ in versus.REFERENCES}, "the prices are read at the moments the bets are taken and closed"
    assert versus.MIN_BOOKS == 3


def test_a_book_with_no_margin_is_not_a_price_so_the_even_story_needs_a_margin() -> None:
    assert versus.consensus(books([(2.00, 2.00)] * 3, ref="h24")) == {}, "1 / 2 + 1 / 2 = 1: stale or broken"
    assert len(versus.consensus(books([FAIR] * 3, ref="h24"))) == 2


def test_the_best_price_is_read_from_the_complete_books_only() -> None:
    def one(book: int, selection: str, odds: float) -> Quote:
        return Quote("h24", 1, book, "CORNERS_OU", "over_under", selection, D("9.5"), odds)

    quotes = [
        *books([(1.80, 2.10), (1.90, 2.00)], ref="h24"),
        one(3, "Over", 2.60), one(3, "Under", 1.80),     # 0.385 + 0.556 = 0.94: a margin below zero, so not a price
        one(4, "Over", 3.00),                            # half a book
    ]
    best = versus.best_prices(quotes)
    assert best[("h24", 1, "CORNERS_OU", D("9.5"), "Over")] == (1.90, 2)
    assert best[("h24", 1, "CORNERS_OU", D("9.5"), "Under")] == (2.10, 2)
    assert len(best) == 2
    assert {k: n for k, (_, n) in best.items()} == {k: n for k, (_, n) in versus.consensus(quotes).items()}, "the same books as the consensus"


def test_a_bet_is_taken_at_the_best_price_a_day_before_and_valued_three_ways() -> None:
    quotes = [
        *books(DAY_BEFORE, ref="h24"),
        # at the last price before the kick-off the over has shortened in every book: 2.20 / (1.70 + 2.20) = 0.564103
        *books([(1.70, 2.20)] * 3, ref="close"),
    ]
    [bet] = simulate(forecast(1, 0.55, True), quotes)
    assert (bet.model, bet.key, bet.fixture_id, bet.line, bet.selection, bet.books, bet.won) == (MODEL, "CORNERS_OU", 1, D("9.5"), "Over", 3, 1)
    assert bet.odds == 2.00, "the best price of the three books"
    assert bet.believed == pytest.approx(0.10)  # 2.00 x 0.55 - 1
    assert bet.p_pick == pytest.approx(P_PICK) == pytest.approx(0.491228, abs=1e-6)
    assert bet.at_pick == pytest.approx(-0.017544, abs=1e-6)  # 2.00 x 0.491228 - 1: shopping for the best price paid back less than the margin
    assert bet.p_close == pytest.approx(2.20 / 3.90)
    assert bet.clv == pytest.approx(0.128205, abs=1e-6)  # 2.00 x 0.564103 - 1: the market came to agree with the price
    assert bet.clv == closing_value.clv(bet.odds, bet.p_close or 0.0), "the one definition of the system"
    assert bet.profit == pytest.approx(1.0)
    [lost] = simulate(forecast(1, 0.55, False), quotes)  # the same story, and the under won
    assert (lost.selection, lost.won, lost.profit) == ("Over", 0, -1.0)


def test_the_value_floor_is_met_at_the_price_and_can_be_moved() -> None:
    quotes = books(DAY_BEFORE, ref="h24") + books([FAIR] * 3, ref="close")
    assert simulate(forecast(1, 0.51, True), quotes) == [], "2.00 x 0.51 - 1 = 0.02 is below 3 %"
    assert [b.selection for b in simulate(forecast(1, 0.52, True), quotes)] == ["Over"], "0.04 is above it; the under at 0.48 pays 1.90: -0.09"
    assert [b.selection for b in simulate(forecast(1, 0.51, True), quotes, min_ev=0.01)] == ["Over"]


def test_the_best_line_of_a_market_is_the_only_bet_and_each_market_and_match_has_its_own() -> None:
    cards = "family-cards_lines_ft"
    rows = [
        *forecast(1, 0.55, True, line="9.5"),                    # Over 9.5 at 2.00: believed +0.10
        *forecast(1, 0.45, False, line="10.5"),                  # Under 10.5 at 2.40 (the over 10.5 pays 1.60): 2.40 x 0.55 - 1 = +0.32, the best
        *forecast(1, 0.56, True, line="4.5", key="CORNERS_OU_HOME"),
        *forecast(1, 0.55, True, line="4.5", key="CARDS_OU", model=cards),
        *forecast(2, 0.55, False),
    ]
    quotes: list[Quote] = []
    for ref in ("h24", "close"):
        day = ref == "h24"
        quotes += (books(DAY_BEFORE if day else [FAIR] * 3, ref=ref, line="9.5")
                   + books([(1.60, 2.40)] * 3 if day else [FAIR] * 3, ref=ref, line="10.5")
                   + books([(1.95, 1.95)] * 3 if day else [FAIR] * 3, ref=ref, line="4.5", key="CORNERS_OU_HOME")
                   + books(DAY_BEFORE if day else [FAIR] * 3, ref=ref, line="4.5", key="CARDS_OU")
                   + books(DAY_BEFORE if day else [FAIR] * 3, ref=ref, fixture=2))
    taken = simulate(rows, quotes)
    assert [(b.model, b.fixture_id, b.key, b.line, b.selection) for b in taken] == [
        (cards, 1, "CARDS_OU", D("4.5"), "Over"),
        (MODEL, 1, "CORNERS_OU", D("10.5"), "Under"),
        (MODEL, 1, "CORNERS_OU_HOME", D("4.5"), "Over"),
        (MODEL, 2, "CORNERS_OU", D("9.5"), "Over"),
    ]
    under = taken[1]
    assert under.odds == 2.40 and under.believed == pytest.approx(0.32)
    assert under.won == 1 and under.profit == pytest.approx(1.40), "the over of 10.5 lost in this match, so the under won"
    assert under.p_pick == pytest.approx(0.40) and under.at_pick == pytest.approx(-0.04)  # 2.40 x 0.40 - 1
    assert under.p_close == pytest.approx(0.5) and under.clv == pytest.approx(0.20)  # the line closed even: 2.40 x 0.50 - 1
    assert taken[2].odds == 1.95 and taken[2].clv == pytest.approx(-0.025)  # 1.95 x 0.50 - 1: the price was the books', the close even
    assert simulate(list(reversed(rows)), quotes) == taken, "the order of the rows decides nothing"


def test_a_tie_between_two_lines_falls_to_the_same_one_whatever_the_order() -> None:
    rows = forecast(1, 0.55, True, line="8.5") + forecast(1, 0.55, True, line="9.5")
    quotes = books(DAY_BEFORE, ref="h24", line="8.5") + books(DAY_BEFORE, ref="h24", line="9.5")
    assert [b.line for b in simulate(rows, quotes)] == [D("9.5")] == [b.line for b in simulate(list(reversed(rows)), quotes)]


def test_what_the_market_cannot_say_is_not_bet() -> None:
    rows = [g for fixture, line in ((1, "10"), (2, "9.5"), (3, "9.5"), (4, "9.5"), (5, "9.5")) for g in forecast(fixture, 0.55, True, line=line)]
    quotes = [
        *books(DAY_BEFORE, ref="h24", fixture=1, line="10"),     # a line that can push: the books' probability is not the model's
        *books([FAIR] * 2, ref="h24", fixture=2),                # two books: not a consensus
        *books(DAY_BEFORE, ref="close", fixture=3),              # a price at the close and none a day before
        *books([(1.30, 1.30)] * 3, ref="h24", fixture=4),        # margins of 54 %: not prices
        *books(DAY_BEFORE, ref="h24", fixture=5),                # and this one is a bet
    ]
    assert [b.fixture_id for b in simulate(rows, quotes)] == [5]
    assert [b.fixture_id for b in simulate(rows, quotes, min_books=2)] == [2, 5], "with two books asked for the second match has its market"


def test_a_bet_with_no_closing_consensus_is_counted_apart_and_not_valued() -> None:
    quotes = books(DAY_BEFORE, ref="h24") + books([FAIR] * 2, ref="close")
    [bet] = simulate(forecast(1, 0.55, True), quotes)
    assert bet.p_close is None and bet.clv is None
    entry = report(forecast(1, 0.55, True), quotes)["models"][MODEL]
    assert (entry["taken"], entry["no_closing_line"], entry["n"], entry["clv"]) == (1, 1, 0, None)
    assert entry["verdict"] == bets.TOO_FEW and entry["needed"] == 300


@pytest.mark.parametrize(
    ("n", "close", "expected", "clv"),
    [
        (299, (1.90, 2.10), bets.TOO_FEW, 0.05),        # 2.00 x 2.10 / 4.00 - 1
        (300, (1.90, 2.10), bets.MEETS, 0.05),
        (300, FAIR, bets.MEETS, 0.0),                   # not negative is enough: zero passes
        (300, (2.10, 1.90), bets.CLV_NEGATIVE, -0.05),  # 2.00 x 1.90 / 4.00 - 1
        (299, (2.10, 1.90), bets.TOO_FEW, -0.05),       # with too few bets it does not matter which way the value points
    ],
)
def test_the_criterion_is_300_bets_and_a_closing_line_value_that_is_not_negative(n: int, close: tuple[float, float], expected: str, clv: float) -> None:
    rows, quotes = world(n, close)
    entry = report(rows, quotes)["models"][MODEL]
    assert entry["n"] == n and entry["fixtures"] == n and entry["verdict"] == expected
    assert entry["clv"] == pytest.approx(clv, abs=1e-9) and entry["needed"] == max(0, 300 - n)
    assert entry["believed"] == pytest.approx(0.10) and entry["at_pick"] == pytest.approx(2 * P_PICK - 1)
    assert entry["return"] == pytest.approx(1.0) and entry["return_se"] == pytest.approx(0.0), "the over won every time"


def test_the_threshold_of_bets_can_be_moved_and_bets_that_cannot_be_valued_do_not_pass() -> None:
    rows, quotes = world(10, (1.90, 2.10))
    assert report(rows, quotes, min_bets=10)["models"][MODEL]["verdict"] == bets.MEETS
    assert report(rows, quotes, min_bets=11)["models"][MODEL]["verdict"] == bets.TOO_FEW
    assert bets.verdict(0, None) == bets.TOO_FEW
    assert bets.verdict(300, None) == bets.CLV_NEGATIVE


def test_the_standard_errors_are_clustered_by_match() -> None:
    # match 1: two bets (two markets), each with a closing-line value of +0.10 (the over closed at 2.20 / 4.00 = 0.55); match 2: one bet at -0.05
    rows = [*forecast(1, 0.55, True), *forecast(1, 0.55, True, line="4.5", key="CORNERS_OU_HOME"), *forecast(2, 0.55, False)]
    quotes = [*books(DAY_BEFORE, ref="h24"), *books([(1.80, 2.20)] * 3, ref="close"),
              *books(DAY_BEFORE, ref="h24", line="4.5", key="CORNERS_OU_HOME"), *books([(1.80, 2.20)] * 3, ref="close", line="4.5", key="CORNERS_OU_HOME"),
              *books(DAY_BEFORE, ref="h24", fixture=2), *books([(2.10, 1.90)] * 3, ref="close", fixture=2)]
    entry = report(rows, quotes)["models"][MODEL]
    assert entry["n"] == 3 and entry["fixtures"] == 2
    assert entry["clv"] == pytest.approx(0.05)
    # the match 1 sums 2 x (0.10 - 0.05) = 0.10 and the match 2 -0.10: sqrt(0.10^2 + 0.10^2) / 3. Three independent bets would give 0.0408
    assert entry["clv_se"] == pytest.approx(0.0471405, abs=1e-6)
    # the return: +1, +1, -1; mean 1/3; the match 1 sums 2 x (1 - 1/3) = 4/3 and the match 2 -4/3: sqrt(2 x (4/3)^2) / 3
    assert entry["return"] == pytest.approx(1 / 3) and entry["return_se"] == pytest.approx(0.628539, abs=1e-6)
    assert entry["hit_rate"] == pytest.approx(2 / 3) and entry["mean_odds"] == pytest.approx(2.0)
    assert {x["key"]: x["n"] for x in entry["by_key"]} == {"CORNERS_OU": 2, "CORNERS_OU_HOME": 1}


def test_a_family_with_forecasts_and_no_price_is_listed_with_no_bets() -> None:
    rows = forecast(1, 0.55, True, model="family-yellow_ft", key="YELLOW_OU")
    entry = report(rows, [])["models"]["family-yellow_ft"]
    assert (entry["taken"], entry["n"], entry["verdict"], entry["needed"]) == (0, 0, bets.TOO_FEW, 300)
    assert "family-yellow_ft: no bet -> too few bets" in bets.render(report(rows, []))
    assert report([], [])["models"] == {}


def test_the_text_says_where_each_family_stands() -> None:
    rows, quotes = world(300, (1.90, 2.10))
    text = bets.render(report(rows, quotes), min_rows=50)
    assert "300+ simulated bets (1 unit at the best price 24 h before the kick-off, when the model saw a value of 3 % or more" in text
    assert (f"{MODEL}: 300 bets in 300 matches - the model believed +10.0 %, the books' probability that day -1.8 %, closing line +5.0 % ± 0.0, "
            "return +100.0 % ± 0.0 -> meets the criterion") in text
    assert "CORNERS_OU" in text and "CORNERS_OU" not in bets.render(report(rows, quotes), min_rows=301), "a market with few bets is not named"

    few = bets.render(report(*world(1, (2.10, 1.90))))
    assert "1 bets in 1 matches (299 short of 300)" in few and "closing line -5.0 %" in few and "-> too few bets" in few

    negative = bets.render(report(*world(300, (2.10, 1.90))))
    assert "closing line -5.0 % ± 0.0" in negative and "-> closing-line value negative" in negative

    apart = bets.render(report(forecast(1, 0.55, True), books(DAY_BEFORE, ref="h24") + books([FAIR] * 2, ref="close")))
    assert f"{MODEL}: no bet; 1 more with no closing consensus -> too few bets" in apart

    assert "no forecast stored 24 hours or more before a kick-off has been graded yet" in bets.render(report([], []))


def test_a_value_inside_the_noise_is_said_to_be() -> None:
    # two matches, closing-line values +0.10 and -0.05: mean +0.025 ± 0.0530 - it meets the plan's threshold of two bets and says what it is worth
    rows = [*forecast(1, 0.55, True), *forecast(2, 0.55, True)]
    quotes = [*books(DAY_BEFORE, ref="h24"), *books([(1.80, 2.20)] * 3, ref="close"),
              *books(DAY_BEFORE, ref="h24", fixture=2), *books([(2.10, 1.90)] * 3, ref="close", fixture=2)]
    noisy = report(rows, quotes, min_bets=2)
    assert noisy["models"][MODEL]["verdict"] == bets.MEETS
    assert "meets the criterion, but the closing-line value is within 2 standard errors of zero" in bets.render(noisy)
    assert "within 2 standard errors" not in bets.render(report(*world(2, (1.90, 2.10)), min_bets=2)), "a certain value is not called noise"


def test_the_report_is_json_ready() -> None:
    rows, quotes = world(3, (1.90, 2.10))
    ready = report(rows, quotes)
    assert json.loads(json.dumps(ready))["criterion"] == {"min_bets": 300, "min_ev": 0.03, "min_books": 3, "pick": "h24", "close": "close"}
    assert json.loads(json.dumps(report([], [])))["models"] == {}


def test_the_prices_are_read_a_few_matches_at_a_time_and_boiled_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """``versus.read_prices``: the quotes of a window of weeks do not fit in memory, so each chunk of matches is read, boiled down to its consensus
    and best price, and let go - the result is the one of reading all at once."""
    quotes = [q for fixture in range(1, 8) for q in books(DAY_BEFORE, ref="h24", fixture=fixture) + books([FAIR] * 3, ref="close", fixture=fixture)]
    asked: list[list[int]] = []

    def load(conn: object, *, fixtures: list[int], keys: list[str], since: datetime) -> list[Quote]:
        asked.append(list(fixtures))
        assert keys == ["CORNERS_OU"] and since == KNOWN
        return [q for q in quotes if q.fixture_id in fixtures]

    monkeypatch.setattr(versus, "load_quotes", load)
    monkeypatch.setattr(versus, "CHUNK", 3)
    fair, best = versus.read_prices(None, fixtures=[7, 1, 3, 2, 5, 4, 6, 3], keys=["CORNERS_OU"], since=KNOWN)  # type: ignore[arg-type]
    assert asked == [[1, 2, 3], [4, 5, 6], [7]], "sorted, without repeats, three at a time"
    assert (fair, best) == prices(quotes)
    assert len(fair) == 7 * 2 * 2 and fair[("h24", 7, "CORNERS_OU", D("9.5"), "Over")][0] == pytest.approx(P_PICK)
    assert versus.read_prices(None, fixtures=[], keys=["CORNERS_OU"], since=KNOWN) == ({}, {})  # type: ignore[arg-type]
