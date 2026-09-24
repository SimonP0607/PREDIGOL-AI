"""The models recover what they are given, and turn it into probabilities by arithmetic.

Synthetic leagues with KNOWN parameters: if the fit cannot get them back, the
model is wrong, however good its backtest looks. A double-counted strength -
the legacy bug - would show up here as expected goals far from the truth.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.stats import poisson

from fbi.models.elo_ologit import OLogitObs, fit_ologit
from fbi.models.goals import GoalObs, fit_goal_model
from fbi.models.metrics import brier, calibration, log_loss, paired_bootstrap_ci
from fbi.models.scoring import dc_tau, from_matrix, poisson_matrix

RNG = np.random.default_rng(2026)
N_TEAMS = 12
TRUE_MU, TRUE_HOME = 0.15, 0.28
TRUE_ATT = RNG.normal(0, 0.30, N_TEAMS)
TRUE_ATT -= TRUE_ATT.mean()
TRUE_DEF = RNG.normal(0, 0.25, N_TEAMS)
TRUE_DEF -= TRUE_DEF.mean()


def simulate(seasons: int = 6, rho: float = 0.0, rng: np.random.Generator | None = None) -> list[GoalObs]:
    rng = rng or np.random.default_rng(1)
    out: list[GoalObs] = []
    for _ in range(seasons):
        for h in range(N_TEAMS):
            for a in range(N_TEAMS):
                if h == a:
                    continue
                lh = math.exp(TRUE_MU + TRUE_HOME + TRUE_ATT[h] - TRUE_DEF[a])
                la = math.exp(TRUE_MU + TRUE_ATT[a] - TRUE_DEF[h])
                if rho == 0.0:
                    gh, ga = int(rng.poisson(lh)), int(rng.poisson(la))
                else:
                    m = dc_tau(poisson_matrix(lh, la), lh, la, rho)
                    m = m / m.sum()
                    k = int(rng.choice(m.size, p=m.ravel()))
                    gh, ga = divmod(k, m.shape[1])
                out.append(GoalObs(100 + h, 100 + a, gh, ga))
    return out


def test_poisson_recovers_known_strengths() -> None:
    model = fit_goal_model(simulate(), kind="poisson")
    assert model.converged
    att = np.array([model.attack[model.index[100 + i]] for i in range(N_TEAMS)])
    dfn = np.array([model.defence[model.index[100 + i]] for i in range(N_TEAMS)])
    assert np.corrcoef(att, TRUE_ATT)[0, 1] > 0.9
    assert np.corrcoef(dfn, TRUE_DEF)[0, 1] > 0.85
    assert model.home == pytest.approx(TRUE_HOME, abs=0.07)
    assert abs(att.sum()) < 1e-9 and abs(dfn.sum()) < 1e-9, "identified by sum-to-zero"


def test_expected_goals_are_not_double_counted() -> None:
    """lambda for a strong-vs-weak fixture must match the truth. Counting the
    attack twice (or a league average on top of both strengths) inflates it."""
    model = fit_goal_model(simulate(seasons=8), kind="poisson")
    h, a = int(np.argmax(TRUE_ATT)), int(np.argmin(TRUE_ATT))
    lh, la = model.lambdas(100 + h, 100 + a)
    true_lh = math.exp(TRUE_MU + TRUE_HOME + TRUE_ATT[h] - TRUE_DEF[a])
    true_la = math.exp(TRUE_MU + TRUE_ATT[a] - TRUE_DEF[h])
    assert lh == pytest.approx(true_lh, rel=0.15)
    assert la == pytest.approx(true_la, rel=0.15)


def test_dixon_coles_recovers_a_negative_rho() -> None:
    model = fit_goal_model(simulate(seasons=10, rho=-0.15, rng=np.random.default_rng(5)), kind="dixon_coles")
    assert model.converged
    assert -0.3 < model.rho < -0.03, f"rho {model.rho:.3f} should be clearly negative"


def test_dixon_coles_with_rho_zero_is_poisson() -> None:
    m = poisson_matrix(1.4, 1.1)
    assert np.allclose(dc_tau(m, 1.4, 1.1, 0.0), m)


def test_score_matrix_probabilities_are_consistent() -> None:
    lh, la = 1.6, 1.1
    p = from_matrix(poisson_matrix(lh, la), lh, la)
    assert p.home + p.draw + p.away == pytest.approx(1.0, abs=1e-9)
    assert p.under_2_5 == pytest.approx(poisson.cdf(2, lh + la), abs=1e-4), "sum of two Poissons is Poisson"
    assert p.btts_yes == pytest.approx((1 - math.exp(-lh)) * (1 - math.exp(-la)), abs=1e-4)
    sym = from_matrix(poisson_matrix(1.3, 1.3), 1.3, 1.3)
    assert sym.home == pytest.approx(sym.away, abs=1e-12)


def test_prediction_intervals_contain_the_point() -> None:
    model = fit_goal_model(simulate(), kind="poisson")
    point = np.array(model.predict(100, 101).as_1x2())
    lo, hi = model.interval_1x2(100, 101)
    assert np.all(lo <= point + 1e-12) and np.all(point <= hi + 1e-12)
    assert np.all(hi - lo > 0), "a fitted model is not certain"


def test_ordered_logit_is_monotone_and_recovers_its_parameters() -> None:
    rng = np.random.default_rng(3)
    beta, home, t1, t2 = 0.005, 0.35, -0.55, 0.65
    obs = []
    for i in range(4000):
        neutral = i % 5 == 0  # some neutral venues, or home and thresholds are not separable
        d = float(rng.normal(0, 150))
        s = beta * d + (0.0 if neutral else home)
        pa = 1 / (1 + math.exp(-(t1 - s)))
        pad = 1 / (1 + math.exp(-(t2 - s)))
        u = rng.random()
        obs.append(OLogitObs(d, neutral, 0 if u < pa else 1 if u < pad else 2))
    m = fit_ologit(obs)
    assert m.home_identified and m.cov is not None
    assert m.beta == pytest.approx(beta, rel=0.15)
    assert m.home == pytest.approx(home, abs=0.1)
    ph = [m.predict(d)[0] for d in (-200, 0, 200)]
    assert ph[0] < ph[1] < ph[2], "a stronger home side is more likely to win"
    assert sum(m.predict(37.0)) == pytest.approx(1.0)


def test_scores_have_their_textbook_values() -> None:
    y = np.array([0, 1, 2, 2])
    perfect = np.eye(3)[y].astype(float)
    assert brier(perfect, y) == pytest.approx(0.0)
    uniform = np.full((4, 3), 1 / 3)
    assert brier(uniform, y) == pytest.approx(2 / 3)
    assert log_loss(uniform, y) == pytest.approx(math.log(3))


def test_calibrated_probabilities_have_small_ece_and_miscalibrated_ones_do_not() -> None:
    rng = np.random.default_rng(9)
    p = rng.dirichlet([3, 2, 3], size=20000)
    y = np.array([rng.choice(3, p=row) for row in p])
    ece, buckets = calibration(p, y)
    assert ece < 0.02
    assert sum(b.n for b in buckets) == p.size
    overconfident = np.clip(p * 1.6 - 0.2, 0.001, None)
    overconfident /= overconfident.sum(axis=1, keepdims=True)
    assert calibration(overconfident, y)[0] > 3 * ece


def test_paired_bootstrap_of_identical_scores_is_zero() -> None:
    a = np.random.default_rng(1).random(500)
    mean, lo, hi = paired_bootstrap_ci(a, a)
    assert mean == 0 and lo == 0 and hi == 0


def test_goal_model_gradient_is_exact() -> None:
    """The analytic gradient drives both the optimiser and the Hessian. A sign
    slip would still 'converge' - to the wrong place - so it is checked against
    finite differences, for Poisson and for Dixon-Coles with a penalty."""
    from fbi.models import goals as g

    obs = simulate(seasons=1, rho=-0.1, rng=np.random.default_rng(4))
    model = fit_goal_model(obs, kind="dixon_coles", penalty=2.0)
    teams = model.teams
    index = {t: i for i, t in enumerate(teams)}
    gh = np.array([o.goals_home for o in obs], dtype=float)
    ga = np.array([o.goals_away for o in obs], dtype=float)
    from scipy.special import gammaln

    d = g._Data(
        hi=np.array([index[o.home_id] for o in obs]), ai=np.array([index[o.away_id] for o in obs]),
        gh=gh, ga=ga, w=np.linspace(0.5, 1.0, len(obs)), home_flag=np.ones(len(obs)),
        const=gammaln(gh + 1) + gammaln(ga + 1),
        m00=(gh == 0) & (ga == 0), m01=(gh == 0) & (ga == 1), m10=(gh == 1) & (ga == 0), m11=(gh == 1) & (ga == 1),
    )
    n = len(teams)
    rng = np.random.default_rng(0)
    for dc in (False, True):
        theta = rng.normal(0, 0.2, 2 * n + (1 if dc else 0))
        if dc:
            theta[-1] = -0.05
        _, grad = g._objective(theta, d, n, dc, 2.0)
        numeric = np.empty_like(theta)
        for j in range(len(theta)):
            e = np.zeros_like(theta)
            e[j] = 1e-6
            numeric[j] = (g._objective(theta + e, d, n, dc, 2.0)[0] - g._objective(theta - e, d, n, dc, 2.0)[0]) / 2e-6
        assert np.allclose(grad, numeric, rtol=1e-4, atol=1e-4), f"dc={dc}"


def test_penalty_keeps_a_goalless_team_finite() -> None:
    """A team that never scored in training: unpenalised MLE sends its attack to
    minus infinity, i.e. 'this team can never score'. The prior stops that."""
    obs = [o for o in simulate(seasons=2) if o.home_id != 100 and o.away_id != 100]
    obs += [GoalObs(100, 101, 0, 2), GoalObs(102, 100, 3, 0)]
    free = fit_goal_model(obs, kind="poisson", penalty=0.0, with_covariance=False)
    shrunk = fit_goal_model(obs, kind="poisson", penalty=3.0, with_covariance=False)
    assert free.attack[free.index[100]] < -3.0, "the unpenalised estimate runs away"
    assert free.lambdas(100, 101)[0] < 0.05, "...and says this team will practically never score"
    assert -1.5 < shrunk.attack[shrunk.index[100]] < 0.0, "the prior holds it near an average team"
    lh, _ = shrunk.lambdas(100, 101)
    assert lh > 0.2


def test_batch_market_arithmetic_equals_the_scalar_path() -> None:
    from fbi.models.scoring import market_rows_batch

    lh = np.array([0.4, 1.3, 2.7, 1.05])
    la = np.array([1.9, 1.1, 0.3, 1.05])
    rho = np.array([-0.12, 0.0, 0.05, -0.2])
    batch = market_rows_batch(lh, la, rho)
    for i in range(len(lh)):
        m = dc_tau(poisson_matrix(lh[i], la[i]), lh[i], la[i], rho[i])
        assert np.allclose(batch[i], from_matrix(m, lh[i], la[i]).as_rows(), atol=1e-12)


def test_intervals_cover_every_market_and_contain_the_point() -> None:
    model = fit_goal_model(simulate(seasons=3, rho=-0.1, rng=np.random.default_rng(8)), kind="dixon_coles",
                           penalty=1.0)
    assert model.cov is not None
    out = model.interval_rows(100, 101)
    assert out is not None
    lo, hi = out
    point = np.array(model.predict(100, 101).as_rows())
    assert np.all(lo <= point) and np.all(point <= hi)
    assert np.all(hi - lo > 0)
    assert np.all(hi - lo < 0.5), "three seasons of data should not leave a probability unknown"


def test_more_data_narrows_the_interval() -> None:
    small = fit_goal_model(simulate(seasons=1), kind="poisson", penalty=1.0)
    large = fit_goal_model(simulate(seasons=8), kind="poisson", penalty=1.0)
    ws = small.interval_rows(100, 101)
    wl = large.interval_rows(100, 101)
    assert ws is not None and wl is not None
    assert (wl[1] - wl[0])[0] < (ws[1] - ws[0])[0]


def test_ordered_logit_interval_contains_the_point() -> None:
    rng = np.random.default_rng(12)
    obs = [OLogitObs(float(d), False, int(rng.choice(3, p=[0.3, 0.27, 0.43]))) for d in rng.normal(0, 120, 600)]
    m = fit_ologit(obs)
    out = m.interval(50.0)
    assert out is not None
    lo, hi = out
    p = np.array(m.predict(50.0))
    assert np.all(lo <= p) and np.all(p <= hi) and np.all(hi > lo)


def test_ordered_logit_without_neutral_venues_fixes_home_and_refuses_neutral_fixtures() -> None:
    """Every league match has a home side: home advantage and the thresholds are
    then one direction in parameter space (a zero Hessian eigenvalue). The fit
    must stay identified, keep its covariance, and decline a neutral fixture."""
    rng = np.random.default_rng(21)
    obs = [OLogitObs(float(d), False, int(rng.choice(3, p=[0.3, 0.26, 0.44]))) for d in rng.normal(0, 120, 900)]
    m = fit_ologit(obs)
    assert not m.home_identified and m.home == 0.0
    assert m.converged and m.cov is not None
    home_rate = np.mean([o.outcome == 2 for o in obs])
    assert m.predict(0.0)[0] == pytest.approx(home_rate, abs=0.04), "thresholds absorbed the home edge"
    with pytest.raises(ValueError):
        m.predict(0.0, neutral=True)
