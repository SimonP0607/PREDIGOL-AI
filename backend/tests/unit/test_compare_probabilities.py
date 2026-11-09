"""The row-by-row comparison of probabilities (plan PICKS, F3): what it measures, on rows whose answer is known."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from scripts.compare_probabilities import (
    build_table,
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
