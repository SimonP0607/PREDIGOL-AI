"""RP-13.1: the board refuses what the plan refuses, and the frozen baseline reproduces itself."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from fbi.ops import before_after as ba

BASELINE = Path(__file__).resolve().parents[3] / "docs" / "intelligence" / "baseline" / "baseline-v1.json"


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def later(doc: dict[str, Any], **sections: list[dict[str, Any]]) -> dict[str, Any]:
    """The same measurement made later: the same definition and competitions, a later cut, some sections with new rows."""
    out = copy.deepcopy(doc)
    out["meta"]["cut_utc"] = "2026-12-20 03:00:00"
    for key, rows in sections.items():
        out["sections"][key]["rows"] = rows
    return out


def verdicts(board: dict[str, Any]) -> dict[int, str]:
    return {e["n"]: e["verdict"] for e in board["indicators"]}


def test_the_baseline_reproduces_itself_with_every_difference_zero(baseline: dict[str, Any]) -> None:
    board = ba.compare(baseline, baseline, allow_identical=True)
    assert board["comparable"] is True
    for e in board["indicators"]:
        for m in e["measures"]:
            assert m.get("difference", 0) == 0, (e["n"], m["key"])
    assert board["columns"][ba.IMPROVED] == [] and board["columns"][ba.WORSENED] == []
    assert {6, 14, 22} <= set(board["apart"][ba.NOT_MEASURED]), "what the baseline did not measure stays not measured"


def test_the_same_document_is_not_a_later_measurement_unless_asked(baseline: dict[str, Any]) -> None:
    board = ba.compare(baseline, baseline)
    assert board["comparable"] is False and all(v == ba.NOT_COMPARABLE for v in verdicts(board).values())


def test_a_different_definition_or_set_of_competitions_is_not_comparable(baseline: dict[str, Any]) -> None:
    other = later(baseline)
    other["definition_version"] = "intel-baseline-v2"
    board = ba.compare(baseline, other)
    assert not board["comparable"] and "definición distinta" in board["reasons"][0]
    assert set(verdicts(board).values()) == {ba.NOT_COMPARABLE}
    wider = later(baseline)
    wider["meta"]["base_before_utc"] = "2026-11-26 00:00:00"
    assert any("conjunto de competiciones" in r for r in ba.compare(baseline, wider)["reasons"])
    assert any("posterior" in r for r in ba.compare(baseline, baseline)["reasons"])


def test_a_difference_whose_interval_includes_zero_is_no_change_proven(baseline: dict[str, Any]) -> None:
    # I2: base +0.0113 (se 0.0020) over 3165 matches; after +0.0100 (se 0.0020): the difference, -0.0013, is well inside +-0.0055
    row = {"matches": "3000", "raw_minus_market": "0.0378", "raw_se": "0.0041", "shown_minus_market": "0.0100", "shown_se": "0.0020"}
    board = ba.compare(baseline, later(baseline, i01_i02_forecast_vs_market=[row]))
    i2 = next(e for e in board["indicators"] if e["n"] == 2)["measures"][0]
    assert i2["verdict"] == ba.NO_CHANGE and i2["reason"] == "el_intervalo_incluye_el_cero"
    assert i2["interval"][0] < 0 < i2["interval"][1]


def test_a_clear_improvement_and_a_clear_worsening_fall_in_their_columns(baseline: dict[str, Any]) -> None:
    row = {"matches": "3000", "raw_minus_market": "0.0378", "raw_se": "0.0041", "shown_minus_market": "-0.0100", "shown_se": "0.0020"}
    texts = [{"n": "2000", "pct_of_total": "90.0", "route": "none", "status": "ok"},
             {"n": "193", "pct_of_total": "10.0", "route": "none", "status": "partial"}]   # 91 % complete, from 19.5 %
    runs = [{"runs": "30000", "status": "completed"}, {"runs": "400", "status": "aborted"}, {"runs": "300", "status": "interrupted"}]
    board = ba.compare(baseline, later(baseline, i01_i02_forecast_vs_market=[row], i13_complete_texts=texts, i20_runs_by_status_7d=runs))
    v = verdicts(board)
    assert v[2] == ba.IMPROVED, "the shown forecast went from +0.0113 to -0.0100 (lower is better)"
    assert v[13] == ba.IMPROVED
    assert v[20] == ba.WORSENED, "from 189 aborted or interrupted runs to 700"
    assert 13 in board["columns"][ba.IMPROVED] and 20 in board["columns"][ba.WORSENED]
    i13 = next(e for e in board["indicators"] if e["n"] == 13)["measures"][0]
    assert i13["meets_threshold"] is False, "91 % complete does not reach the 98 % threshold, improved or not"


def test_a_figure_without_a_way_to_an_interval_is_never_called_better(baseline: dict[str, Any]) -> None:
    cheaper = [{"cost_usd": "20.0", "cost_without_fixture": "0.5", "fixtures": "669", "usd_per_fixture": "0.0300"}]
    board = ba.compare(baseline, later(baseline, i15_cost_per_analyzed_match=cheaper))
    i15 = next(e for e in board["indicators"] if e["n"] == 15)["measures"][0]
    assert i15["verdict"] == ba.NO_CHANGE and i15["reason"] == "sin_intervalo" and i15["difference"] < 0
    assert i15["meets_threshold"] is True, "it did not rise, which is the plan's threshold, and the report says so apart from the verdict"


def test_the_indicators_with_no_goal_are_only_informed(baseline: dict[str, Any]) -> None:
    v = verdicts(ba.compare(baseline, baseline, allow_identical=True))
    assert v[5] == ba.INFORMED and v[17] == ba.INFORMED


def test_a_figure_missing_after_is_not_measured_not_zero(baseline: dict[str, Any]) -> None:
    board = ba.compare(baseline, later(baseline, i08_research_coverage_played=[]))
    assert verdicts(board)[8] == ba.NOT_MEASURED


def test_the_proportion_interval_is_newcombe_over_wilson() -> None:
    a = ba.Measure("p", 0.2, successes=20, n=100, direction=ba.HIGHER)
    b = ba.Measure("p", 0.2, successes=200, n=1000, direction=ba.HIGHER)
    diff, low, high = ba.difference_interval(a, b) or (0, 0, 0)
    assert diff == 0 and low < 0 < high
    c = ba.Measure("p", 0.5, successes=500, n=1000, direction=ba.HIGHER)
    diff, low, high = ba.difference_interval(a, c) or (0, 0, 0)
    assert diff == pytest.approx(0.3) and low > 0.2 and high < 0.4


def test_every_indicator_has_a_threshold_a_reader_and_pieces_that_can_move_it(baseline: dict[str, Any]) -> None:
    numbers = {int(i["n"]) for i in baseline["indicators"]}
    assert numbers == set(range(1, 23)) == set(ba.THRESHOLDS) == set(ba.READERS) == set(ba.ATTRIBUTION)
    assert all(ba.ATTRIBUTION[n] for n in numbers)


def test_the_thresholds_approved_before_measuring_are_pinned() -> None:
    """D7: the criteria were approved before any measurement and are not changed afterwards to favour a result. A change here is a decision of
    the owner, written in the plan: this fingerprint is then changed on purpose, in the open."""
    assert ba.thresholds_fingerprint() == "406aa9e0a65c751a52966619727553815e1faec7bfcff6726449288ce2b6fc96"
