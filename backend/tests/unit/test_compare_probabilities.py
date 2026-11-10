"""The row-by-row comparison of probabilities (plan PICKS, F3): what it measures, on rows whose answer is known."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from scripts.compare_probabilities import (
    CAUSES,
    attribution,
    build_table,
    cause_of,
    checkpoint_figures,
    gaps,
    summarize,
    verdict,
    worst,
)

from fbi.api.services.picks_decision import RAW_MARK

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def board(fixture: int, selection: str, raw: str, shown: str, market: str = "1X2", line: str = "0") -> dict[str, Any]:
    return {"fixture_id": fixture, "market_key": market, "selection": selection, "line": Decimal(line),
            RAW_MARK: Decimal(raw), "p_model": Decimal(shown)}


def decision(fixture: int, selection: str, p_cal: str | None, market: str = "1X2", line: str = "0",
             checkpoint: str = "T-3h", age_h: float = 2) -> dict[str, Any]:
    return {"fixture_id": fixture, "market_key": market, "selection": selection, "line": Decimal(line),
            "p_cal": None if p_cal is None else Decimal(p_cal), "checkpoint": checkpoint, "known_at": NOW - timedelta(hours=age_h)}


def forecast(fixture: int, selection: str, p: str, market: str = "1X2", line: str = "0") -> dict[str, Any]:
    return {"fixture_id": fixture, "market_key": market, "selection": selection, "line": Decimal(line), "p": Decimal(p)}


def test_the_table_has_the_four_readings_of_each_selection() -> None:
    t = build_table([board(1, "Home", "0.60", "0.52")], [decision(1, "Home", "0.52")], [forecast(1, "Home", "0.55")])
    assert t[(1, "1X2", "Home", Decimal(0))] == {
        "board_raw": Decimal("0.60"), "board_switch": Decimal("0.52"), "intel": Decimal("0.52"), "forecast": Decimal("0.55")}


def test_a_source_with_nothing_for_the_selection_is_none_not_zero() -> None:
    t = build_table([board(1, "Home", "0.60", "0.60")], [decision(1, "Home", None)], [])
    row = t[(1, "1X2", "Home", Decimal(0))]
    assert row["intel"] is None and row["forecast"] is None
    assert gaps(t, "board_raw", "intel") == [] and gaps(t, "forecast", "board_switch") == []


def test_a_selection_priced_by_two_models_counts_once() -> None:
    t = build_table([board(1, "Home", "0.60", "0.52"), board(1, "Home", "0.70", "0.52")], [], [])
    assert len(t) == 1 and t[(1, "1X2", "Home", Decimal(0))]["board_raw"] == Decimal("0.60")


def test_gaps_are_in_points_and_widest_first() -> None:
    t = build_table([board(1, "Home", "0.60", "0.52"), board(1, "Away", "0.20", "0.25")],
                    [decision(1, "Home", "0.52"), decision(1, "Away", "0.25")], [])
    found = gaps(t, "board_raw", "intel")
    assert [k[2] for k, _ in found] == ["Home", "Away"]
    assert [float(g) for _, g in found] == [8.0, 5.0]


def test_the_summary_counts_what_is_over_the_tolerance() -> None:
    t = build_table([board(1, "Home", "0.50", "0.50"), board(1, "Draw", "0.30", "0.30"), board(1, "Away", "0.20", "0.20")],
                    [decision(1, "Home", "0.504"), decision(1, "Draw", "0.30"), decision(1, "Away", "0.30")], [])
    s = summarize(gaps(t, "board_switch", "intel"))
    assert s["selections"] == 3 and s["over_tolerance"] == 1  # only the 10-point gap; 0.4 pp is inside half a point
    assert s["max_pp"] == 10.0 and s["median_pp"] == 0.4
    assert summarize([])["selections"] == 0 and summarize([])["median_pp"] is None


def test_the_verdict_holds_only_when_nothing_is_over_the_tolerance_and_there_is_something_to_compare() -> None:
    same = {"board_switch~intel": {"selections": 4, "over_tolerance": 0}, "forecast~board_switch": {"selections": 4, "over_tolerance": 0}}
    assert verdict(same)["holds"] is True
    wide = {"board_switch~intel": {"selections": 4, "over_tolerance": 0}, "forecast~board_switch": {"selections": 4, "over_tolerance": 1}}
    assert verdict(wide)["holds"] is False
    empty = {"board_switch~intel": {"selections": 0, "over_tolerance": 0}, "forecast~board_switch": {"selections": 0, "over_tolerance": 0}}
    v = verdict(empty)
    assert v["holds"] is False and v["comparable"] is False  # nothing compared is not a pass


def test_the_checkpoint_figures_say_where_and_how_old_the_reading_is() -> None:
    f = checkpoint_figures([decision(1, "Home", "0.5", checkpoint="T-3h", age_h=2), decision(2, "Home", "0.5", checkpoint="T-1h", age_h=4),
                            decision(3, "Home", None, checkpoint="T-1h")], NOW)
    assert f["readings"] == 2 and f["by_checkpoint"] == {"T-3h": 1, "T-1h": 1}
    assert f["age_hours_median"] == 3.0 and f["age_hours_max"] == 4.0
    assert checkpoint_figures([], NOW) == {"readings": 0, "by_checkpoint": {}, "age_hours_median": None, "age_hours_max": None}


def test_the_widest_gaps_list_every_number_of_the_selection() -> None:
    t = build_table([board(1, "Home", "0.60", "0.52"), board(2, "Over", "0.70", "0.65", market="OU", line="2.5")],
                    [decision(1, "Home", "0.52"), decision(2, "Over", "0.65", market="OU", line="2.5")],
                    [forecast(1, "Home", "0.55"), forecast(2, "Over", "0.50", market="OU", line="2.5")])
    w = worst(t, top=1)
    assert len(w) == 1 and w[0]["fixture_id"] == 2 and w[0]["gap_pp"] == 15.0
    assert (w[0]["board_raw"], w[0]["board_switch"], w[0]["intel"], w[0]["forecast"]) == (0.7, 0.65, 0.65, 0.5)


def fc(fixture: int, selection: str, p: str, *, model: str = "dixon_coles", calibration: str = "CALIBRATED",
       basis: str = "champion", age_h: float = 2) -> dict[str, Any]:
    return {**forecast(fixture, selection, p), "model_name": model, "calibration": calibration, "basis": basis,
            "known_at": NOW - timedelta(hours=age_h)}


def dec(fixture: int, selection: str, p_cal: str, *, id: int = 1, age_h: float = 2) -> dict[str, Any]:
    return {**decision(fixture, selection, p_cal, age_h=age_h), "id": id}


def test_the_causes_are_told_apart_in_a_fixed_order() -> None:
    d = dec(1, "Home", "0.50")
    assert cause_of(fc(1, "Home", "0.55", model="poisson"), d, "dixon_coles") == "different_model"
    # another model wins over every other reason: the gap would be there however it were calibrated
    assert cause_of(fc(1, "Home", "0.55", model="poisson", calibration="UNCALIBRATED", age_h=40), d, "dixon_coles") == "different_model"
    assert cause_of(fc(1, "Home", "0.55", calibration="UNCALIBRATED"), d, "dixon_coles") == "forecast_uncalibrated"
    assert cause_of(fc(1, "Home", "0.55", age_h=30), d, "dixon_coles") == "different_moment"
    assert cause_of(fc(1, "Home", "0.55"), d, "dixon_coles") == "calibration"


def test_a_decision_whose_model_is_unknown_is_not_blamed_on_the_model() -> None:
    assert cause_of(fc(1, "Home", "0.55", model="poisson"), dec(1, "Home", "0.50"), None) == "calibration"


def test_the_moment_limit_is_six_hours_either_way() -> None:
    d = dec(1, "Home", "0.50", age_h=10)
    assert cause_of(fc(1, "Home", "0.55", age_h=4), d, "dixon_coles") == "calibration"  # six hours apart exactly
    assert cause_of(fc(1, "Home", "0.55", age_h=3.9), d, "dixon_coles") == "different_moment"  # forecast newer
    assert cause_of(fc(1, "Home", "0.55", age_h=16.1), d, "dixon_coles") == "different_moment"  # forecast older


def test_each_gap_counts_once_under_its_first_cause() -> None:
    forecasts = [fc(1, "Home", "0.60", model="poisson"), fc(2, "Home", "0.58", calibration="UNCALIBRATED", basis="needs_price"),
                 fc(3, "Home", "0.55", age_h=30), fc(4, "Home", "0.504")]
    decisions = [dec(i, "Home", "0.50", id=i) for i in (1, 2, 3, 4)]
    models = {1: "dixon_coles", 2: "dixon_coles", 3: "dixon_coles", 4: "dixon_coles"}
    t = build_table([board(i, "Home", "0.50", "0.50") for i in (1, 2, 3, 4)], decisions, forecasts)
    a = attribution(forecasts, decisions, models, t)
    assert a["compared"] == 4 and set(a["causes"]) == set(CAUSES)
    assert {c: v["selections"] for c, v in a["causes"].items()} == {
        "different_model": 1, "forecast_uncalibrated": 1, "different_moment": 1, "calibration": 1}
    assert a["causes"]["different_model"]["max_pp"] == 10.0 and a["causes"]["different_model"]["over_tolerance"] == 1
    assert a["causes"]["calibration"]["over_tolerance"] == 0  # 0.4 points: inside the half point
    assert a["forecast_basis"] == {"champion": 3, "needs_price": 1}


def test_a_cause_without_selections_has_no_figures_not_zeros() -> None:
    a = attribution([], [], {}, {})
    assert a["compared"] == 0 and all(v == {"selections": 0, "median_pp": None, "max_pp": None, "over_tolerance": 0}
                                      for v in a["causes"].values())


def test_selections_missing_a_reading_are_left_out_of_the_attribution() -> None:
    forecasts = [fc(1, "Home", "0.60")]
    decisions = [dec(2, "Home", "0.50", id=2)]
    t = build_table([board(1, "Home", "0.50", "0.50"), board(2, "Home", "0.50", "0.50")], decisions, forecasts)
    assert attribution(forecasts, decisions, {2: "dixon_coles"}, t)["compared"] == 0
