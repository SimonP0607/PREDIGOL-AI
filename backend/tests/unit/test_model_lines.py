"""Every line priced from the score matrix, checked against arithmetic that can
be done by hand.

A model's own output cannot be its own test. Most cases here use a matrix whose
probabilities are written out explicitly, so the expected answer is a sum of a
few named numbers rather than whatever the code happens to produce.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest

from fbi.models.lines import (
    LineOutcome,
    asian_handicap,
    double_chance,
    fair_odds,
    margin_distribution,
    over_under,
    quarter_legs,
    total_distribution,
)
from fbi.models.scoring import dc_tau, from_matrix, poisson_matrix


def hand_matrix() -> np.ndarray:
    """A 3x3 distribution written out, so every expectation below is checkable.

    rows = home goals, columns = away goals

            0-0 .20   0-1 .10   0-2 .05
            1-0 .15   1-1 .12   1-2 .03
            2-0 .10   2-1 .13   2-2 .12
    """
    return np.array(
        [[0.20, 0.10, 0.05],
         [0.15, 0.12, 0.03],
         [0.10, 0.13, 0.12]],
        dtype=np.float64,
    )


def real_matrix(lh: float = 1.45, la: float = 1.15, rho: float = -0.03) -> np.ndarray:
    return dc_tau(poisson_matrix(lh, la), lh, la, rho)


# --- the projections --------------------------------------------------------


def test_the_margin_distribution_is_read_off_the_diagonals() -> None:
    d = margin_distribution(hand_matrix())
    assert d[0] == pytest.approx(0.20 + 0.12 + 0.12)   # 0-0, 1-1, 2-2
    assert d[1] == pytest.approx(0.15 + 0.13)          # 1-0, 2-1
    assert d[2] == pytest.approx(0.10)                 # 2-0
    assert d[-1] == pytest.approx(0.10 + 0.03)         # 0-1, 1-2
    assert d[-2] == pytest.approx(0.05)                # 0-2
    assert sum(d.values()) == pytest.approx(1.0)


def test_the_total_distribution_is_read_off_the_anti_diagonals() -> None:
    d = total_distribution(hand_matrix())
    assert d[0] == pytest.approx(0.20)
    assert d[1] == pytest.approx(0.10 + 0.15)
    assert d[2] == pytest.approx(0.05 + 0.12 + 0.10)
    assert d[3] == pytest.approx(0.03 + 0.13)
    assert d[4] == pytest.approx(0.12)
    assert sum(d.values()) == pytest.approx(1.0)


def test_both_projections_agree_with_the_1x2_the_model_already_reports() -> None:
    """The same matrix must not give two different answers to one question."""
    m = real_matrix()
    probs = from_matrix(m, 1.45, 1.15)
    margins = margin_distribution(m)
    home = sum(p for k, p in margins.items() if k > 0)
    draw = margins[0]
    away = sum(p for k, p in margins.items() if k < 0)
    assert home == pytest.approx(probs.home, abs=1e-12)
    assert draw == pytest.approx(probs.draw, abs=1e-12)
    assert away == pytest.approx(probs.away, abs=1e-12)


# --- double chance ----------------------------------------------------------


def test_double_chance_is_three_additions_and_nothing_else() -> None:
    """1,444 stored prices had no model number to compare against for want of
    these three sums."""
    m = real_matrix()
    probs = from_matrix(m, 1.45, 1.15)
    dc = double_chance(m)
    assert dc["1X"] == pytest.approx(probs.home + probs.draw, abs=1e-12)
    assert dc["X2"] == pytest.approx(probs.draw + probs.away, abs=1e-12)
    assert dc["12"] == pytest.approx(probs.home + probs.away, abs=1e-12)


def test_the_three_double_chance_prices_sum_to_two() -> None:
    """Each outcome appears in exactly two of the three, so the total is 2 -
    the invariant that catches a mis-assembled Double Chance."""
    dc = double_chance(real_matrix())
    assert sum(dc.values()) == pytest.approx(2.0, abs=1e-9)


# --- over/under, at every line ---------------------------------------------


def test_over_under_reproduces_the_single_line_the_model_used_to_price() -> None:
    m = real_matrix()
    probs = from_matrix(m, 1.45, 1.15)
    over = over_under(m, selection="over", line=Decimal("2.5"))
    assert over.win == pytest.approx(probs.over_2_5, abs=1e-12)
    assert over.push == 0.0, "a half line cannot push"


def test_a_half_line_is_a_clean_two_way_bet() -> None:
    m = hand_matrix()
    over = over_under(m, selection="over", line=Decimal("2.5"))
    under = over_under(m, selection="under", line=Decimal("2.5"))
    assert over.win == pytest.approx(0.03 + 0.13 + 0.12)   # totals 3 and 4
    assert under.win == pytest.approx(1 - (0.03 + 0.13 + 0.12))
    assert over.push == under.push == 0.0
    assert over.win + under.win == pytest.approx(1.0)


def test_a_whole_line_pushes_on_exactly_that_many_goals() -> None:
    """Over 3.0 with exactly three goals returns the stake. 1,817 stored
    Over/Under rows are on whole lines; treating them as two-way bets would
    misprice every one."""
    m = hand_matrix()
    over = over_under(m, selection="over", line=Decimal("3"))
    under = over_under(m, selection="under", line=Decimal("3"))
    three = 0.03 + 0.13
    assert over.push == pytest.approx(three)
    assert under.push == pytest.approx(three)
    assert over.win == pytest.approx(0.12)                       # total 4
    assert under.win == pytest.approx(0.20 + 0.25 + 0.27)        # totals 0,1,2
    assert over.win + over.push + over.lose == pytest.approx(1.0)


def test_every_captured_over_under_line_is_priceable() -> None:
    """26 distinct lines are stored, from 0.5 to 9.5, and the model priced one."""
    m = real_matrix()
    lines = ["0.50", "0.75", "1.00", "1.25", "1.50", "1.75", "2.00", "2.25",
             "2.50", "2.75", "3.00", "3.25", "3.50", "3.75", "4.00", "4.25",
             "4.50", "4.75", "5.00", "5.25", "5.50", "6.00", "6.50", "7.50",
             "8.50", "9.50"]
    for text in lines:
        line = Decimal(text)
        over = over_under(m, selection="over", line=line)
        under = over_under(m, selection="under", line=line)
        assert 0 <= over.win <= 1, text
        assert over.win + over.push + under.win == pytest.approx(1.0, abs=1e-9), text


def test_the_over_probability_falls_as_the_line_rises() -> None:
    m = real_matrix()
    probs = [over_under(m, selection="over", line=Decimal(str(x))).win
             for x in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5)]
    assert probs == sorted(probs, reverse=True)


# --- asian handicap --------------------------------------------------------


def test_a_level_handicap_is_the_match_without_the_draw() -> None:
    """AH 0.0 pushes on a draw, so its two sides are the 1X2 home and away."""
    m = hand_matrix()
    home = asian_handicap(m, selection="home", line=Decimal(0))
    away = asian_handicap(m, selection="away", line=Decimal(0))
    draw = 0.20 + 0.12 + 0.12
    assert home.push == pytest.approx(draw)
    assert away.push == pytest.approx(draw)
    assert home.win == pytest.approx(0.15 + 0.13 + 0.10)
    assert away.win == pytest.approx(0.10 + 0.03 + 0.05)
    assert home.win + away.win + draw == pytest.approx(1.0)


def test_the_line_applies_to_the_selection_it_is_stored_against() -> None:
    """The convention the whole system stores, settled by devigging real pairs:
    read this way they produce 1.090, read as a per-side signed handicap the
    same pairs produce 0.47, which is impossible."""
    m = hand_matrix()
    # Home -1: home must win by two or more.
    home = asian_handicap(m, selection="home", line=Decimal("-1"))
    assert home.win == pytest.approx(0.10)                  # margin +2
    assert home.push == pytest.approx(0.15 + 0.13)          # margin +1
    # Away +1: away loses by at most nothing, i.e. draw or better, plus a push
    # when it loses by exactly one.
    away = asian_handicap(m, selection="away", line=Decimal("1"))
    assert away.win == pytest.approx(0.20 + 0.12 + 0.12 + 0.10 + 0.03 + 0.05)
    assert away.push == pytest.approx(0.15 + 0.13)


def test_the_two_sides_of_a_pair_account_for_everything() -> None:
    m = real_matrix()
    for text in ("-2.5", "-1.5", "-1", "-0.5", "0", "0.5", "1", "1.5", "2.5"):
        line = Decimal(text)
        home = asian_handicap(m, selection="home", line=line)
        away = asian_handicap(m, selection="away", line=-line)
        assert home.win + home.push + away.win == pytest.approx(1.0, abs=1e-9), text
        assert home.push == pytest.approx(away.push, abs=1e-12), text


def test_a_bigger_handicap_against_a_team_lowers_its_chance() -> None:
    m = real_matrix()
    probs = [asian_handicap(m, selection="home", line=Decimal(str(x))).win
             for x in (1.5, 0.5, -0.5, -1.5, -2.5)]
    assert probs == sorted(probs, reverse=True)


def test_an_unknown_side_is_refused_rather_than_guessed() -> None:
    m = real_matrix()
    with pytest.raises(ValueError, match="home and an away side"):
        asian_handicap(m, selection="Draw", line=Decimal(0))
    with pytest.raises(ValueError, match="over and an under side"):
        over_under(m, selection="Yes", line=Decimal("2.5"))


# --- quarter lines ---------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "legs"),
    [("-0.25", ("-0.50", "0.00")), ("0.25", ("0.00", "0.50")),
     ("-0.75", ("-1.00", "-0.50")), ("1.75", ("1.50", "2.00"))],
)
def test_a_quarter_line_splits_into_its_two_half_stakes(
    line: str, legs: tuple[str, str]
) -> None:
    got = quarter_legs(Decimal(line))
    assert got is not None
    assert (str(got[0]), str(got[1])) == legs


@pytest.mark.parametrize("line", ["0", "0.50", "-1.50", "3", "-2"])
def test_a_whole_or_half_line_is_not_a_split(line: str) -> None:
    assert quarter_legs(Decimal(line)) is None


def test_a_quarter_lines_numbers_reproduce_the_split_bets_expected_value() -> None:
    """The algebra the module documents, checked numerically: the averaged pair
    gives the same EV as settling the two half-stakes separately, at any price.

    4,309 of our stored Asian Handicap rows are on quarter lines - 44% of the
    series - so this is the case that decides whether the series is usable.
    """
    m = real_matrix()
    line = Decimal("-0.75")
    legs = quarter_legs(line)
    assert legs is not None
    a, b = (asian_handicap(m, selection="home", line=x) for x in legs)
    combined = asian_handicap(m, selection="home", line=line)

    for price in (Decimal("1.80"), Decimal("2.05"), Decimal("3.40")):
        def ev(o: LineOutcome, d: Decimal = price) -> float:
            return o.win * float(d - 1) - o.lose

        assert ev(combined) == pytest.approx((ev(a) + ev(b)) / 2, abs=1e-12)


def test_a_quarter_line_carries_half_the_whole_legs_push() -> None:
    m = real_matrix()
    whole = asian_handicap(m, selection="home", line=Decimal("-1"))
    quarter = asian_handicap(m, selection="home", line=Decimal("-0.75"))
    assert quarter.push == pytest.approx(whole.push / 2, abs=1e-12)


# --- the fair price --------------------------------------------------------


def test_a_two_way_bets_fair_price_is_the_reciprocal() -> None:
    assert fair_odds(LineOutcome(0.5, 0.0)) == pytest.approx(Decimal(2))
    assert fair_odds(LineOutcome(0.25, 0.0)) == pytest.approx(Decimal(4))


def test_a_push_shortens_the_fair_price() -> None:
    """A push returns the stake, so it is not a loss the price has to cover.
    Pricing a pushable line as if 1/win were fair overstates the edge on every
    whole and quarter line we quote - 66% of the Asian Handicap series.
    """
    no_push = fair_odds(LineOutcome(0.40, 0.00))
    with_push = fair_odds(LineOutcome(0.40, 0.20))
    assert no_push is not None and with_push is not None
    assert with_push < no_push
    assert with_push == pytest.approx(Decimal("2.0"))   # (1-0.2)/0.4
    assert no_push == pytest.approx(Decimal("2.5"))     # 1/0.4


def test_the_fair_price_is_the_reciprocal_of_the_conditional_win() -> None:
    o = LineOutcome(0.40, 0.20)
    fair = fair_odds(o)
    assert fair is not None
    assert float(fair) == pytest.approx(1.0 / o.conditional_win)


def test_a_bet_that_cannot_win_has_no_fair_price_rather_than_infinity() -> None:
    assert fair_odds(LineOutcome(0.0, 0.30)) is None


def test_a_certain_push_leaves_nothing_at_risk() -> None:
    o = LineOutcome(0.0, 1.0)
    assert o.lose == 0.0
    assert o.conditional_win == 0.0
