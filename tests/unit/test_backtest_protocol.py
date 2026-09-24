"""The walk-forward protocol cannot see the future - checked by changing the future.

A leakage test that only inspects timestamps trusts the code that produced
them. The stronger test rewrites every result after some date and requires
every prediction made before that date to come out bit-for-bit identical.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from fbi.backtesting import walkforward as wf
from fbi.backtesting.data import BacktestData, MarketTriplet
from fbi.backtesting.evaluate import (
    BET_EV_THRESHOLD,
    BET_PRICE_KEY,
    PRIMARY_BASELINE,
    compare,
    simulate_bets,
)
from fbi.backtesting.persist import verdict
from fbi.backtesting.walkforward import (
    GoalSpec,
    ModelRun,
    Prediction,
    PredRow,
    WalkForwardConfig,
    run_elo_ologit,
    run_goal_model,
    select_goal_spec,
)
from fbi.features.data import MatchRecord
from fbi.features.engine import RESULT_AVAILABLE_AFTER, LeakageError

N_TEAMS = 10
COMP = 7


def _league(seed: int = 3) -> list[MatchRecord]:
    """Three seasons of a ten-team double round robin, one matchday a week."""
    rng = np.random.default_rng(seed)
    strength = rng.normal(0, 0.35, N_TEAMS)
    out: list[MatchRecord] = []
    fid = 1
    for season in (2022, 2023, 2024):
        pairs = [(h, a) for h in range(N_TEAMS) for a in range(N_TEAMS) if h != a]
        rng.shuffle(pairs)
        start = datetime(season, 8, 6, 14, 0, tzinfo=UTC)
        for i, (h, a) in enumerate(pairs):
            ko = start + timedelta(days=7 * (i // 5), minutes=15 * (i % 5))
            lh = math.exp(0.1 + 0.3 + strength[h] - strength[a])
            la = math.exp(0.1 + strength[a] - strength[h])
            out.append(MatchRecord(fid, ko, COMP, "domestic_league", season, 100 + h, 100 + a,
                                   int(rng.poisson(lh)), int(rng.poisson(la)), False, "finished"))
            fid += 1
    return out


def _data(matches: list[MatchRecord]) -> BacktestData:
    return BacktestData(matches, {}, {}, {}, {}, {})


CFG = WalkForwardConfig(competition_ids=(COMP,), refit_days=7, validation_refit_days=28,
                        xi_grid=(0.0, 0.004), penalty_grid=(1.0, 3.0), interval_draws=50)


def _targets(matches: list[MatchRecord], season: int = 2024) -> list[MatchRecord]:
    return [m for m in matches if m.season == season]


def test_every_block_respects_the_availability_model() -> None:
    matches = _league()
    run = run_goal_model(_data(matches), _targets(matches), spec=GoalSpec("poisson", 0.002, 1.0), cfg=CFG,
                         refit_days=7, intervals=True)
    assert run.predictions, "the synthetic league must be predictable"
    by_id = {m.fixture_id: m for m in matches}
    for block in run.blocks:
        assert block.cutoff < block.first_target_kickoff
        if block.newest_train_kickoff is not None:
            assert block.newest_train_kickoff + RESULT_AVAILABLE_AFTER < block.cutoff
        for fid in block.train_ids:
            assert by_id[fid].kickoff_at + RESULT_AVAILABLE_AFTER < block.cutoff
    for p in run.predictions.values():
        assert p.data_cutoff < by_id[p.fixture_id].kickoff_at


def test_changing_the_future_does_not_change_the_past() -> None:
    matches = _league()
    targets = _targets(matches)
    split = targets[len(targets) // 2].kickoff_at
    poisoned = [replace(m, goals_home=7, goals_away=0) if m.kickoff_at >= split else m for m in matches]
    spec = GoalSpec("dixon_coles", 0.004, 1.0)
    clean = run_goal_model(_data(matches), targets, spec=spec, cfg=CFG, refit_days=7, intervals=True)
    dirty = run_goal_model(_data(poisoned), _targets(poisoned), spec=spec, cfg=CFG, refit_days=7, intervals=True)
    before = [fid for fid, p in clean.predictions.items() if p.data_cutoff <= split]
    assert len(before) > 20
    for fid in before:
        assert clean.predictions[fid].rows == dirty.predictions[fid].rows, f"fixture {fid} saw the future"
    after = [fid for fid, p in clean.predictions.items() if p.data_cutoff > split + RESULT_AVAILABLE_AFTER]
    assert any(clean.predictions[f].p != dirty.predictions[f].p for f in after), "the poison must be visible later"


def test_hyperparameters_are_chosen_without_the_test_season() -> None:
    matches = _league()
    poisoned = [replace(m, goals_home=9, goals_away=9) if m.season == 2024 else m for m in matches]
    a = select_goal_spec(_data(matches), CFG, "poisson")
    b = select_goal_spec(_data(poisoned), CFG, "poisson")
    assert a == b


def test_a_training_result_inside_the_availability_window_is_refused() -> None:
    m = _league()[0]
    late = replace(m, kickoff_at=m.kickoff_at)
    target = replace(m, fixture_id=999, kickoff_at=m.kickoff_at + timedelta(hours=2, minutes=59))
    with pytest.raises(LeakageError):
        wf._check_block(target.kickoff_at - timedelta(minutes=1), [late], [target])
    with pytest.raises(LeakageError):
        wf._check_block(target.kickoff_at, [], [target])


def test_the_elo_model_refuses_a_feature_computed_after_kickoff() -> None:
    matches = _league()
    features: dict[int, dict[str, float | None]] = {m.fixture_id: {"elo_diff": 10.0} for m in matches}
    cutoffs = {m.fixture_id: m.kickoff_at - timedelta(hours=1) for m in matches}
    bad = _targets(matches)[-1]
    cutoffs[bad.fixture_id] = bad.kickoff_at + timedelta(minutes=1)
    data = BacktestData(matches, features, {}, cutoffs, {}, {})
    with pytest.raises(LeakageError):
        run_elo_ologit(data, _targets(matches), cfg=CFG, refit_days=7)


def test_the_grid_is_extended_when_the_best_candidate_sits_on_its_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake model that improves with xi up to 0.016: the search must walk the
    grid out to it instead of stopping at the boundary it was given."""
    matches = _league()
    val = [m for m in matches if m.season == 2023]

    def fake(data: BacktestData, targets: list[MatchRecord], *, spec: GoalSpec, **_: object) -> ModelRun:
        run = ModelRun(spec.kind, spec.tag)
        sharp = 0.9 - abs(math.log2(max(spec.xi, 1e-6) / 0.016)) * 0.1 - abs(math.log(spec.penalty / 1.0)) * 0.01
        for m in targets:
            y = wf.outcome_index(m)
            p = [(1 - sharp) / 2] * 3
            p[y] = sharp
            run.predictions[m.fixture_id] = Prediction(m.fixture_id, spec.kind, m.kickoff_at, (p[0], p[1], p[2]),
                                                       (), "", 1)
        return run

    monkeypatch.setattr(wf, "run_goal_model", fake)
    spec, _, grid = select_goal_spec(_data(matches), CFG, "poisson")
    assert spec.xi == pytest.approx(0.016)
    assert max(grid["xi"]) >= 0.016 > max(CFG.xi_grid)
    assert val


def test_comparison_verdict_needs_the_whole_interval() -> None:
    rng = np.random.default_rng(0)
    y = {i: int(rng.integers(0, 3)) for i in range(400)}
    market = {i: np.array([0.45, 0.27, 0.28]) for i in y}
    same = compare(market, market, y, baseline_key="m", market_key="1X2", line=0.0)
    assert same is not None and same.verdict == "indistinguishable"
    oracle = {i: np.eye(3)[y[i]] * 0.9 + 0.1 / 3 for i in y}
    better = compare(oracle, market, y, baseline_key="m", market_key="1X2", line=0.0)
    assert better is not None and better.verdict == "better" and better.logloss_diff.hi < 0
    assert verdict(-0.01, -0.001) == "better" and verdict(0.001, 0.02) == "worse"
    assert verdict(-0.0, 0.0) == "indistinguishable"


def test_betting_simulation_arithmetic() -> None:
    matches = _targets(_league())[:3]
    run = ModelRun("m", "s")
    prices = {}
    market = {}
    for m in matches:
        p = (0.5, 0.25, 0.25)
        run.predictions[m.fixture_id] = Prediction(m.fixture_id, "m", m.kickoff_at - timedelta(hours=1), p,
                                                   (PredRow("1X2", "Home", 0.0, 0.5, None, None),), "", 1)
        prices[m.fixture_id] = {"Home": 2.2, "Draw": 3.5, "Away": 3.9}  # EV home = +10%
        market[m.fixture_id] = MarketTriplet(0.44, 0.28, 0.28, 1.03)
    data = BacktestData(matches, {}, {}, {}, {PRIMARY_BASELINE: market}, {BET_PRICE_KEY: prices})
    sim = simulate_bets(run, data, matches)
    assert BET_EV_THRESHOLD <= 0.10
    assert len(sim.bets) == 3 and all(b.selection == "Home" for b in sim.bets)
    wins = sum(1 for m in matches if wf.outcome_index(m) == 0)
    assert sim.profit == pytest.approx(wins * 1.2 - (3 - wins))
    assert sim.staked == 3.0
    assert sim.mean_probability_edge == pytest.approx(0.06)
