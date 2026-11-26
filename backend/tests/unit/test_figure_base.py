"""What a stated figure rests on and the weights of the calibrator behind it (RP-2.1, ``figure-base-v1``)."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from fbi.forecasting import figure_base as fb
from fbi.forecasting import match_forecast as mf
from fbi.intel.calibration import Calibrator, apply_params
from tests.unit.test_match_forecast import LINE_1X2, LINE_OU, logit2, platt, rows, state

SEEN = datetime(2026, 10, 22, 11, 0, tzinfo=UTC)


def test_the_weights_are_the_coefficients_apply_params_uses() -> None:
    assert fb.weights_of("identity", {}) == (0.0, 1.0, 0.0)
    assert fb.weights_of("platt", {"a": -0.1, "b": 0.8}) == (-0.1, 0.8, 0.0)
    assert fb.weights_of("logit2", {"a": 0.1, "b": 0.5, "c": 0.7}) == (0.1, 0.5, 0.7)
    with pytest.raises(ValueError, match="unknown"):
        fb.weights_of("magic", {})
    # and they are what the number is: the formula of the label reproduces the calibrator's own output
    params = {"a": 0.1, "b": 0.5, "c": 0.7}
    a, b, c = fb.weights_of("logit2", params)
    p_model, p_market = 0.62, 0.55
    z = a + b * math.log(p_model / (1 - p_model)) + c * math.log(p_market / (1 - p_market))
    assert apply_params("logit2", params, p_model, p_market) == pytest.approx(1 / (1 + math.exp(-z)), abs=1e-9)


def test_the_label_follows_the_method() -> None:
    assert fb.base_of(None) == fb.Base("raw")
    assert fb.base_of("identity").label == fb.CALIBRATED_NO_MARKET
    assert fb.base_of("platt", {"a": 0.0, "b": 1.0}).label == fb.CALIBRATED_NO_MARKET
    assert fb.base_of("logit2", {"a": 0.0, "b": 0.5, "c": 0.5}) == fb.Base(fb.CALIBRATED_WITH_MARKET, "logit2", 0.0, 0.5, 0.5)
    assert fb.MARKET in fb.LABELS and fb.MARKET not in fb.STATED, "the market's own number is never the stated figure"


def test_a_champion_that_was_not_applied_leaves_the_figure_raw() -> None:
    champion = Calibrator("OU", "dixon_coles", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5}, 3, "CHAMPION")
    assert fb.of_champion(champion, applied=False) == fb.UNCALIBRATED_BASE
    assert fb.of_champion(None, applied=True) == fb.UNCALIBRATED_BASE
    assert fb.of_champion(champion, applied=True).label == fb.CALIBRATED_WITH_MARKET


def test_a_stored_row_gets_the_label_from_what_it_already_says() -> None:
    assert fb.label_of_stored("UNCALIBRATED", None) == fb.RAW
    assert fb.label_of_stored("CALIBRATED", "platt") == fb.CALIBRATED_NO_MARKET
    assert fb.label_of_stored("CALIBRATED", "logit2") == fb.CALIBRATED_WITH_MARKET


def test_the_forecast_of_a_market_carries_its_base_() -> None:
    nothing = mf.forecast_market(1, "1X2", LINE_1X2, {"elo_ologit": rows("elo_ologit", "1X2")}, state(), {})
    assert nothing is not None and nothing.base == fb.UNCALIBRATED_BASE
    champion = platt("1X2", "elo_ologit", ident=11)
    corrected = mf.forecast_market(1, "1X2", LINE_1X2, {"elo_ologit": rows("elo_ologit", "1X2")}, state({("1X2", "elo_ologit"): champion}), {})
    assert corrected is not None and corrected.base == fb.Base(fb.CALIBRATED_NO_MARKET, "platt", -0.1, 0.8, 0.0)
    market = {"Over": (0.55, SEEN), "Under": (0.45, SEEN)}
    leaning = mf.forecast_market(1, "OU", LINE_OU, {"dc": rows("dc", "OU")}, state({("OU", "dc"): logit2("OU", "dc")}), market)
    assert leaning is not None and leaning.base == fb.Base(fb.CALIBRATED_WITH_MARKET, "logit2", 0.0, 0.5, 0.5)
    assert leaning.base.as_json() == {"label": "calibrated_with_market", "method": "logit2", "intercept": 0.0, "w_model": 0.5, "w_market": 0.5}
    assert nothing.base.as_json() == {"label": "raw"}
