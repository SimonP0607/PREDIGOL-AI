"""Research V2's rules on plain values: the opinion pool, the roles, the audit's arithmetic and
the gradient-boosted challenger's protocol."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pytest

from fbi.backtesting.data import BacktestData, MarketTriplet
from fbi.backtesting.evaluate import Comparison, Diff, Scores
from fbi.backtesting.walkforward import WalkForwardConfig
from fbi.features.engine import FEATURE_NAMES, walk_forward
from fbi.research.blend import BlendResult, fit_weight, pool, weight_interval
from fbi.research.pick_audit import Group, audited, bucket_of
from fbi.research.roles import model_role
from fbi.research.v2_models import run_hgb
from tests.unit.test_backtest_protocol import COMP, _league, _targets


def _world(n: int, seed: int, informative: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    truth = rng.dirichlet([4, 2.5, 3], size=n)
    y = np.array([rng.choice(3, p=p) for p in truth])
    noise = rng.dirichlet([4, 2.5, 3], size=n)
    market = 0.5 * truth + 0.5 * noise if informative else truth
    model = truth if informative else rng.dirichlet([4, 2.5, 3], size=n)
    return market, model, y


def test_the_pool_is_the_market_at_zero_and_the_model_at_one() -> None:
    q, m, _ = _world(10, 1, True)
    assert np.allclose(pool(q, m, 0.0), q / q.sum(axis=1, keepdims=True))
    assert np.allclose(pool(q, m, 1.0), m / m.sum(axis=1, keepdims=True))


def test_a_model_that_knows_more_gets_weight_and_noise_gets_none() -> None:
    q, m, y = _world(3000, 2, informative=True)
    assert fit_weight(q, m, y) > 0.3
    q, m, y = _world(3000, 3, informative=False)
    w, lo, hi = weight_interval(q, m, y, [i // 10 for i in range(len(y))], draws=60)
    assert lo <= w <= hi and lo < 0.05, "a model of pure noise adds nothing: the interval reaches zero"


def _cmp(lo: float, hi: float) -> Comparison:
    s = Scores(100, 0.6, 1.0, 0.02, 0.5, ())
    return Comparison("market", "1X2", 0.0, 100, s, s, Diff((lo + hi) / 2, lo, hi), Diff(0, 0, 0))


def _blend(w_lo: float, diff_hi: float | None) -> BlendResult:
    return BlendResult("market", 0.1, 100, w_lo + 0.05, w_lo, w_lo + 0.1, 100, 1.0, 1.0,
                       None if diff_hi is None else diff_hi - 0.01, None if diff_hi is None else diff_hi - 0.02,
                       diff_hi)


def test_roles_follow_the_evidence() -> None:
    assert model_role(_cmp(-0.02, -0.001), None, champion="m").role == "CHALLENGER"
    assert model_role(_cmp(0.01, 0.03), _blend(-0.1, 0.01), champion="m").role == "REJECTED"
    assert model_role(_cmp(0.01, 0.03), _blend(0.02, -0.001), champion="m").role == "CHALLENGER", \
        "worse alone, but it adds information and the blend beats the market"
    assert model_role(_cmp(0.01, 0.03), _blend(0.02, 0.01), champion="m").role == "RESEARCH", \
        "a positive weight whose blend does not beat the market cannot tell yet"
    assert model_role(_cmp(-0.01, 0.01), None, champion="m").role == "RESEARCH"
    assert model_role(None, None, champion="m").role == "RESEARCH"


def test_the_audit_separates_the_price_from_luck() -> None:
    ko = datetime(2026, 9, 30, 18, tzinfo=UTC)
    base = {"competition": "Premier League", "competition_type": "domestic_league", "entity_scope": "club",
            "tier": 1, "model": "dixon_coles", "market_key": "1X2", "kickoff_at": ko, "p_push": None,
            "fixture_id": 9}
    rows = [
        base | {"id": 1, "market_odds": Decimal("3.00"), "profit_units": Decimal("-1"), "ev": Decimal("0.20"),
                "p_close": Decimal("0.30"), "p_market_fair": Decimal("0.32"), "close_at": ko - timedelta(minutes=30)},
        base | {"id": 2, "market_odds": Decimal("3.00"), "profit_units": Decimal("2"), "ev": Decimal("0.20"),
                "p_close": Decimal("0.30"), "p_market_fair": Decimal("0.32"), "close_at": ko - timedelta(minutes=30)},
        base | {"id": 3, "market_odds": Decimal("1.50"), "profit_units": Decimal("0.5"), "ev": Decimal("0.05"),
                "p_close": None, "p_market_fair": None, "close_at": None},
    ]
    picks = audited(rows)
    assert picks[0].ev_close == pytest.approx(-0.10) and picks[0].segment == "top_league"
    assert picks[0].ev_pick == pytest.approx(-0.04), "the price paid, against the market's view when the pick was made"
    assert picks[2].ev_close is None and picks[2].ev_pick is None and picks[0].minutes_before == 30
    g = Group()
    for p in picks[:2]:
        g.add(p)
    s = g.summary()
    assert s["roi"] == pytest.approx(0.5) and s["ev_at_close"] == pytest.approx(-0.10)
    assert s["luck"] == pytest.approx(0.6), "won more than the market's view of the bets said"
    assert s["movement"] == pytest.approx(-0.06), "the market moved away from the selection after the pick"
    assert s["ev_at_pick"] + s["movement"] + s["luck"] == pytest.approx(s["roi"]), \
        "realised = the price paid + the market's move + luck"
    # both picks on one match: their spreads add (perfect correlation, the upper bound)
    sd = math.sqrt(0.3 * 4 + 0.7 - 0.01)
    assert s["luck_se_if_close_right"] == pytest.approx(2 * sd / 2)
    assert s["luck_z"] == pytest.approx(0.6 / sd)
    assert bucket_of(1.5) == "1.0-1.6" and bucket_of(7.0) == "5.0+"


def test_a_small_group_that_all_lost_is_not_certain_bad_luck() -> None:
    ko = datetime(2026, 9, 30, 18, tzinfo=UTC)
    rows = [{"competition": "Premier League", "competition_type": "domestic_league", "entity_scope": "club",
             "tier": 1, "model": "poisson", "market_key": "1X2", "kickoff_at": ko, "p_push": None,
             "fixture_id": 100 + i, "id": i, "market_odds": Decimal("5.00"), "profit_units": Decimal("-1"),
             "ev": Decimal("0.40"), "p_close": Decimal("0.185"), "p_market_fair": Decimal("0.19"),
             "close_at": ko - timedelta(hours=2)} for i in range(12)]
    g = Group()
    for p in audited(rows):
        g.add(p)
    s = g.summary()
    assert s["luck_se"] is not None and s["luck_se"] < 1e-9, "every pick lost: the empirical spread is nil"
    assert s["luck_se_if_close_right"] > 0.5, "twelve longshots losing is well within what luck does"
    assert -2 < s["luck_z"] < -1


def test_the_trees_are_walk_forward_and_take_the_pre_closing_price_only() -> None:
    matches = _league()
    targets = _targets(matches)
    vectors, _ = walk_forward(matches, [(m, m.kickoff_at - timedelta(minutes=60)) for m in matches])
    features = {v.fixture_id: v.values for v in vectors}
    cutoffs = {v.fixture_id: v.data_cutoff for v in vectors}
    market = {m.fixture_id: MarketTriplet(0.45, 0.27, 0.28, 1.05) for m in matches}
    data = BacktestData(matches, features, {}, cutoffs, {"AVG/pre_closing/shin": market}, {})
    cfg = WalkForwardConfig(competition_ids=(COMP,), refit_days=28)
    import fbi.research.v2_models as v2m

    v2m.MIN_HGB_TRAIN = 100  # the synthetic league is small; the protocol is what is under test
    try:
        plain = run_hgb(data, targets, cfg=cfg, refit_days=28)
        with_market = run_hgb(data, targets, cfg=cfg, refit_days=28, with_market=True)
    finally:
        v2m.MIN_HGB_TRAIN = 1000
    for run in (plain, with_market):
        assert run.predictions and run.fits >= 5
        for p in run.predictions.values():
            assert sum(p.p) == pytest.approx(1.0) and p.data_cutoff < next(
                m.kickoff_at for m in targets if m.fixture_id == p.fixture_id)
        for block in run.blocks:
            assert block.newest_train_kickoff is None or block.newest_train_kickoff < block.cutoff
    assert len(FEATURE_NAMES) > 30


def test_picks_on_one_match_are_one_cluster() -> None:
    from fbi.research.pick_audit import mean_se

    independent = [(i, x) for i, x in enumerate([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])]
    together = [(i // 3, x) for i, x in enumerate([1.0, 1.0, 1.0, -1.0, -1.0, -1.0])]
    _, se_ind = mean_se(independent)
    _, se_tog = mean_se(together)
    assert se_ind is not None and se_tog is not None and se_tog > se_ind, \
        "three picks that win or lose together are one piece of evidence, not three"
