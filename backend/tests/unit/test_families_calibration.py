"""Can a recalibration repair the over/under probabilities of a family? The check of ``fbi.families.evaluate`` (plan F10, "calibrador evaluado")."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from fbi.families import evaluate
from fbi.families.evaluate import Evaluation, Row
from fbi.families.fit import Dispersion

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def distorted(n: int, *, slope: float, shift: float, seed: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Probabilities, and outcomes drawn with the TRUE probability ``sigmoid(slope * logit(p) + shift)``."""
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.05, 0.95, n)
    q = 1 / (1 + np.exp(-(slope * np.log(p / (1 - p)) + shift)))
    return p, (rng.uniform(size=n) < q).astype(float)


def test_a_known_distortion_is_recovered() -> None:
    p, y = distorted(60000, slope=0.8, shift=-0.3)
    a, b = evaluate.recalibrate(p, y)
    assert abs(a - 0.8) < 0.05 and abs(b + 0.3) < 0.05
    only_shift_a, only_shift_b = evaluate.recalibrate(p, y, slope=False)
    assert only_shift_a == 1.0 and only_shift_b < 0.0, "a shift alone keeps the slope and moves the probabilities down"


def test_a_calibrated_forecast_is_left_alone() -> None:
    p, y = distorted(60000, slope=1.0, shift=0.0, seed=5)
    a, b = evaluate.recalibrate(p, y)
    assert abs(a - 1.0) < 0.05 and abs(b) < 0.05


def test_a_bet_that_always_or_never_happens_is_not_recalibrated() -> None:
    p = np.array([0.2, 0.4, 0.6])
    assert evaluate.recalibrate(p, np.zeros(3)) == (1.0, 0.0)
    assert evaluate.recalibrate(p, np.ones(3)) == (1.0, 0.0)
    assert evaluate.recalibrate(np.array([]), np.array([])) == (1.0, 0.0)


def test_the_calibration_error_is_the_gap_between_what_was_said_and_what_happened() -> None:
    p = np.full(100, 0.7)
    assert abs(evaluate.ece(p, np.array([1.0] * 50 + [0.0] * 50)) - 0.2) < 1e-12
    assert evaluate.ece(p, np.array([1.0] * 70 + [0.0] * 30)) < 1e-12


def evaluation(n: int, *, true_mean: float, said_mean: float, seed: int = 11) -> Evaluation:
    """``n`` predictions in the order they were played, Poisson counts around ``true_mean`` that the model said were around ``said_mean``."""
    rng = np.random.default_rng(seed)
    rows = [Row(i, 1, T0 + timedelta(hours=i), int(rng.poisson(true_mean)), int(rng.poisson(true_mean)), said_mean, said_mean, true_mean, true_mean)
            for i in range(n)]
    return Evaluation("cards_lines_ft", rows, 0, Dispersion(0.0, 0.0, 0.0), Dispersion(0.0, 0.0, 0.0))


def test_the_check_repairs_a_model_that_says_too_much_on_matches_it_did_not_fit() -> None:
    out = evaluate.calibration_check(evaluation(4000, true_mean=2.0, said_mean=2.6), lines=(4.5,), side_lines=(1.5,))
    assert out["n"] == 4000 and set(out["bets"]) == {"total 4.5", "home 1.5", "away 1.5"}
    assert out["fit_until"] == (T0 + timedelta(hours=1999)).isoformat(), "the first half of the matches, in the order they were played, fits"
    total = out["bets"]["total 4.5"]
    assert total["n_fit"] == 2000 and total["n_test"] == 2000
    assert total["mean_p"] > total["observed"] + 0.08, "the model said more than happened"
    assert total["ece"]["shift"] < total["ece"]["raw"] / 3 and total["ece"]["slope"] < total["ece"]["raw"] / 3
    gain = total["gain"]["shift"]
    assert gain["mean"] > 3 * gain["se"] > 0, "and the shift saves log loss on the matches that did not fit it"


def test_the_check_does_not_claim_a_gain_for_a_calibrated_model() -> None:
    out = evaluate.calibration_check(evaluation(4000, true_mean=2.0, said_mean=2.0, seed=13), lines=(4.5,), side_lines=())
    gain = out["bets"]["total 4.5"]["gain"]["slope"]
    assert abs(gain["mean"]) < 3 * gain["se"], "nothing to repair"


def test_too_few_predictions_are_not_split() -> None:
    out = evaluate.calibration_check(evaluation(2 * evaluate.MIN_CALIBRATION_TEST - 1, true_mean=2.0, said_mean=2.6), lines=(4.5,), side_lines=(1.5,))
    assert out == {"n": 2 * evaluate.MIN_CALIBRATION_TEST - 1, "bets": {}}
