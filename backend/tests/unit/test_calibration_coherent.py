"""The coherent multiclass calibration of INT-A02 (``fbi.intel.calibration_coherent``, ``cal-coherent-v1``): a market that adds up to
one by construction, the two-outcome case that is cal-logit2-v1 itself, and the pure pieces its walk-forward evaluation reads."""

from __future__ import annotations

import math

import numpy as np
import pytest

from fbi.intel import calibration_coherent as cc
from fbi.intel import stats


def dirichlet(n: int, k: int, *, seed: int, conc: float = 4.0) -> np.ndarray:
    return np.random.default_rng(seed).dirichlet(np.full(k, conc), size=n)


def simulate(n: int, *, a: tuple[float, ...], b: float, c: float, seed: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A model q, a market m and outcomes drawn from the TRUE pool exp(a_k + b log q_k + c log m_k)."""
    k = len(a)
    q = dirichlet(n, k, seed=seed)
    m = dirichlet(n, k, seed=seed + 1)
    eta = np.asarray(a) + b * np.log(q) + c * np.log(m)
    p = np.exp(eta - eta.max(axis=1, keepdims=True))
    p /= p.sum(axis=1, keepdims=True)
    u = np.random.default_rng(seed + 2).uniform(size=(n, 1))
    y = (u > np.cumsum(p, axis=1)).sum(axis=1).astype(np.int64)
    return q, m, y


def test_every_market_adds_up_to_one_by_construction() -> None:
    for k in (2, 3):
        q, m, y = simulate(3000, a=(0.2, -0.1, 0.0)[:k] if k == 3 else (0.3, 0.0), b=0.4, c=0.9, seed=11 + k)
        f = cc.fit(q, m, y)
        assert f.converged and f.n == 3000 and f.outcomes == k
        p = f.predict(dirichlet(500, k, seed=5), dirichlet(500, k, seed=6))
        assert p.shape == (500, k)
        assert float(cc.sum_gap(p).max()) <= cc.SUM_TOLERANCE
        assert np.all((p > 0) & (p < 1))


def test_a_known_pool_is_recovered() -> None:
    q, m, y = simulate(40000, a=(0.25, -0.35, 0.0), b=0.3, c=0.8, seed=21)
    f = cc.fit(q, m, y)
    assert f.reference == 2 and f.intercepts[2] == 0.0
    assert abs(f.intercepts[0] - 0.25) < 0.06 and abs(f.intercepts[1] + 0.35) < 0.06
    assert abs(f.b - 0.3) < 0.06 and abs(f.c - 0.8) < 0.06
    assert f.market_share is not None and abs(f.market_share - 0.8 / 1.1) < 0.05


def test_two_outcomes_is_cal_logit2_of_one_side() -> None:
    """With two outcomes the pool is logit p_1 = (a_1 - a_2) + b logit q_1 + c logit m_1: the binary fit of fbi.intel.stats, which is
    what cal-logit2-v1 runs, on one side of the market with the same penalty."""
    q, m, y = simulate(5000, a=(0.4, 0.0), b=0.5, c=0.7, seed=31)
    f = cc.fit(q, m, y)
    side = stats.fit_logistic(np.column_stack([stats.logit(q[:, 0]), stats.logit(m[:, 0])]), (y == 0).astype(float), l2=cc.L2)
    assert f.intercepts[0] == pytest.approx(side.w[0], abs=1e-6)
    assert f.b == pytest.approx(side.w[1], abs=1e-6) and f.c == pytest.approx(side.w[2], abs=1e-6)
    p = f.predict(q, m)
    expected = side.predict(np.column_stack([stats.logit(q[:, 0]), stats.logit(m[:, 0])]))
    assert np.allclose(p[:, 0], expected, atol=1e-6) and np.allclose(p[:, 1], 1 - expected, atol=1e-6)


def test_the_reference_outcome_changes_no_probability() -> None:
    """The intercepts are free (only the slopes are penalised), so fixing another one at 0 is the same fit."""
    q, m, y = simulate(4000, a=(0.1, -0.2, 0.0), b=0.6, c=0.5, seed=41)
    last, first = cc.fit(q, m, y), cc.fit(q, m, y, reference=0)
    assert first.intercepts[0] == 0.0
    assert np.allclose(last.predict(q, m), first.predict(q, m), atol=1e-8)
    assert last.b == pytest.approx(first.b, abs=1e-8) and last.c == pytest.approx(first.c, abs=1e-8)


def test_inputs_need_not_add_up_to_one() -> None:
    """A constant times a row of q (or m) adds a constant to its logs, which cancels in the softmax."""
    q, m, y = simulate(2000, a=(0.0, 0.0, 0.0), b=0.5, c=0.5, seed=51)
    f = cc.fit(q, m, y)
    scale = np.random.default_rng(1).uniform(0.9, 1.1, size=(2000, 1))
    assert np.allclose(f.predict(q, m), f.predict(q * scale, m / scale), atol=1e-12)


def test_the_penalty_shrinks_only_the_slopes() -> None:
    q, m, y = simulate(3000, a=(0.3, -0.3, 0.0), b=0.6, c=0.6, seed=61)
    soft, hard = cc.fit(q, m, y), cc.fit(q, m, y, l2=1e6)
    assert abs(hard.b) < 0.01 and abs(hard.c) < 0.01
    # with the slopes held at ~0 the intercepts are the log odds of the outcomes' frequencies against the reference
    freq = np.bincount(y, minlength=3) / y.size
    assert hard.intercepts[0] == pytest.approx(math.log(freq[0] / freq[2]), abs=0.01)
    assert abs(soft.b) > 0.3


def test_the_market_alone_takes_the_whole_pool() -> None:
    """Outcomes drawn from the market: the model adds nothing and its slope is about zero."""
    q, m, y = simulate(30000, a=(0.0, 0.0, 0.0), b=0.0, c=1.0, seed=71)
    f = cc.fit(q, m, y)
    assert abs(f.b) < 0.05 and abs(f.c - 1.0) < 0.06
    assert f.market_share is not None and f.market_share > 0.93


def test_bad_inputs_are_refused() -> None:
    q = dirichlet(10, 3, seed=1)
    with pytest.raises(ValueError):
        cc.fit(q, q[:, :2], np.zeros(10, dtype=np.int64))
    with pytest.raises(ValueError):
        cc.fit(q, q, np.full(10, 3, dtype=np.int64))
    with pytest.raises(ValueError):
        cc.fit(q * 0.0, q, np.zeros(10, dtype=np.int64))
    with pytest.raises(ValueError):
        cc.fit(q[:, :1], q[:, :1], np.zeros(10, dtype=np.int64))
    with pytest.raises(ValueError):
        cc.fit(q, q, np.zeros(10, dtype=np.int64), reference=3)
    f = cc.fit(q, q, np.arange(10, dtype=np.int64) % 3)
    with pytest.raises(ValueError):
        f.predict(q[:, :2], q[:, :2])


def test_the_log_loss_is_that_of_the_outcome_that_happened() -> None:
    p = np.array([[0.5, 0.3, 0.2], [0.1, 0.1, 0.8]])
    assert np.allclose(cc.log_loss(p, [1, 2]), [-math.log(0.3), -math.log(0.8)])
    assert cc.log_loss([[1.0, 0.0]], [1])[0] == pytest.approx(-math.log(cc.EPS))


def test_rescaling_is_what_the_common_view_does() -> None:
    raw = np.array([[0.5, 0.3, 0.3], [0.2, 0.2, 0.5]])
    p = cc.rescale(raw)
    assert np.allclose(p.sum(axis=1), 1.0) and p[0, 0] == pytest.approx(0.5 / 1.1)
    assert np.allclose(cc.sum_gap(raw), [0.1, 0.1])


def test_ece_over_groups_of_equal_size() -> None:
    p = np.array([0.1, 0.1, 0.2, 0.2, 0.8, 0.8, 0.9, 0.9])
    y = np.array([0, 0, 0, 1, 1, 1, 1, 1], dtype=float)
    # two groups of four: mean p 0.15 against 0.25 observed, and 0.85 against 1.0
    assert cc.ece_equal_mass(y, p, bins=2) == pytest.approx(0.5 * 0.10 + 0.5 * 0.15)
    table = cc.reliability_equal_mass(y, p, bins=2)
    assert [t["n"] for t in table] == [4, 4] and table[1]["hit"] == 1.0
    sizes = [t["n"] for t in cc.reliability_equal_mass(np.zeros(23), np.linspace(0.01, 0.99, 23))]
    assert sum(sizes) == 23 and max(sizes) - min(sizes) <= 1 and len(sizes) == 10
    assert math.isnan(cc.ece_equal_mass([], []))
    assert cc.reliability_equal_mass([], []) == []
    rng = np.random.default_rng(3)
    pp = rng.uniform(0.05, 0.95, 200000)
    assert cc.ece_equal_mass((rng.uniform(size=pp.size) < pp).astype(float), pp) < 0.01, "a calibrated forecast has an ECE near 0"


def test_a_day_learns_only_from_what_was_over_and_settled_before_it() -> None:
    cutoff, window = 100.0, 30.0
    kickoff = np.array([60.0, 70.0, 80.0, 99.0, 100.0, 69.9])
    settled = np.array([61.0, 72.0, 100.0, 99.5, 101.0, 70.0])
    mask = cc.train_mask(kickoff, settled, cutoff=cutoff, window=window)
    # 60 is out of the window, 80 was settled at the cut-off (not before), 100 kicked off at it, 69.9 is out of the window
    assert mask.tolist() == [False, True, False, True, False, False]


def test_the_day_bootstrap_is_reproducible() -> None:
    days = [0.01, -0.02, 0.005, 0.0, -0.01, 0.015, -0.005]
    mean, lo, hi = cc.day_bootstrap(days, reps=2000, seed=20261111)
    assert mean == pytest.approx(float(np.mean(days))) and lo < mean < hi
    assert cc.day_bootstrap(days, reps=2000, seed=20261111) == (mean, lo, hi)
    assert cc.day_bootstrap([0.3, 0.3, 0.3], reps=50, seed=1) == pytest.approx((0.3, 0.3, 0.3))
    assert all(math.isnan(x) for x in cc.day_bootstrap([], reps=10, seed=1))
    wmean, wlo, whi = cc.cluster_bootstrap([1.0, 3.0], [1.0, 3.0], reps=500, seed=2)
    assert wmean == pytest.approx(1.0) and wlo == pytest.approx(1.0) and whi == pytest.approx(1.0)
    assert cc.cluster_bootstrap([2.0, 0.0], [1.0, 3.0], reps=10, seed=2)[0] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        cc.day_bootstrap(days, reps=0, seed=1)


def test_the_record_of_a_fit() -> None:
    q, m, y = simulate(1500, a=(0.1, 0.0), b=0.5, c=0.5, seed=81)
    doc = cc.fit(q, m, y).as_json()
    assert doc["version"] == cc.VERSION and doc["reference"] == 1 and doc["intercepts"][1] == 0.0 and doc["converged"]
    assert cc.finite(float("nan")) is None and cc.finite(None) is None and cc.finite(0.1234567) == 0.123457
    assert math.isnan(cc.sd([1.0])) and cc.sd([1.0, 3.0]) == pytest.approx(math.sqrt(2.0))
