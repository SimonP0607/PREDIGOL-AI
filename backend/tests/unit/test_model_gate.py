"""The model gate reads evidence, not hopes: a model that scores well but has not
been reproduced, or does not beat the market, does not leave RESEARCH."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

import numpy as np

from fbi.backtesting.data import BacktestData, MarketTriplet
from fbi.backtesting.evaluate import PRIMARY_BASELINE, evaluate_session
from fbi.backtesting.walkforward import Block, ModelRun, Prediction, PredRow, outcome_index
from fbi.features.data import MatchRecord
from fbi.research.gate import CHECKS, _halves, evaluate_gate, status_for
from tests.unit.test_backtest_protocol import _league, _targets


def _run(name: str, targets: list[MatchRecord], prob: Callable[[MatchRecord], tuple[float, float, float]]
         ) -> ModelRun:
    run = ModelRun(name, "test")
    for m in targets:
        p = prob(m)
        cutoff = m.kickoff_at - timedelta(hours=1)
        run.predictions[m.fixture_id] = Prediction(
            m.fixture_id, name, cutoff, p,
            tuple(PredRow("1X2", s, 0.0, p[k], None, None) for k, s in enumerate(("Home", "Draw", "Away"))), "h", 100)
        run.blocks.append(Block(cutoff, (), None, (m.fixture_id,), m.kickoff_at))
    run.train_from, run.train_to = targets[0].kickoff_at - timedelta(days=300), targets[-1].kickoff_at
    return run


def _setup() -> tuple[BacktestData, list[MatchRecord]]:
    matches = _league()
    targets = _targets(matches)
    market = {m.fixture_id: MarketTriplet(0.45, 0.27, 0.28, 1.03) for m in targets}
    return BacktestData(matches, {}, {}, {}, {PRIMARY_BASELINE: market}, {}), targets


def _sharp(m: MatchRecord) -> tuple[float, float, float]:
    p = [0.1, 0.1, 0.1]
    p[outcome_index(m)] = 0.8
    return (p[0], p[1], p[2])


def test_a_model_that_beats_the_market_still_waits_for_reproduction() -> None:
    data, targets = _setup()
    evaluation = evaluate_session(data, targets, [_run("oracle", targets, _sharp)])
    ev = evaluation.models[0]
    gate = evaluate_gate(ev, evaluation, refit_days=1)
    assert set(gate["checks"]) == set(CHECKS)
    assert gate["checks"]["beats_market"]["passed"]
    assert gate["checks"]["out_of_sample"]["passed"] and gate["checks"]["temporal_validation"]["passed"]
    assert not gate["checks"]["reproducible"]["passed"]
    assert not gate["passed"] and status_for(gate) == "RESEARCH"
    again = evaluate_gate(ev, evaluation, refit_days=1, reproduced_by=42)
    assert again["checks"]["reproducible"]["passed"] and "42" in again["checks"]["reproducible"]["evidence"]


def test_the_market_itself_does_not_beat_the_market() -> None:
    data, targets = _setup()
    evaluation = evaluate_session(data, targets, [_run("copy", targets, lambda m: (0.45, 0.27, 0.28))])
    gate = evaluate_gate(evaluation.models[0], evaluation, refit_days=1, reproduced_by=1)
    assert not gate["checks"]["beats_market"]["passed"]
    assert "indistinguishable" in gate["checks"]["beats_market"]["evidence"]
    assert not gate["passed"] and status_for(gate) == "RESEARCH"


def test_no_market_means_no_pass() -> None:
    matches = _league()
    targets = _targets(matches)
    data = BacktestData(matches, {}, {}, {}, {}, {})
    evaluation = evaluate_session(data, targets, [_run("oracle", targets, _sharp)])
    gate = evaluate_gate(evaluation.models[0], evaluation, refit_days=1, reproduced_by=1)
    for name in ("calibrated", "stable", "beats_market"):
        assert not gate["checks"][name]["passed"]


def test_halves_are_weighted_by_fixtures() -> None:
    by_month = {"2024-08": {"n": 10.0, "logloss_diff": 0.1}, "2024-09": {"n": 30.0, "logloss_diff": -0.1},
                "2024-10": {"n": 40.0, "logloss_diff": 0.2}}
    first, second = _halves(by_month)
    assert first is not None and second is not None
    assert np.isclose(first, (10 * 0.1 + 30 * -0.1) / 40) and np.isclose(second, 0.2)
    assert _halves({}) == (None, None)
