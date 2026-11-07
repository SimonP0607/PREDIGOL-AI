"""``sim-v1``: the joint distribution by halves and every market summed from it."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import poisson, skellam

from fbi.models.goals import InvalidCorrectionError
from fbi.models.lines import asian_handicap, over_under
from fbi.models.scoring import dc_tau, from_matrix, poisson_matrix
from fbi.simulator import joint as jt
from fbi.simulator import markets as mk
from fbi.simulator.markets import Selection as S  # noqa: N817

LH, LA = 1.55, 1.05


@pytest.fixture(scope="module")
def indep() -> jt.JointScore:
    return jt.build(jt.split_full_time(LH, LA))


@pytest.fixture(scope="module")
def dc() -> jt.JointScore:
    return jt.build(jt.split_full_time(LH, LA), rho=-0.1)


def p(j: jt.JointScore, market: str, pick: str, *rest: float | str) -> float:
    """P(win); ``rest`` is ``[line][, period]`` (a period alone is fine: "1H")."""
    line = next((float(x) for x in rest if not isinstance(x, str)), 0.0)
    period = next((x for x in rest if isinstance(x, str)), "FT")
    return mk.probability(j, S(market, pick, line, period))


# -- the distribution ---------------------------------------------------------------------------------------------------------------------

def test_the_joint_is_a_distribution_and_reports_its_tail(indep: jt.JointScore, dc: jt.JointScore) -> None:
    for j in (indep, dc):
        assert j.p.shape == (11, 11, 11, 11)
        assert j.p.min() >= 0 and j.p.sum() == pytest.approx(1.0, abs=1e-12)
        assert 0 <= j.tail_mass < 1e-6
    heavy = jt.build(jt.HalfIntensities(3.0, 3.0, 3.0, 3.0), max_goals=4)
    assert heavy.tail_mass > 0.1 and heavy.p.sum() == pytest.approx(1.0)


def test_every_group_of_outcomes_adds_up_to_one(dc: jt.JointScore) -> None:
    for period in mk.PERIODS:
        for name, group in mk.groups(period).items():
            assert sum(p(dc, s.market, s.pick, s.line, s.period) for s in group) == pytest.approx(1.0, abs=1e-12), (period, name)
    cs = sum(p(dc, "CS", f"{h}-{a}") for h in range(21) for a in range(21))
    assert cs == pytest.approx(1.0, abs=1e-12)
    menu = mk.menu(dc)
    assert sum(v["win"] for k, v in menu.items() if k.startswith("CS:FT:")) == pytest.approx(1.0)


def test_independent_poisson_matches_the_closed_forms(indep: jt.JointScore) -> None:
    """Truncated at 10 per half and renormalised: the closed forms hold to the reported tail (about 3e-9 here)."""
    # the sum of independent Poisson halves is Poisson: every full-time number has a closed form
    assert p(indep, "1X2", "Home") == pytest.approx(1 - skellam.cdf(0, LH, LA), abs=1e-8)
    assert p(indep, "1X2", "Draw") == pytest.approx(skellam.pmf(0, LH, LA), abs=1e-8)
    assert p(indep, "OU", "Under", 2.5) == pytest.approx(poisson.cdf(2, LH + LA), abs=1e-8)
    assert p(indep, "BTTS", "Yes") == pytest.approx((1 - math.exp(-LH)) * (1 - math.exp(-LA)), abs=1e-8)
    assert p(indep, "TT_HOME", "Over", 1.5) == pytest.approx(1 - poisson.cdf(1, LH), abs=1e-8)
    assert p(indep, "CS", "2-1") == pytest.approx(poisson.pmf(2, LH) * poisson.pmf(1, LA), abs=1e-8)
    # a half: Poisson with the split intensities
    h1, a1 = LH * jt.FIRST_HALF_SHARE_HOME, LA * jt.FIRST_HALF_SHARE_AWAY
    assert p(indep, "OU", "Under", 0.5, "1H") == pytest.approx(math.exp(-(h1 + a1)), abs=1e-8)
    assert p(indep, "1X2", "Draw", "2H") == pytest.approx(skellam.pmf(0, LH - h1, LA - a1), abs=1e-8)


def test_full_time_does_not_depend_on_the_split() -> None:
    a = jt.build(jt.split_full_time(LH, LA, share_home=0.3, share_away=0.6), rho=-0.1)
    b = jt.build(jt.split_full_time(LH, LA), rho=-0.1)
    np.testing.assert_allclose(a.score_matrix("FT")[:11, :11], b.score_matrix("FT")[:11, :11], atol=1e-12)
    assert p(a, "1X2", "Draw", "1H") != pytest.approx(p(b, "1X2", "Draw", "1H"), abs=1e-3)


def test_dixon_coles_full_time_is_the_source_models_matrix(dc: jt.JointScore) -> None:
    source = from_matrix(dc_tau(poisson_matrix(LH, LA), LH, LA, -0.1), LH, LA)
    derived = [p(dc, *x) for x in (("1X2", "Home"), ("1X2", "Draw"), ("1X2", "Away"), ("OU", "Over", 2.5), ("OU", "Under", 2.5),
                                   ("BTTS", "Yes"), ("BTTS", "No"))]
    # the source truncates at 10-10 and renormalises: the difference is its tail, far under a rounding of the stored rows
    np.testing.assert_allclose(derived, source.as_rows(), atol=2e-6)
    ft = dc.score_matrix("FT")
    assert ft[0, 0] == pytest.approx(poisson.pmf(0, LH) * poisson.pmf(0, LA) * (1 + LH * LA * 0.1), rel=1e-7)


def test_an_invalid_correction_is_refused_like_the_source_does() -> None:
    with pytest.raises(InvalidCorrectionError):
        jt.build(jt.split_full_time(2.5, 2.0), rho=0.5)
    with pytest.raises(ValueError, match="positive"):
        jt.HalfIntensities(0.5, 0.0, 0.5, 0.5)
    with pytest.raises(ValueError, match="between 0 and 1"):
        jt.split_full_time(1.0, 1.0, share_home=1.0)


def test_the_half_fits_shares_keep_the_full_time_model() -> None:
    halves = jt.HalfIntensities(0.5, 0.4, 0.9, 0.5)  # sums 1.4 / 0.9, unlike the full-time fit's 1.55 / 1.05
    scaled = jt.rescale_to_full_time(halves, LH, LA)
    assert scaled.home == pytest.approx(LH) and scaled.away == pytest.approx(LA)
    assert scaled.home_1h / scaled.home == pytest.approx(0.5 / 1.4)


# -- symmetry -----------------------------------------------------------------------------------------------------------------------------

def test_swapping_the_sides_mirrors_every_market() -> None:
    a = jt.build(jt.HalfIntensities(0.7, 0.4, 0.9, 0.6), rho=-0.05)
    b = jt.build(jt.HalfIntensities(0.4, 0.7, 0.6, 0.9), rho=-0.05)
    for period in mk.PERIODS:
        assert p(a, "1X2", "Home", period) == pytest.approx(p(b, "1X2", "Away", period), abs=1e-12)
        assert p(a, "BTTS", "Yes", period) == pytest.approx(p(b, "BTTS", "Yes", period), abs=1e-12)
        for line in (-1.25, -0.75, -0.5, 0.0, 0.25, 1.0):
            pa, pb = mk.price(a, S("AH", "Home", line, period)), mk.price(b, S("AH", "Away", line, period))
            assert (pa.win, pa.push) == pytest.approx((pb.win, pb.push), abs=1e-12)
    assert p(a, "HTFT", "1/2") == pytest.approx(p(b, "HTFT", "2/1"), abs=1e-12)
    assert p(a, "TT_HOME", "Over", 1.5) == pytest.approx(p(b, "TT_AWAY", "Over", 1.5), abs=1e-12)
    even = jt.build(jt.HalfIntensities(0.6, 0.6, 0.8, 0.8))
    assert p(even, "1X2", "Home") == pytest.approx(p(even, "1X2", "Away"), abs=1e-12)
    assert p(even, "AH", "Home", 0.0) == pytest.approx(0.5 * (1 - p(even, "1X2", "Draw")), abs=1e-12)


# -- the handicaps and their lines --------------------------------------------------------------------------------------------------------

def test_whole_half_and_quarter_asian_lines(dc: jt.JointScore) -> None:
    h, d, _ = (p(dc, "1X2", s) for s in ("Home", "Draw", "Away"))
    m = dc.score_matrix("FT")
    margin = {k: float(np.trace(m, offset=-k)) for k in range(-20, 21)}
    ah = lambda line, side="Home": mk.price(dc, S("AH", side, line))  # noqa: E731
    assert (ah(0.0).win, ah(0.0).push) == pytest.approx((h, d))  # handicap 0 is draw-no-bet
    assert (ah(0.0).win, ah(0.0).push) == pytest.approx((mk.price(dc, S("DNB", "Home")).win, mk.price(dc, S("DNB", "Home")).push))
    assert (ah(-0.5).win, ah(-0.5).push) == pytest.approx((h, 0.0))
    assert ah(0.5).win == pytest.approx(h + d)
    # -0.25: half at 0 (a draw pushes), half at -0.5 (a draw loses): a draw loses half the stake
    assert (ah(-0.25).win, ah(-0.25).push) == pytest.approx((h, d / 2))
    # +0.25: half at 0, half at +0.5: a draw wins half, returns half
    assert (ah(0.25).win, ah(0.25).push) == pytest.approx((h + d / 2, d / 2))
    # -0.75: half at -0.5, half at -1.0: a one-goal win wins half and returns half
    assert (ah(-0.75).win, ah(-0.75).push) == pytest.approx((sum(v for k, v in margin.items() if k >= 2) + margin[1] / 2, margin[1] / 2))
    # -1.0: a one-goal win returns the stake
    assert (ah(-1.0).win, ah(-1.0).push) == pytest.approx((sum(v for k, v in margin.items() if k >= 2), margin[1]))
    # the two sides of a line, and the stored prices' own arithmetic (fbi.models.lines) on the same full-time matrix
    from decimal import Decimal

    for line in (-1.75, -1.25, -0.75, -0.25, 0.0, 0.25, 0.75, 1.5):
        home, away = ah(line), ah(-line, "Away")
        assert home.win + away.win + home.push == pytest.approx(1.0) and home.push == pytest.approx(away.push)
        ref = asian_handicap(m, selection="Home", line=Decimal(str(line)))
        assert (home.win, home.push) == pytest.approx((ref.win, ref.push), abs=1e-12)
    for line in (1.75, 2.0, 2.25, 2.5, 3.0):
        o = mk.price(dc, S("OU", "Over", line))
        ref = over_under(m, selection="Over", line=Decimal(str(line)))
        assert (o.win, o.push) == pytest.approx((ref.win, ref.push), abs=1e-12)
        u = mk.price(dc, S("OU", "Under", line))
        assert o.win + u.win + o.push == pytest.approx(1.0) and o.push == pytest.approx(u.push)


def test_european_handicap_and_double_chance(dc: jt.JointScore) -> None:
    m = dc.score_matrix("FT")
    margin = {k: float(np.trace(m, offset=-k)) for k in range(-20, 21)}
    assert p(dc, "EH", "Draw", -1.0) == pytest.approx(margin[1])  # home -1: a one-goal home win is the handicap's draw
    assert p(dc, "EH", "Home", -1.0) == pytest.approx(sum(v for k, v in margin.items() if k >= 2))
    assert p(dc, "EH", "Away", 1.0) == pytest.approx(sum(v for k, v in margin.items() if k <= -2))
    h, d, a = (p(dc, "1X2", s) for s in ("Home", "Draw", "Away"))
    assert [p(dc, "DC", s) for s in ("1X", "X2", "12")] == pytest.approx([h + d, d + a, h + a])
    with pytest.raises(ValueError, match="whole number"):
        mk.settle(dc, S("EH", "Home", -0.5))


def test_bad_selections_are_refused() -> None:
    for args in (("XX", "Home"), ("1X2", "Home", 0.0, "3H"), ("HTFT", "1/1", 0.0, "1H"), ("OU", "Over", 2.3)):
        with pytest.raises(ValueError):
            S(*args)
    j = jt.build(jt.split_full_time(1.2, 1.0))
    for sel in (S("1X2", "Win"), S("OU", "Maybe", 2.5), S("CS", "two-one"), S("HTFT", "1-X"), S("DC", "1Z")):
        with pytest.raises(ValueError):
            mk.settle(j, sel)


# -- HT/FT and the halves -----------------------------------------------------------------------------------------------------------------

def test_htft_against_the_families_derivation() -> None:
    """Without the correction the joint is the families' assumption exactly: the same nine HT/FT cells (F10's derivation)."""
    from fbi.families import halves
    from fbi.families.fit import NO_DISPERSION, prediction

    first, second = prediction(0.6, 0.45, NO_DISPERSION), prediction(0.8, 0.6, NO_DISPERSION)
    j = jt.build(jt.HalfIntensities(0.6, 0.45, 0.8, 0.6))
    for label, value in halves.half_time_full_time(first, second).items():
        assert p(j, "HTFT", label) == pytest.approx(value, abs=1e-6), label
    menu = halves.menu(first, second)
    assert p(j, "OU", "Over", 1.5, "1H") == pytest.approx(menu["ou_1h_1.5"], abs=1e-6)
    assert p(j, "BTTS", "Yes", "2H") == pytest.approx(menu["btts_2h"], abs=1e-6)


# -- correlations -------------------------------------------------------------------------------------------------------------------------

def test_correlation_signs(dc: jt.JointScore) -> None:
    c = mk.Correlations(dc)
    over, btts, under = S("OU", "Over", 2.5), S("BTTS", "Yes"), S("OU", "Under", 2.5)
    home, away = S("1X2", "Home"), S("1X2", "Away")
    assert c.excess(over, btts) > 0.05  # more goals, both more likely to score
    assert c.excess(under, btts) < -0.05
    assert c.excess(home, away) == pytest.approx(-p(dc, "1X2", "Home") * p(dc, "1X2", "Away"))  # exclusive: P(both) = 0
    assert c.excess(home, S("DC", "1X")) > 0
    assert c.excess(home, S("TT_HOME", "Over", 1.5)) > 0 and c.excess(away, S("TT_HOME", "Over", 1.5)) < 0
    assert c.excess(S("OU", "Over", 0.5, "1H"), S("OU", "Over", 2.5)) > 0  # the first half's goals are the match's
    ps = c.pair(over, over)
    assert ps.correlation == pytest.approx(1.0) and ps.excess == pytest.approx(ps.p_a * (1 - ps.p_a))
    m = c.matrix([over, btts, home, away])
    assert np.allclose(m, m.T) and np.all(np.linalg.eigvalsh(m) > -1e-12)  # a covariance matrix
    assert c.pair(S("CS", "30-0"), home).correlation is None  # impossible score: no variance


def test_independent_halves_are_uncorrelated_without_the_correction(indep: jt.JointScore, dc: jt.JointScore) -> None:
    first, second = S("OU", "Over", 0.5, "1H"), S("OU", "Over", 0.5, "2H")
    assert mk.pair(indep, first, second).excess == pytest.approx(0.0, abs=1e-12)
    assert mk.pair(indep, S("TT_HOME", "Over", 0.5), S("TT_AWAY", "Over", 0.5)).excess == pytest.approx(0.0, abs=1e-12)
    # rho < 0 makes 0-0 and 1-1 more likely and 1-0 / 0-1 less: the halves are no longer independent
    assert mk.pair(dc, first, second).excess != pytest.approx(0.0, abs=1e-6)


def test_return_covariance_counts_pushes(dc: jt.JointScore) -> None:
    c = mk.Correlations(dc)
    a, b = S("AH", "Home", 0.0), S("AH", "Home", -0.25)
    win, push = c.price(a).win, c.price(a).push
    odds = 2.0
    mean = win * odds + push - 1
    var = win * (odds - 1) ** 2 + (1 - win - push) * 1.0 - mean**2
    assert c.return_covariance(a, odds, a, odds) == pytest.approx(var)
    assert c.return_covariance(a, 1.9, b, 2.1) > 0
