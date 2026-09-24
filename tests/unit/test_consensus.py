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


def test_lines_are_separate_markets_and_ambiguous_markets_are_skipped() -> None:
    quotes = (book(1, "OU", {"Over": "1.90", "Under": "1.95"}, "2.5")
              + book(1, "OU", {"Over": "2.60", "Under": "1.50"}, "3.5")
              + book(1, "DC", {"1X": "1.30", "12": "1.30", "X2": "1.80"})
              + book(1, "AH", {"Home": "1.90", "Away": "1.95"}, "-0.5"))
    rows = consensus(quotes)
    assert {(r.market_key, r.line) for r in rows} == {("OU", D("2.5")), ("OU", D("3.5"))}
    for line in (D("2.5"), D("3.5")):
        assert sum(r.p_fair for r in rows if r.line == line and r.method == "proportional") == pytest.approx(1.0)


def test_a_book_without_margin_is_not_averaged_in() -> None:
    fair_book = book(1, "BTTS", {"Yes": "1.80", "No": "2.00"})
    arbitrage = book(2, "BTTS", {"Yes": "2.10", "No": "2.10"})
    rows = consensus(fair_book + arbitrage)
    assert rows and all(r.n_bookmakers == 1 for r in rows)
    yes = next(r for r in rows if r.selection == "Yes" and r.method == "shin")
    assert yes.best_odds == D("1.80") and yes.best_bookmaker_id == 1, \
        "a book that fails validation is not trusted for the best price either"
