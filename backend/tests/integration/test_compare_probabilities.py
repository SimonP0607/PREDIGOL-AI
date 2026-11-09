"""The row-by-row comparison on a live database (plan PICKS, F3): the example picks of test_pick_states, read three ways."""

# ruff: noqa: F811  (pytest fixtures imported from test_pick_states are used by name as parameters)
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from scripts.compare_probabilities import collect

from tests.integration.helpers import scalar
from tests.integration.test_pick_states import NOW, World, world  # noqa: F401
from tests.integration.test_picks_source import P_CAL, decide, decided  # noqa: F401

pytestmark = pytest.mark.integration


def forecast(world: World, name: str, p: Decimal) -> None:
    fid = world.fixtures[name]
    version = scalar(world.db.execute("SELECT model_version_id FROM picks.picks WHERE id = %s", (world.picks[name],)))
    world.db.execute(
        "INSERT INTO models.match_forecasts (version, known_at, fixture_id, family, market_key, selection, line, model_name, "
        "model_version_id, data_cutoff_ts, p_model, p, calibration, basis, input_hash, code_version) VALUES ('forecast-v1', %s, %s, "
        "'RESULT', '1X2', 'Home', 0, 'dixon_coles', %s, %s, %s, %s, 'UNCALIBRATED', 'no_champion', %s, 'c')",
        (NOW - timedelta(hours=2), fid, version, NOW - timedelta(hours=3), p, p, f"fc-{name}"))


def test_the_comparison_reads_the_four_numbers_and_says_whether_the_criterion_holds(decided: World) -> None:
    forecast(decided, "A", P_CAL)  # the Match Center says what Intelligence says
    forecast(decided, "B", Decimal("0.60"))  # and here it does not: 12 points above Intelligence's reading
    f = collect(decided.db, hours=48, top=5, now=NOW)
    assert f["selections"] >= 5 and f["with_intelligence"] == 5 and f["with_forecast"] == 2
    # the board with the switch IS Intelligence's reading, selection by selection: the criterion between them is met by construction
    assert f["pairs"]["board_switch~intel"]["over_tolerance"] == 0
    assert f["pairs"]["board_raw~intel"]["over_tolerance"] == 5  # 0.50 against 0.48: two points on each of the five
    assert f["pairs"]["forecast~intel"]["selections"] == 2 and f["pairs"]["forecast~intel"]["over_tolerance"] == 1
    assert f["verdict"]["comparable"] is True and f["verdict"]["holds"] is False
    assert f["widest"][0]["selection"] == "Home" and f["widest"][0]["gap_pp"] == 12.0
    assert f["checkpoints"]["by_checkpoint"] == {"T-3h": 5}


def test_when_the_match_center_agrees_everywhere_the_criterion_holds(decided: World) -> None:
    for name in ("A", "B", "C", "D", "S"):
        forecast(decided, name, P_CAL)
    f = collect(decided.db, hours=48, top=5, now=NOW)
    assert f["verdict"] == {"tolerance_pp": 0.5, "comparable": True, "holds": True,
                            "board_vs_intelligence_over": 0, "match_center_vs_board_over": 0}


def test_nothing_to_compare_is_not_a_pass(world: World) -> None:
    f = collect(world.db, hours=48, top=5, now=NOW)
    assert f["with_intelligence"] == 0 and f["verdict"]["comparable"] is False and f["verdict"]["holds"] is False
