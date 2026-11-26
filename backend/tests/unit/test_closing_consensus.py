"""The consensus of the real close (RP-1.4, ``fbi.market.closing_consensus``): pure parts - a consensus needs three books, the minute it stands for is
the median of the books' stamps, an Asian-handicap pair is one book - and the words of the measure."""

from __future__ import annotations

from decimal import Decimal

from fbi.market import closing_consensus as cc
from fbi.market.consensus import BookQuote


def book(bookmaker: int, home: str, draw: str, away: str, minutes: int) -> list[cc.Stamped]:
    return [cc.Stamped(BookQuote(bookmaker, "1X2", sel, Decimal(0), Decimal(odds)), minutes)
            for sel, odds in (("Home", home), ("Draw", draw), ("Away", away))]


def test_three_books_make_a_consensus_and_two_do_not() -> None:
    three = [*book(1, "2.10", "3.40", "3.60", 10), *book(2, "2.05", "3.50", "3.70", 25), *book(3, "2.15", "3.30", "3.50", 55)]
    got = cc.rows(7, three)
    assert {r.method for r in got} == {"shin", "proportional", "power"}
    home = next(r for r in got if r.method == "shin" and r.selection == "Home")
    assert (home.n_bookmakers, home.minutes_to_ko, home.newest_minutes_to_ko, home.fixture_id) == (3, 25, 10, 7)
    assert 0.40 < float(home.p_fair) < 0.52
    assert cc.rows(7, three[:6]) == [], "two books are not a consensus: nothing is stored, nothing is guessed"


def test_the_probabilities_of_a_book_sum_to_one() -> None:
    three = [*book(1, "2.10", "3.40", "3.60", 10), *book(2, "2.05", "3.50", "3.70", 25), *book(3, "2.15", "3.30", "3.50", 55)]
    shin = [r for r in cc.rows(1, three) if r.method == "shin"]
    assert abs(sum(r.p_fair for r in shin) - 1) < Decimal("0.00001")


def test_an_asian_handicap_pair_is_quoted_at_opposite_lines_and_is_one_book() -> None:
    quotes = []
    for b, (h, a, minutes) in enumerate((("1.95", "1.95", 12), ("1.90", "2.00", 20), ("1.97", "1.93", 40)), start=1):
        quotes += [cc.Stamped(BookQuote(b, "AH", "Home", Decimal("-0.5"), Decimal(h)), minutes),
                   cc.Stamped(BookQuote(b, "AH", "Away", Decimal("0.5"), Decimal(a)), minutes)]
    got = [r for r in cc.rows(3, quotes) if r.method == "shin" and r.selection == "Home"]
    assert len(got) == 1 and got[0].n_bookmakers == 3 and got[0].minutes_to_ko == 20


def test_the_real_close_keeps_the_name_of_the_old_one() -> None:
    assert cc.REFERENCE_PRIOR == "last-shin-consensus-before-kickoff", "the reference that was 'the close' keeps its stored name"
    assert cc.REFERENCE != cc.REFERENCE_PRIOR


def test_the_measure_says_in_spanish_whether_it_meets_the_acceptance() -> None:
    doc = {"since": "2026-11-01T00:00:00", "until": "2026-11-26T00:00:00", "matches_with_price": 10, "matches_with_real_close": 10, "within_target": 7,
           "target_minutes": 30, "share_within_target": 0.7, "meets_acceptance": False, "real_median_minutes": 21.0, "prior_median_minutes": 170.0,
           "decisions_with_both": 0, "clv_prior_mean": None, "clv_real_mean": None, "mean_abs_difference": None}
    text = "\n".join(cc.lines(doc))
    assert "no cumple" in text and "70%" in text and "sin dato" in text
