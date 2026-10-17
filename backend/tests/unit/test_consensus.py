"""The live consensus averages de-vigged books and refuses to guess."""

from __future__ import annotations

from decimal import Decimal

import pytest

from fbi.domain.market_probability import DevigMethod, devig
from fbi.domain.odds import DecimalOdds
from fbi.market.consensus import BookQuote, consensus

D = Decimal


def book(bm: int, market: str, prices: dict[str, str], line: str = "0") -> list[BookQuote]:
    return [BookQuote(bm, market, sel, D(line), D(odd)) for sel, odd in prices.items()]


def test_the_consensus_is_the_mean_of_each_book_devigged_on_its_own() -> None:
    a = {"Home": "2.10", "Draw": "3.40", "Away": "3.60"}
    b = {"Home": "2.00", "Draw": "3.50", "Away": "3.90"}
    rows = [r for r in consensus(book(1, "1X2", a) + book(2, "1X2", b)) if r.method == "shin"]
    assert {r.selection for r in rows} == {"Home", "Draw", "Away"}
    fa = devig({k: DecimalOdds(D(v)) for k, v in a.items()}, DevigMethod.SHIN)
    fb = devig({k: DecimalOdds(D(v)) for k, v in b.items()}, DevigMethod.SHIN)
    home = next(r for r in rows if r.selection == "Home")
    assert home.p_fair == pytest.approx((fa["Home"].probability.value + fb["Home"].probability.value) / 2)
    assert sum(r.p_fair for r in rows) == pytest.approx(1.0, abs=1e-9)
    assert home.n_bookmakers == 2 and home.dispersion is not None and home.dispersion > 0
    assert home.best_odds == D("2.10") and home.best_bookmaker_id == 1
    away = next(r for r in rows if r.selection == "Away")
    assert away.best_odds == D("3.90") and away.best_bookmaker_id == 2


def test_an_incomplete_book_is_left_out_not_completed() -> None:
    full = book(1, "1X2", {"Home": "2.10", "Draw": "3.40", "Away": "3.60"})
    partial = book(2, "1X2", {"Home": "1.50", "Draw": "4.00"})
    rows = consensus(full + partial)
    assert all(r.n_bookmakers == 1 for r in rows)
    assert all(r.best_bookmaker_id == 1 for r in rows)


def test_each_line_is_its_own_market() -> None:
    quotes = (book(1, "OU", {"Over": "1.90", "Under": "1.95"}, "2.5")
              + book(1, "OU", {"Over": "2.60", "Under": "1.50"}, "3.5"))
    rows = consensus(quotes)
    assert {(r.market_key, r.line) for r in rows} == {("OU", D("2.5")), ("OU", D("3.5"))}
    for line in (D("2.5"), D("3.5")):
        assert sum(r.p_fair for r in rows if r.line == line and r.method == "proportional") == pytest.approx(1.0)


def test_an_impossible_two_way_book_is_not_a_pair_whatever_its_lines() -> None:
    """The instrument that replaced the sign convention.

    The provider offers several handicap bets per book and their stored lines
    collide: "Home 2.5" at 1.020 sits beside "Away -2.5" at 11.000 AND
    "Away 2.5" at 1.020. The first is the real pair - it devigs to 1.071 - and
    pairing on the sign alone took the second and produced 1.95, a 95% margin
    no bookmaker has. Two near-certainties are never two sides of one bet.
    """
    wrong = (book(1, "AH", {"Home": "1.02"}, "2.5")
             + book(1, "AH", {"Away": "1.03"}, "-2.5"))
    assert consensus(wrong) == [], "a 1.95 book is not a book"


def test_the_believable_partner_is_chosen_when_both_candidates_exist() -> None:
    """Home 2.5 at 1.02 has two candidate partners in the payload. The one that
    makes a real book is taken; the other belongs to a different bet."""
    quotes = (book(1, "AH", {"Home": "1.02"}, "2.5")
              + book(1, "AH", {"Away": "11.00"}, "-2.5")
              + book(1, "AH", {"Away": "1.02"}, "2.5"))
    rows = [r for r in consensus(quotes) if r.method == "shin"]
    assert rows, "the real pair must survive"
    assert {r.selection for r in rows} == {"Home", "Away"}
    away = next(r for r in rows if r.selection == "Away")
    assert away.best_odds == D("11.00"), "paired with the price that makes a book"
    assert sum(r.p_fair for r in rows) == pytest.approx(1.0, abs=1e-9)
    assert rows[0].overround < 1.1


def test_a_pair_at_one_line_is_accepted_when_it_devigs_believably() -> None:
    """The rule is about the overround, not about the sign: if two prices make a
    real two-way book, they are a real pair."""
    rows = consensus(book(1, "AH", {"Home": "1.90", "Away": "1.95"}, "-0.5"))
    assert rows
    for method in ("shin", "proportional", "power"):
        assert sum(r.p_fair for r in rows if r.method == method) == pytest.approx(
            1.0, abs=1e-9
        )


def test_a_handicap_pairs_across_opposite_lines() -> None:
    quotes = (book(1, "AH", {"Home": "1.90"}, "-0.5")
              + book(1, "AH", {"Away": "1.95"}, "0.5"))
    rows = consensus(quotes)
    assert {(r.market_key, r.selection, r.line) for r in rows} == {
        ("AH", "Home", D("-0.5")), ("AH", "Away", D("0.5"))
    }, "each side is stored at the line it was quoted at"
    for method in ("shin", "proportional", "power"):
        total = sum(r.p_fair for r in rows if r.method == method)
        assert total == pytest.approx(1.0, abs=1e-9), method


def test_the_handicap_consensus_is_conditional_on_the_bet_being_settled() -> None:
    """Two numbers summing to 1 cannot also account for a push. On a whole line
    they are P(win | settled), and the consumer divides the model's P(win) by
    (1 - P(push)) before comparing."""
    quotes = (book(1, "AH", {"Home": "1.95"}, "-1")
              + book(1, "AH", {"Away": "1.90"}, "1"))
    rows = consensus(quotes)
    assert rows
    for method in ("shin", "proportional", "power"):
        assert sum(r.p_fair for r in rows if r.method == method) == pytest.approx(
            1.0, abs=1e-9
        )


def test_double_chance_is_de_vigged_through_the_1x2_book_it_implies() -> None:
    """A fair Double Chance book sums to 2, so the three fair probabilities must
    too - and each outcome appears in exactly two of the three."""
    rows = consensus(book(1, "DC", {"1X": "1.30", "12": "1.25", "X2": "1.80"}))
    assert {r.selection for r in rows} == {"1X", "X2", "12"}
    for method in ("shin", "proportional", "power"):
        total = sum(r.p_fair for r in rows if r.method == method)
        assert total == pytest.approx(2.0, abs=1e-9), method


def test_the_implied_double_chance_outcomes_are_a_valid_distribution() -> None:
    """P(home) = 1X + 12 - 1 and its two siblings must each be positive and sum
    to 1, or the transform has gone wrong somewhere."""
    rows = [r for r in consensus(book(1, "DC", {"1X": "1.30", "12": "1.25",
                                                "X2": "1.80"}))
            if r.method == "shin"]
    fair = {r.selection: r.p_fair for r in rows}
    home = fair["1X"] + fair["12"] - 1
    draw = fair["1X"] + fair["X2"] - 1
    away = fair["X2"] + fair["12"] - 1
    assert min(home, draw, away) > 0
    assert home + draw + away == pytest.approx(1.0, abs=1e-9)


def test_an_incoherent_double_chance_book_is_dropped_not_clipped() -> None:
    """P(home) is (1X + 12 - X2) / 2 in raw implied terms, so a book whose X2 is
    shorter than 1X and 12 together implies a NEGATIVE home probability.

    X2 at 1.02 against 1X at 3.00 and 12 at 4.00 is such a book: 0.980 > 0.333 +
    0.250. Clipping it to zero would turn a broken quote into a confident
    number, which is the failure the whole module is built to avoid, so the book
    is left out and the sound one stands alone.
    """
    broken = book(1, "DC", {"1X": "3.00", "X2": "1.02", "12": "4.00"})
    good = book(2, "DC", {"1X": "1.30", "12": "1.25", "X2": "1.80"})
    rows = consensus(broken + good)
    assert rows and all(r.n_bookmakers == 1 for r in rows), (
        "only the coherent book was averaged in"
    )
    for method in ("shin", "proportional", "power"):
        assert sum(r.p_fair for r in rows if r.method == method) == pytest.approx(
            2.0, abs=1e-9
        )


def test_an_incomplete_double_chance_book_is_left_out() -> None:
    assert consensus(book(1, "DC", {"1X": "1.30", "12": "1.25"})) == []


def test_a_book_without_margin_is_not_averaged_in() -> None:
    fair_book = book(1, "BTTS", {"Yes": "1.80", "No": "2.00"})
    arbitrage = book(2, "BTTS", {"Yes": "2.10", "No": "2.10"})
    rows = consensus(fair_book + arbitrage)
    assert rows and all(r.n_bookmakers == 1 for r in rows)
    yes = next(r for r in rows if r.selection == "Yes" and r.method == "shin")
    assert yes.best_odds == D("1.80") and yes.best_bookmaker_id == 1, \
        "a book that fails validation is not trusted for the best price either"
