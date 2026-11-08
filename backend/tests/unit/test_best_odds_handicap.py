"""The Cuotas board pairs an Asian handicap's two sides as one bet (plan Cuotas, ola 0, E1; ``fbi.api.services.product``).

The consensus stores each side of a handicap bet at the line it is quoted at (``fbi.market.consensus``): one bet is Home at h
with Away at -h. The board grouped the prices by the stored line, so a row put Home at h beside Away at h - the away side of the
OTHER bet. In production, fixture 7819 showed Home -0.25 at 1.67 beside Away -0.25 at 3.48: two prices whose fair probabilities
sum to 0.85, not the two faces of anything. Grouped by pair, a row is Home at h with Away at -h, their fair probabilities summing
to 1; the market's line is the home side's, and a highlight names its selection at its own line.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.api.services import product

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)


def row(selection: str, line: str, odds: str, p_fair: str, *, market: str = "AH", books: int = 6) -> dict[str, Any]:
    """One newest-consensus row of ``BEST_PRICES``, with the badges a board needs."""
    return {
        "fixture_id": 7819, "market_key": market, "selection": selection, "line": Decimal(line),
        "p_fair": Decimal(p_fair), "best_odds": Decimal(odds), "n_bookmakers": books, "as_of": NOW - timedelta(minutes=40),
        "bookmaker": "Pinnacle", "kickoff_at": NOW + timedelta(hours=5), "home_team_id": 51, "home_name": "Brighton",
        "home_logo": None, "away_team_id": 55, "away_name": "Brentford", "away_logo": None, "competition_id": 39,
        "competition_name": "Premier League", "competition_country": "England", "competition_logo": None,
        "competition_flag": None,
    }


# Fixture 7819 as the consensus stores it: five bets, each a home side at h and an away side at -h. Home -0.25 at 1.67 is a
# bet with Away +0.25; Away -0.25 at 3.48 is a bet with Home +0.25. The bet at -0.25 is the most widely quoted.
FIXTURE_7819 = [
    row("Home", "-0.75", "2.10", "0.465"), row("Away", "0.75", "1.80", "0.535"),
    row("Home", "-0.50", "1.95", "0.497"), row("Away", "0.50", "1.92", "0.503"),
    row("Home", "-0.25", "1.67", "0.585", books=8), row("Away", "0.25", "2.45", "0.415", books=8),
    row("Home", "0.00", "1.45", "0.672"), row("Away", "0.00", "2.80", "0.328"),
    row("Home", "0.25", "1.32", "0.735"), row("Away", "-0.25", "3.48", "0.265"),
]


def pairs(rows: list[dict[str, Any]]) -> dict[Decimal, list[dict[str, Any]]]:
    grouped: dict[Decimal, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[product.pair_line(r["market_key"], r["selection"], r["line"])].append(r)
    return grouped


def test_each_handicap_row_is_one_bet_home_at_h_beside_away_at_minus_h() -> None:
    grouped = pairs(FIXTURE_7819)
    assert sorted(grouped) == [Decimal(x) for x in ("-0.75", "-0.5", "-0.25", "0", "0.25")]
    for h, rows in grouped.items():
        assert {r["selection"]: r["line"] for r in rows} == {"Home": h, "Away": -h}, h
        # the two faces of one bet: their fair probabilities sum to 1
        assert sum(r["p_fair"] for r in rows) == pytest.approx(Decimal(1), abs=Decimal("0.001")), h


def test_grouped_by_the_stored_line_the_sides_were_two_different_bets() -> None:
    """What the board did before: the stored line -0.25 held Home -0.25 (1.67) and Away -0.25 (3.48) - 0.585 + 0.265."""
    by_stored: dict[Decimal, list[dict[str, Any]]] = defaultdict(list)
    for r in FIXTURE_7819:
        by_stored[r["line"]].append(r)
    wrong = by_stored[Decimal("-0.25")]
    assert {(r["selection"], r["best_odds"]) for r in wrong} == {("Home", Decimal("1.67")), ("Away", Decimal("3.48"))}
    assert sum(r["p_fair"] for r in wrong) == Decimal("0.850"), "no bet: two sides of two bets"


def test_fixture_7819_shows_home_minus_a_quarter_beside_its_away_plus_a_quarter() -> None:
    fixtures, highlights = product.best_odds(FIXTURE_7819, moment=NOW)
    [ah] = fixtures[0].markets
    assert ah.market_key == "AH" and ah.line == Decimal("-0.25"), "the market's line is the home side's"
    prices = {p.selection: p for p in ah.selections}
    assert (prices["Home"].best_odds, prices["Away"].best_odds) == (Decimal("1.67"), Decimal("2.45"))
    assert Decimal("3.48") not in {p.best_odds for p in ah.selections}, "Away -0.25 belongs to the bet at +0.25"
    assert prices["Home"].p_fair + prices["Away"].p_fair == Decimal("1.000")
    # Away +0.25 pays above fair (2.45 x 0.415 = 1.017): the highlight names it at its own line, +0.25
    [h] = highlights
    assert (h.market_key, h.price.selection, h.line) == ("AH", "Away", Decimal("0.25"))
    assert h.price.price_edge == Decimal("0.0168")


def test_the_main_handicap_line_is_the_most_balanced_bet() -> None:
    """``main_line`` weighs pairs: Home -0.25 / Away +0.25 (49 / 51) is the even bet. Weighed by the stored line, the level
    line (56 / 44) won, because -0.25 and +0.25 each held one side of two lopsided bets (49 with 38, 62 with 51)."""
    rows = [
        row("Home", "-0.25", "1.98", "0.49"), row("Away", "0.25", "1.90", "0.51"),
        row("Home", "0.00", "1.74", "0.56"), row("Away", "0.00", "2.20", "0.44"),
        row("Home", "0.25", "1.57", "0.62"), row("Away", "-0.25", "2.55", "0.38"),
    ]
    assert product.main_line("AH", pairs(rows)) == Decimal("-0.25")
    by_stored: dict[Decimal, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_stored[r["line"]].append(r)
    assert product.main_line("AH", by_stored) == Decimal("0"), "the old grouping chose the level line"
    fixtures, _ = product.best_odds(rows, moment=NOW)
    [ah] = fixtures[0].markets
    assert ah.line == Decimal("-0.25")
    assert {p.selection: p.best_odds for p in ah.selections} == {"Home": Decimal("1.98"), "Away": Decimal("1.90")}


def test_only_the_handicaps_away_side_moves_and_a_level_line_stays_zero() -> None:
    assert product.pair_line("AH", "Away", Decimal("-0.25")) == Decimal("0.25")
    assert product.pair_line("AH", "Home", Decimal("-0.25")) == Decimal("-0.25")
    assert str(product.pair_line("AH", "Away", Decimal("0.00"))) == "0.00", "never a negative zero"
    assert product.pair_line("OU", "Under", Decimal("2.5")) == Decimal("2.5")
    assert product.pair_line("1X2", "Away", Decimal("0")) == Decimal("0")
    fixtures, _ = product.best_odds([row("Over", "2.50", "1.90", "0.52", market="OU"),
                                     row("Under", "2.50", "1.95", "0.48", market="OU")], moment=NOW)
    [ou] = fixtures[0].markets
    assert ou.line == Decimal("2.5") and {p.selection for p in ou.selections} == {"Over", "Under"}
