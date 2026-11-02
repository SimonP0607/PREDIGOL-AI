"""The bets on ONE count, derived from its distribution (plan F10). Every derivation is held to a closed form (Poisson counts have one) or to a
brute-force sum over the two counts: the goals of each side in a half stand for any count here."""

from __future__ import annotations

import itertools
import math

import pytest

from fbi.families import derive
from fbi.families.counts import MAX_COUNT
from fbi.families.fit import NO_DISPERSION, Dispersion, Prediction, prediction

FIRST = (0.55, 0.40)
SECOND = (0.70, 0.55)


def _poisson(mu: float, k: int) -> float:
    return math.exp(-mu) * mu**k / math.factorial(k)


def _pred(means: tuple[float, float], d: Dispersion = NO_DISPERSION) -> Prediction:
    return prediction(means[0], means[1], d)


def test_split_line_whole_half_and_quarter_lines() -> None:
    assert derive.split_line(1.5) == ((1.5, 1.0),)
    assert derive.split_line(2.0) == ((2.0, 1.0),)
    assert derive.split_line(0.0) == ((0.0, 1.0),)
    assert derive.split_line(2.25) == ((2.0, 0.5), (2.5, 0.5))
    assert derive.split_line(2.75) == ((2.5, 0.5), (3.0, 0.5))
    assert derive.split_line(-0.25) == ((-0.5, 0.5), (0.0, 0.5))
    assert derive.split_line(-0.75) == ((-1.0, 0.5), (-0.5, 0.5))


def test_the_total_of_a_poisson_half_over_a_half_line_has_a_closed_form() -> None:
    pred = _pred(FIRST)
    lam = sum(FIRST)
    assert derive.count_line(pred.pmf_total, 0.5).over == pytest.approx(1 - math.exp(-lam), abs=1e-12)
    assert derive.count_line(pred.pmf_total, 1.5).over == pytest.approx(1 - _poisson(lam, 0) - _poisson(lam, 1), abs=1e-12)
    one_side = derive.count_line(pred.pmf_home, 0.5)
    assert one_side.over == pytest.approx(1 - math.exp(-FIRST[0]), abs=1e-12) and one_side.push == 0.0


def test_a_whole_line_returns_the_stake_when_it_lands_on_it() -> None:
    pred = _pred(SECOND)
    lam = sum(SECOND)
    line = derive.count_line(pred.pmf_total, 1.0)
    assert line.push == pytest.approx(_poisson(lam, 1), abs=1e-12)
    assert line.over + line.push + line.under == pytest.approx(1.0, abs=1e-12)


def test_a_quarter_line_is_half_a_stake_on_each_neighbour() -> None:
    pred = _pred(SECOND)
    lam = sum(SECOND)
    p0, p1, p2 = (_poisson(lam, k) for k in range(3))
    # 1.25 = half on 1.0 (push at 1) and half on 1.5: wins at 2+, half-loses at 1, loses at 0
    q125 = derive.count_line(pred.pmf_total, 1.25)
    assert q125.over == pytest.approx(1 - p0 - p1, abs=1e-12)
    assert q125.push == pytest.approx(0.5 * p1, abs=1e-12)
    assert q125.under == pytest.approx(p0 + 0.5 * p1, abs=1e-12)
    # 1.75 = half on 1.5 and half on 2.0 (push at 2): wins at 3+, half-wins at 2, loses at 0-1
    q175 = derive.count_line(pred.pmf_total, 1.75)
    assert q175.over == pytest.approx(0.5 * (1 - p0 - p1) + 0.5 * (1 - p0 - p1 - p2), abs=1e-12)
    assert q175.push == pytest.approx(0.5 * p2, abs=1e-12)
    assert q175.under == pytest.approx(p0 + p1, abs=1e-12)
    for line in (q125, q175):
        assert line.over + line.push + line.under == pytest.approx(1.0, abs=1e-12)


def test_both_teams_score_and_odd_goals_have_exact_poisson_forms() -> None:
    pred = _pred(FIRST)
    assert derive.both_score(pred) == pytest.approx((1 - math.exp(-FIRST[0])) * (1 - math.exp(-FIRST[1])), abs=1e-12)
    # P(odd) of a Poisson(lam) is (1 - exp(-2 lam)) / 2
    assert derive.odd_total(pred) == pytest.approx((1 - math.exp(-2 * sum(FIRST))) / 2, abs=1e-12)


def test_the_result_of_a_half_is_the_sum_over_its_scores() -> None:
    pred = _pred(FIRST)
    home = away = level = 0.0
    for i, j in itertools.product(range(MAX_COUNT + 1), repeat=2):
        p = float(pred.pmf_home[i]) * float(pred.pmf_away[j])
        if i > j:
            home += p
        elif i == j:
            level += p
        else:
            away += p
    got = derive.result(pred)
    assert got == pytest.approx((home, level, away), abs=1e-12)
    assert sum(got) == pytest.approx(1.0, abs=1e-12)


def test_draw_no_bet_and_double_chance_follow_from_the_result() -> None:
    pred = _pred(SECOND)
    h, x, a = derive.result(pred)
    dnb_h, dnb_a = derive.draw_no_bet(pred)
    assert dnb_h == pytest.approx(h / (h + a)) and dnb_a == pytest.approx(a / (h + a)) and dnb_h + dnb_a == pytest.approx(1.0)
    assert derive.double_chance(pred) == pytest.approx((h + x, x + a, h + a))


def test_a_handicap_of_zero_is_the_result_and_a_quarter_handicap_splits_the_draw() -> None:
    pred = _pred(FIRST)
    h, x, a = derive.result(pred)
    zero = derive.asian_handicap(pred, 0.0)
    assert (zero.over, zero.push, zero.under) == pytest.approx((h, x, a), abs=1e-12)
    # -0.25 = half on 0 and half on -0.5: the home side wins when it leads, half-loses on a draw
    q = derive.asian_handicap(pred, -0.25)
    assert q.over == pytest.approx(h, abs=1e-12)
    assert q.push == pytest.approx(0.5 * x, abs=1e-12)
    assert q.under == pytest.approx(a + 0.5 * x, abs=1e-12)
    # +0.5 for the home side wins on a draw too
    plus = derive.asian_handicap(pred, 0.5)
    assert plus.over == pytest.approx(h + x, abs=1e-12) and plus.push == 0.0
