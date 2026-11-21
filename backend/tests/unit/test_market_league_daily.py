"""PM-05-07: the market's margin and dispersion by competition, market and day (``fbi.market.league_daily``) - the pure measures,
recomputed by hand (exact fractions) on 20 matches, the books left out, the days a pass measures and the switch born off."""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction

import pytest

from fbi.market import league_daily as ld

DAY = date(2026, 11, 15)
PRICES_1X2 = [  # 20 matches, three houses each: (home, draw, away)
    [("2.10", "3.40", "3.60"), ("2.05", "3.30", "3.75"), ("2.15", "3.25", "3.50")],
    [("1.50", "4.20", "6.50"), ("1.48", "4.33", "6.00"), ("1.53", "4.00", "6.25")],
    [("3.10", "3.20", "2.40"), ("3.00", "3.25", "2.45"), ("3.20", "3.10", "2.35")],
    [("1.25", "6.00", "11.0"), ("1.22", "6.50", "12.0"), ("1.28", "5.75", "10.0")],
    [("2.60", "3.10", "2.90"), ("2.55", "3.20", "2.85"), ("2.70", "3.00", "2.80")],
    [("1.90", "3.50", "4.20"), ("1.87", "3.60", "4.33"), ("1.95", "3.40", "4.00")],
    [("4.50", "3.60", "1.80"), ("4.33", "3.75", "1.83"), ("4.75", "3.50", "1.78")],
    [("2.30", "3.30", "3.20"), ("2.25", "3.40", "3.25"), ("2.35", "3.20", "3.10")],
    [("1.70", "3.80", "5.00"), ("1.67", "3.90", "5.25"), ("1.72", "3.75", "4.80")],
    [("2.00", "3.40", "3.90"), ("1.95", "3.50", "4.00"), ("2.05", "3.30", "3.80")],
    [("3.60", "3.40", "2.10"), ("3.50", "3.50", "2.15"), ("3.75", "3.30", "2.05")],
    [("1.40", "4.75", "8.00"), ("1.38", "5.00", "8.50"), ("1.42", "4.60", "7.50")],
    [("2.80", "3.00", "2.75"), ("2.75", "3.10", "2.70"), ("2.90", "2.95", "2.65")],
    [("1.80", "3.60", "4.60"), ("1.83", "3.50", "4.50"), ("1.78", "3.75", "4.75")],
    [("5.50", "4.00", "1.60"), ("5.25", "4.20", "1.62"), ("6.00", "3.90", "1.57")],
    [("2.45", "3.20", "3.00"), ("2.40", "3.30", "3.05"), ("2.50", "3.10", "2.95")],
    [("1.60", "4.00", "5.75"), ("1.57", "4.20", "6.00"), ("1.62", "3.90", "5.50")],
    [("2.20", "3.30", "3.40"), ("2.15", "3.40", "3.50"), ("2.25", "3.25", "3.30")],
    [("3.30", "3.30", "2.25"), ("3.25", "3.40", "2.30"), ("3.40", "3.20", "2.20")],
    [("1.33", "5.25", "9.00"), ("1.30", "5.50", "10.0"), ("1.36", "5.00", "8.50")],
]
SEL = ("Home", "Draw", "Away")


def prices() -> list[ld.Price]:
    out = []
    for f, books in enumerate(PRICES_1X2):
        for b, book in enumerate(books):
            for s, odd in zip(SEL, book, strict=True):
                out.append(ld.Price(fixture_id=100 + f, competition_id=7, day=DAY, bookmaker_id=b + 1, market_key="1X2",
                                    line=Decimal("0"), selection=s, odds=Decimal(odd)))
    return out


def hand_margin(book: tuple[str, ...]) -> Fraction:
    return sum((1 / Fraction(o) for o in book), Fraction(0)) - 1


def hand_percentile(values: list[Fraction], q: Fraction) -> Fraction:
    v = sorted(values)
    pos = q * (len(v) - 1)
    low = int(pos)
    high = min(low + 1, len(v) - 1)
    return v[low] + (v[high] - v[low]) * (pos - low)


def test_the_margins_of_20_matches_match_the_hand_computation() -> None:
    summary = ld.summarise(prices())
    assert summary.rejected == 0
    (row,) = summary.stats
    hand = [hand_margin(book) for books in PRICES_1X2 for book in books]
    assert (row.day, row.competition_id, row.market_key, row.line) == (DAY, 7, "1X2", Decimal("0"))
    assert (row.n_fixtures, row.n_books, row.books_median) == (20, 60, 3.0)
    assert row.margin_mean == pytest.approx(float(sum(hand) / len(hand)), abs=1e-12)
    assert row.margin_median == pytest.approx(float(hand_percentile(hand, Fraction(1, 2))), abs=1e-12)
    assert row.margin_p10 == pytest.approx(float(hand_percentile(hand, Fraction(1, 10))), abs=1e-12)
    assert row.margin_p90 == pytest.approx(float(hand_percentile(hand, Fraction(9, 10))), abs=1e-12)
    # one match by hand: 1/2.10 + 1/3.40 + 1/3.60 - 1
    assert float(hand_margin(PRICES_1X2[0][0])) == pytest.approx(1 / 2.10 + 1 / 3.40 + 1 / 3.60 - 1, abs=1e-12)


def test_the_dispersion_is_the_spread_of_the_fair_probabilities_across_houses() -> None:
    (row,) = ld.summarise(prices()).stats
    per_match = []
    for books in PRICES_1X2:
        fairs = []
        for book in books:
            implied = [1 / float(o) for o in book]
            fairs.append([p / sum(implied) for p in implied])
        per_match.append(statistics.fmean(statistics.pstdev([f[i] for f in fairs]) for i in range(3)))
    assert row.n_dispersion == 20
    assert row.dispersion_mean == pytest.approx(statistics.fmean(per_match), abs=1e-12)
    assert row.dispersion_median == pytest.approx(statistics.median(per_match), abs=1e-12)


def test_incomplete_and_unbelievable_books_are_left_out_never_guessed() -> None:
    def p(f: int, b: int, market: str, line: str, sel: str, odd: str) -> ld.Price:
        return ld.Price(fixture_id=f, competition_id=9, day=DAY, bookmaker_id=b, market_key=market, line=Decimal(line), selection=sel,
                        odds=Decimal(odd))

    rows = [
        p(1, 1, "OU", "2.5", "Over", "1.90"), p(1, 1, "OU", "2.5", "Under", "1.90"),   # margin 5.26 %
        p(1, 2, "OU", "2.5", "Over", "1.95"),                                           # incomplete: left out
        p(1, 3, "OU", "2.5", "Over", "2.10"), p(1, 3, "OU", "2.5", "Under", "2.05"),   # no margin (stale): left out
        p(1, 4, "OU", "2.5", "Over", "1.40"), p(1, 4, "OU", "2.5", "Under", "1.40"),   # 42.9 %: two different bets, left out
        p(1, 5, "OU", "3.5", "Over", "2.80"), p(1, 5, "OU", "3.5", "Under", "1.40"),   # another line: not read
        p(1, 6, "DC", "0", "1X", "1.30"),                                               # another market: not read
    ]
    summary = ld.summarise(rows)
    assert summary.rejected == 3
    (row,) = summary.stats
    assert (row.market_key, row.line, row.n_fixtures, row.n_books) == ("OU", Decimal("2.5"), 1, 1)
    assert row.margin_median == pytest.approx(2 / 1.90 - 1)
    assert row.margin_p10 == row.margin_median == row.margin_p90
    assert (row.dispersion_median, row.dispersion_mean, row.n_dispersion) == (None, None, 0)


def test_a_day_with_no_complete_book_writes_no_row() -> None:
    rows = [ld.Price(1, 9, DAY, 1, "BTTS", Decimal("0"), "Yes", Decimal("1.80"))]
    summary = ld.summarise(rows)
    assert summary.stats == [] and summary.rejected == 1


def test_percentile_is_postgresql_percentile_cont() -> None:
    assert ld.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert ld.percentile([1.0, 2.0, 3.0, 4.0], 0.1) == pytest.approx(1.3)
    assert ld.percentile([5.0], 0.9) == 5.0
    with pytest.raises(ValueError):
        ld.percentile([], 0.5)


def test_the_days_due_are_the_recent_week_then_the_oldest_missing() -> None:
    today = date(2026, 11, 21)
    due = ld.days_due(today, [])
    assert due[: ld.RECENT_DAYS] == [today - timedelta(days=n) for n in range(1, ld.RECENT_DAYS + 1)]
    assert due[ld.RECENT_DAYS] == ld.WINDOW_START
    assert today not in due and len(due) == min(ld.MAX_DAYS, (today - ld.WINDOW_START).days)
    assert len(ld.days_due(date(2027, 3, 1), [])) == ld.MAX_DAYS
    everything = [ld.WINDOW_START + timedelta(days=n) for n in range((today - ld.WINDOW_START).days)]
    assert ld.days_due(today, everything) == due[: ld.RECENT_DAYS]
    assert ld.days_due(ld.WINDOW_START, []) == []


def test_the_switch_is_born_off() -> None:
    assert ld.mode({}) == "off"
    assert ld.mode({ld.SWITCH: "0"}) == "off"
    assert ld.mode({ld.SWITCH: "1"}) == "on"
    assert ld.mode({ld.SWITCH: "on"}) == "on"


def test_the_markets_are_the_exclusive_ones_of_the_consensus() -> None:
    from fbi.market.consensus import EXCLUSIVE, MAX_TWO_WAY_BOOK

    assert {m: sels for m, _, sels in ld.MARKETS} == EXCLUSIVE
    assert ld.MAX_TWO_WAY_BOOK == MAX_TWO_WAY_BOOK


def test_nothing_of_the_module_reaches_a_probability_or_a_pick() -> None:
    import ast
    from pathlib import Path

    tree = ast.parse(Path(ld.__file__).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not [m for m in imported if m.startswith("fbi.")], imported
    sql = (ld.PRICES_SQL + ld.UPSERT_SQL + ld.MEASURED_SQL + ld.READ_SQL).lower()
    for word in ("picks.", "models.", "predictions", "features."):
        assert word not in sql
