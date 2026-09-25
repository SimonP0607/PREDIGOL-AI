"""The families added for pre-upgrade research: base rates, multinomial logistic,
and the evaluation that judges them (RPS, match-day block bootstrap,
Diebold-Mariano, detectable difference, evidence labels).

The walk-forward discipline is tested the same way as for the goal models:
rewrite the future and require the past to come out identical.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from fbi.backtesting import walkforward as wf
from fbi.backtesting.data import BacktestData
from fbi.backtesting.evaluate import EQUIVALENCE_MARGIN, Comparison, Diff, compare, score
from fbi.backtesting.walkforward import (
    WalkForwardConfig,
    known_before,
    outcome_index,
    run_base_rates,
    run_mnlogit,
)
from fbi.features.engine import LeakageError
from fbi.models import families
from fbi.models.logistic import fit_logistic
from fbi.models.metrics import (
    block_bootstrap_ci,
    diebold_mariano,
    minimum_detectable_difference,
    paired_bootstrap_ci,
    per_match_rps,
    rps,
)
from tests.unit.test_backtest_protocol import COMP, _league, _targets

CFG = WalkForwardConfig(competition_ids=(COMP,), refit_days=7, validation_refit_days=28, interval_draws=50)


# --------------------------------------------------------------------------- logistic


def _softmax_rows(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return np.asarray(e / e.sum(axis=1, keepdims=True))


def test_logistic_recovers_the_generating_probabilities() -> None:
    rng = np.random.default_rng(5)
    n = 20000
    x = rng.normal(0, 1, (n, 2))
    w = np.array([[1.2, 0.0], [0.0, 0.0], [-1.2, 0.4]])
    b = np.array([0.3, 0.0, -0.1])
    p = _softmax_rows(x @ w.T + b)
    y = np.array([rng.choice(3, p=row) for row in p])
    model = fit_logistic(x.tolist(), y.tolist(), features=("a", "b"), l2=1.0)
    assert model.converged and model.n_train == n
    probe = rng.normal(0, 1, (200, 2))
    truth = _softmax_rows(probe @ w.T + b)
    fitted = np.array([model.predict(list(r)) for r in probe])
    assert np.abs(fitted - truth).max() < 0.03
    assert np.allclose(fitted.sum(axis=1), 1.0)


def test_logistic_imputes_the_training_mean_and_refuses_wrong_shapes() -> None:
    rng = np.random.default_rng(1)
    rows: list[list[float | None]] = [[float(v), None if i % 5 == 0 else float(-v)]
                                      for i, v in enumerate(rng.normal(0, 1, 300))]
    y = [0 if r[0] is not None and r[0] > 0.3 else 2 if r[0] is not None and r[0] < -0.3 else 1 for r in rows]
    model = fit_logistic(rows, y, features=("x", "z"))
    at_mean = model.predict([float(model.mean[0]), float(model.mean[1])])
    assert model.predict([float(model.mean[0]), None]) == pytest.approx(at_mean)
    with pytest.raises(ValueError):
        model.predict([0.0])
    with pytest.raises(ValueError):
        fit_logistic(rows[:8], y[:8], features=("x", "z"))
    with pytest.raises(ValueError):
        fit_logistic(rows, y, features=("x",))


def test_a_feature_missing_everywhere_is_neutral_not_a_crash() -> None:
    rows: list[list[float | None]] = [[float(i % 7) - 3, None] for i in range(200)]
    y = [i % 3 for i in range(200)]
    model = fit_logistic(rows, y, features=("x", "never"))
    assert model.converged
    assert model.weights[:, 1] == pytest.approx(np.zeros(3), abs=1e-9)


def test_the_family_registry_says_what_runs_and_why_the_rest_waits() -> None:
    active = {f.name for f in families.active()}
    assert active == {"base_rates", "poisson", "dixon_coles", "elo_ologit", "mnlogit"}
    for f in families.FAMILIES:
        assert f.registry_family in {"baseline", "rating", "goals", "ml", "ensemble"}
        if f.status == "planned":
            assert f.requirements, f"{f.name} is planned without saying what it waits for"
    assert families.get("mnlogit").features == families.MNLOGIT_FEATURES
    row = families.mnlogit_row({"elo_diff": 40.0, "pi_expected_gd": 0.3, "home_sot_share10": 0.6,
                                "away_sot_share10": 0.45, "home_rest_days": 20.0, "away_rest_days": 3.0,
                                "is_neutral": 0.0})
    assert len(row) == len(families.MNLOGIT_FEATURES)
    assert row[2] == pytest.approx(0.15)
    assert row[3] is None, "a missing input gives a missing derived feature, not zero"
    assert row[5] == 7.0, "rest difference is clipped at a week"
    with pytest.raises(KeyError):
        families.get("gnn")


# --------------------------------------------------------------------------- base rates


def test_base_rates_are_laplace_frequencies_of_what_was_public() -> None:
    matches = _league()
    targets = _targets(matches)
    run = run_base_rates(BacktestData(matches, {}, {}, {}, {}, {}), targets, cfg=CFG, refit_days=7)
    assert run.predictions
    first = min(run.predictions.values(), key=lambda p: p.data_cutoff)
    window = first.data_cutoff - timedelta(days=CFG.history_days)
    train = [m for m in matches if known_before(m, first.data_cutoff) and m.kickoff_at >= window]
    counts = np.bincount([outcome_index(m) for m in train], minlength=3) + 1.0
    assert first.p == pytest.approx(tuple(counts / counts.sum()))
    assert first.n_train == len(train)
    assert all(r.lo is None and r.hi is None for p in run.predictions.values() for r in p.rows)


def test_base_rates_cannot_see_the_future() -> None:
    matches = _league()
    targets = _targets(matches)
    split = targets[len(targets) // 2].kickoff_at
    poisoned = [replace(m, goals_home=0, goals_away=5) if m.kickoff_at >= split else m for m in matches]
    clean = run_base_rates(BacktestData(matches, {}, {}, {}, {}, {}), targets, cfg=CFG, refit_days=7)
    dirty = run_base_rates(BacktestData(poisoned, {}, {}, {}, {}, {}), _targets(poisoned), cfg=CFG, refit_days=7)
    before = [fid for fid, p in clean.predictions.items() if p.data_cutoff <= split]
    assert before
    assert all(clean.predictions[f].p == dirty.predictions[f].p for f in before)


# --------------------------------------------------------------------------- mnlogit


def _featured(matches: list, *, shift: dict[int, timedelta] | None = None) -> BacktestData:
    rng = np.random.default_rng(9)
    feats: dict[int, dict[str, float | None]] = {}
    for m in matches:
        feats[m.fixture_id] = {
            "elo_diff": float((m.home_team_id - m.away_team_id) * 12 + rng.normal(0, 20)),
            "pi_expected_gd": float((m.home_team_id - m.away_team_id) * 0.05),
            "home_sot_share10": float(rng.uniform(0.3, 0.7)), "away_sot_share10": float(rng.uniform(0.3, 0.7)),
            "home_shot_share10": None, "away_shot_share10": None,
            "home_history_n": 60.0, "away_history_n": 60.0, "home_rest_days": 7.0, "away_rest_days": 6.0,
            "league_home_gd_avg": 0.3, "is_neutral": 0.0,
        }
    cutoffs = {m.fixture_id: m.kickoff_at - timedelta(hours=1) + (shift or {}).get(m.fixture_id, timedelta())
               for m in matches}
    return BacktestData(matches, feats, {m.fixture_id: f"h{m.fixture_id}" for m in matches}, cutoffs, {}, {})


def test_mnlogit_predicts_from_the_fixtures_own_features_and_never_the_future(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wf, "MIN_MNLOGIT_TRAIN", 60)
    matches = _league()
    targets = _targets(matches)
    clean = run_mnlogit(_featured(matches), targets, cfg=CFG, refit_days=7)
    assert len(clean.predictions) > 40
    for fid, p in clean.predictions.items():
        assert sum(p.p) == pytest.approx(1.0)
        assert p.input_hash == f"h{fid}", "the prediction names the feature set it was computed from"
    split = targets[len(targets) // 2].kickoff_at
    poisoned = [replace(m, goals_home=6, goals_away=0) if m.kickoff_at >= split else m for m in matches]
    dirty = run_mnlogit(_featured(poisoned), _targets(poisoned), cfg=CFG, refit_days=7)
    before = [fid for fid, p in clean.predictions.items() if p.data_cutoff <= split]
    assert before
    assert all(clean.predictions[f].p == dirty.predictions[f].p for f in before)


def test_mnlogit_refuses_a_feature_set_computed_after_kickoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wf, "MIN_MNLOGIT_TRAIN", 60)
    matches = _league()
    bad = _targets(matches)[-1]
    data = _featured(matches, shift={bad.fixture_id: timedelta(hours=2)})
    with pytest.raises(LeakageError):
        run_mnlogit(data, _targets(matches), cfg=CFG, refit_days=7)


def test_mnlogit_declines_without_the_required_features(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wf, "MIN_MNLOGIT_TRAIN", 60)
    matches = _league()
    data = _featured(matches)
    gap = _targets(matches)[-1]
    data.features[gap.fixture_id]["pi_expected_gd"] = None
    run = run_mnlogit(data, _targets(matches), cfg=CFG, refit_days=7)
    assert gap.fixture_id not in run.predictions
    assert (gap.fixture_id, "no feature set for this fixture") in run.uncovered


# --------------------------------------------------------------------------- metrics


def test_ranked_probability_score_values() -> None:
    p = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [1 / 3, 1 / 3, 1 / 3], [0.5, 0.5, 0.0]])
    y = np.array([0, 0, 1, 2])
    # last row: cumulative forecast (0.5, 1.0) against cumulative outcome (0, 0)
    expected = [0.0, 1.0, 1 / 9, (0.5 ** 2 + 1.0 ** 2) / 2]
    assert per_match_rps(p, y) == pytest.approx(expected)
    assert rps(p, y) == pytest.approx(np.mean(expected))


def test_block_bootstrap_with_singleton_blocks_is_the_paired_bootstrap() -> None:
    rng = np.random.default_rng(2)
    a, b = rng.normal(1.0, 0.3, 500), rng.normal(1.02, 0.3, 500)
    mean, lo, hi, n_blocks = block_bootstrap_ci(a - b, list(range(500)))
    assert (mean, lo, hi) == pytest.approx(paired_bootstrap_ci(a, b))
    assert n_blocks == 500
    with pytest.raises(ValueError):
        block_bootstrap_ci(a - b, [0, 1])


def test_block_bootstrap_widens_when_matches_on_a_day_move_together() -> None:
    rng = np.random.default_rng(4)
    day_effect = np.repeat(rng.normal(0, 0.05, 60), 10)
    d = day_effect + rng.normal(0, 0.005, 600)
    days = np.repeat(np.arange(60), 10).tolist()
    _, lo_b, hi_b, n = block_bootstrap_ci(d, days)
    _, lo_i, hi_i, _ = block_bootstrap_ci(d, list(range(600)))
    assert n == 60
    assert (hi_b - lo_b) > 2.5 * (hi_i - lo_i), "ten matches that move together are one observation, not ten"


def test_diebold_mariano_sign_and_size() -> None:
    rng = np.random.default_rng(8)
    better = rng.normal(-0.02, 0.1, 2000)
    stat, p, lag = diebold_mariano(better)
    assert stat < 0 and p < 0.001 and lag >= 1
    stat0, p0, _ = diebold_mariano(rng.normal(0, 0.1, 2000))
    assert p0 > 0.01 and abs(stat0) < 3
    assert diebold_mariano(np.zeros(50)) == (0.0, 1.0, 3)
    with pytest.raises(ValueError):
        diebold_mariano([0.1] * 5)


def test_minimum_detectable_difference() -> None:
    z = 1.959963984540054 + 0.8416212335729143
    assert minimum_detectable_difference([0.0] * 10, se=0.01) == pytest.approx(z * 0.01)
    x = np.random.default_rng(3).normal(0, 0.2, 400)
    assert minimum_detectable_difference(x) == pytest.approx(z * x.std(ddof=1) / 20)
    assert minimum_detectable_difference([1.0]) == float("inf")


def _comparison(mean: float, lo: float, hi: float) -> Comparison:
    s = score(np.array([[0.5, 0.3, 0.2]]), np.array([0]))
    return Comparison("m", "1X2", 0.0, 1, s, s, Diff(mean, lo, hi), Diff(0.0, 0.0, 0.0))


def test_evidence_labels() -> None:
    assert _comparison(-0.01, -0.02, -0.001).evidence == "sufficient"
    assert _comparison(0.03, 0.02, 0.04).evidence == "sufficient"
    assert _comparison(0.001, -0.003, 0.004).evidence == "equivalent"
    assert _comparison(0.001, -0.02, 0.03).evidence == "insufficient"
    edge = _comparison(0.0, -EQUIVALENCE_MARGIN, EQUIVALENCE_MARGIN)
    assert edge.evidence == "equivalent"


def test_compare_blocks_by_day_and_reports_the_extras() -> None:
    rng = np.random.default_rng(6)
    y = {i: int(rng.integers(0, 3)) for i in range(300)}
    market = {i: np.array([0.45, 0.27, 0.28]) for i in y}
    noisy = {i: np.clip(market[i] + rng.normal(0, 0.02, 3), 0.01, None) for i in y}
    noisy = {i: v / v.sum() for i, v in noisy.items()}
    days: dict[int, object] = {i: f"2024-09-{1 + i // 30:02d}" for i in y}
    c = compare(noisy, market, y, baseline_key="m", market_key="1X2", line=0.0, blocks=days, order=days)
    assert c is not None and c.n_blocks == 10
    assert c.rps_model is not None and c.rps_baseline is not None and c.dm_p is not None
    assert c.mdd is not None and c.mdd > 0
    d = c.details()
    assert {"ci_method", "evidence", "dm_stat", "dm_p", "min_detectable_logloss_diff", "equivalence_margin",
            "rps_diff", "n_blocks"} <= set(d)
