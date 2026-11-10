"""The common probability view (plan PICKS, F3, option B): decision-v2 carries it as a measurement, and the replay says how far each
probability is from it. What is held: the view is the Match Center's own function (a complete market that adds up to one, calibrated only
with a champion and a fresh price), carrying it changes no decision, and the numbers of the summary are the ones the rows say."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from fbi.decision import engine, replay
from fbi.decision import view as common
from fbi.forecasting.market_view import MARKETS, Row, Source, forecast_market
from fbi.intel.calibration import CalibrationState, Calibrator

from .test_decision_v2_engine import AT, KEY, MODEL, core, pick, world

SELECTIONS = MARKETS[("1X2", Decimal(0))]
CUT = AT - timedelta(hours=2)


def rows(model: str = MODEL, ps: tuple[float, ...] = (0.50, 0.30, 0.20), version: int = 3) -> list[Row]:
    return [Row(s, Source(model, version, CUT, "h", p, p - 0.05, p + 0.05, 0.0)) for s, p in zip(SELECTIONS, ps, strict=True)]


def nothing() -> CalibrationState:
    return CalibrationState(champions={}, best={}, wf={}, edge={})


def champion(method: str = "identity") -> CalibrationState:
    params = {"a": 0.1, "b": 0.8, "c": 0.3} if method == "logit2" else {}
    cal = Calibrator("1X2", MODEL, method, params, id=5, role="CHAMPION")
    return CalibrationState(champions={("1X2", MODEL): cal}, best={("1X2", MODEL): cal}, wf={}, edge={})


def market_of(ps: tuple[float, ...]) -> dict[str, tuple[float, Any]]:
    return {s: (p, AT - timedelta(minutes=30)) for s, p in zip(SELECTIONS, ps, strict=True)}


def test_without_a_champion_the_view_is_the_models_own_number_and_says_so() -> None:
    f = forecast_market(77, "1X2", Decimal(0), {MODEL: rows()}, nothing(), {})
    assert f is not None and (f.calibration, f.basis) == ("UNCALIBRATED", "no_champion")
    assert [round(o.p, 6) for o in f.outcomes] == [0.5, 0.3, 0.2] and abs(sum(o.p for o in f.outcomes) - 1) < 1e-9


def test_a_champion_that_needs_the_price_does_not_calibrate_without_one() -> None:
    f = forecast_market(77, "1X2", Decimal(0), {MODEL: rows()}, champion("logit2"), {})
    assert f is not None and (f.calibration, f.basis) == ("UNCALIBRATED", "needs_price")
    assert [round(o.p, 6) for o in f.outcomes] == [0.5, 0.3, 0.2]  # the model's number, not a dressed-up one


def test_a_calibrated_view_adds_up_to_one_whatever_the_calibrator_does_to_each_outcome() -> None:
    f = forecast_market(77, "1X2", Decimal(0), {MODEL: rows()}, champion("logit2"), market_of((0.45, 0.30, 0.25)))
    assert f is not None and f.calibration == "CALIBRATED"
    assert abs(sum(o.p for o in f.outcomes) - 1) < 1e-9 and all(0 < o.p < 1 for o in f.outcomes)


def test_the_readings_are_keyed_like_a_candidate_with_every_outcome_of_the_market() -> None:
    f = forecast_market(77, "1X2", Decimal(0), {MODEL: rows()}, nothing(), {})
    assert f is not None
    found = common.readings({(77, "1X2", Decimal(0)): f})
    assert set(found) == {(77, "1X2", s, Decimal("0.00")) for s in SELECTIONS}  # also the outcomes decision-v1 never flagged
    home = found[KEY]
    assert (home.model, home.calibration, home.basis, home.version) == (MODEL, "UNCALIBRATED", "no_champion", "forecast-v1")
    assert home.p == 0.5 and home.low is not None and home.high is not None and home.low < home.p < home.high


def test_carrying_the_view_changes_no_decision() -> None:
    w = world()
    cands = [core({MODEL: pick()})]
    f = forecast_market(77, "1X2", Decimal(0), {MODEL: rows()}, nothing(), {})
    assert f is not None
    views = common.readings({(77, "1X2", Decimal(0)): f})
    plain = engine.decide_all(w, cands)
    carried = engine.decide_all(w, cands, views=views)
    assert [(d.state, d.codes, d.reason, d.score) for d in plain] == [(d.state, d.codes, d.reason, d.score) for d in carried]
    assert plain[0].common is None and carried[0].common is not None and carried[0].common.p == 0.5
    assert carried[0].as_json()["common"]["calibration"] == "UNCALIBRATED" and plain[0].as_json()["common"] is None


def view_of(p: float, *, model: str = MODEL, calibration: str = "CALIBRATED") -> engine.CommonView:
    return engine.CommonView(p, p, model, calibration, "champion" if calibration == "CALIBRATED" else "needs_price", None, None, None, CUT, None,
                             "forecast-v1")


def row(p_cal: float | None, *, model: str = MODEL) -> dict[str, Any]:
    return {"p_cal": p_cal, "model_name": model}


def test_the_causes_of_a_gap_are_told_apart_in_a_fixed_order() -> None:
    assert replay.common_cause(row(0.5, model="poisson"), view_of(0.5)) == "different_model"
    assert replay.common_cause(row(0.5, model="poisson"), view_of(0.5, calibration="UNCALIBRATED")) == "different_model"
    assert replay.common_cause(row(0.5), view_of(0.5, calibration="UNCALIBRATED")) == "view_uncalibrated"
    assert replay.common_cause(row(0.5), view_of(0.5)) == "calibration"


def test_the_summary_counts_what_the_rows_say_and_leaves_out_what_has_no_reading() -> None:
    items: list[tuple[dict[str, Any], engine.CommonView | None, float | None]] = [
        (row(0.500), view_of(0.503), 0.500),  # 0.3 pp: the same number
        (row(0.500), view_of(0.560), 0.500),  # 6 pp, same model, calibrated
        (row(0.500, model="poisson"), view_of(0.600), None),  # another model: 10 pp
        (row(0.500), view_of(0.520, calibration="UNCALIBRATED"), 0.5),  # the view is the model's own number: 2 pp
        (row(None), view_of(0.4), None),  # decision-v1 has no calibrated probability: has a reading, nothing to compare
        (row(0.5), None, 0.5),  # a market the view does not cover
    ]
    s = replay.common_summary(items)
    assert (s["rows"], s["with_view"], s["with_v1_probability"], s["within_tolerance"]) == (6, 5, 4, 1)
    assert s["max_pp"] == 10.0 and s["tolerance_pp"] == 0.5
    assert s["view_calibration"] == {"CALIBRATED": 4, "UNCALIBRATED": 1}
    assert {c: v["selections"] for c, v in s["causes"].items()} == {"different_model": 1, "view_uncalibrated": 1, "calibration": 2}
    assert s["causes"]["different_model"]["max_pp"] == 10.0 and s["causes"]["calibration"]["over_tolerance"] == 1


def test_an_empty_summary_has_no_figures_not_zeros() -> None:
    s = replay.common_summary([])
    assert s["rows"] == 0 and s["median_pp"] is None and s["max_pp"] is None and s["within_tolerance"] == 0
