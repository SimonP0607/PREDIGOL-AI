"""PM-09-06: the expected table with the provider's xG - the Poisson outcome of a match against an independent computation (SciPy's
Skellam), the expected points and their variance, the order of the table, the gate of the matrix and the switch (off by default)."""

from __future__ import annotations

import math

import pytest
from scipy.stats import skellam

from fbi.stats import expected_table as xt


@pytest.mark.parametrize("a,b", [(0.4, 2.7), (1.0, 1.0), (1.5, 0.9), (3.2, 0.3), (0.05, 0.05), (4.8, 2.1)])
def test_the_outcome_is_the_skellam_of_the_two_xg(a: float, b: float) -> None:
    win, draw, loss = xt.outcome(a, b)
    assert win + draw + loss == pytest.approx(1, abs=1e-9)
    assert win == pytest.approx(float(skellam.sf(0, a, b)), abs=1e-9)
    assert draw == pytest.approx(float(skellam.pmf(0, a, b)), abs=1e-9)
    assert xt.outcome(b, a) == pytest.approx((loss, draw, win), abs=1e-12)


def test_expected_points_and_their_variance() -> None:
    assert xt.expected_points(0.0, 0.0) == (1.0, 0.0)  # no chance for either side: a draw for sure
    mean, var = xt.expected_points(1.5, 0.9)
    win, draw, _ = xt.outcome(1.5, 0.9)
    assert mean == pytest.approx(3 * win + draw)
    assert var == pytest.approx(9 * win + draw - mean**2)
    with pytest.raises(ValueError):
        xt.outcome(-0.1, 1.0)


def test_the_table_sums_each_team_and_orders_it() -> None:
    played = [xt.Played(1, 10, 20, 0, 1, 2.0, 0.5), xt.Played(2, 20, 30, 2, 2, 1.0, 1.0), xt.Played(3, 30, 10, 3, 0, 0.6, 1.8)]
    lines = xt.table(played, {10: "Diez", 20: "Veinte", 30: "Treinta"})
    by = {x.team_id: x for x in lines}
    assert [x.matches for x in lines] == [2, 2, 2]
    assert by[10].points == 0 and by[20].points == 4 and by[30].points == 4
    assert by[10].xpts == pytest.approx(xt.expected_points(2.0, 0.5)[0] + xt.expected_points(1.8, 0.6)[0])
    assert by[10].xg_for == pytest.approx(3.8) and by[10].xg_against == pytest.approx(1.1)
    assert by[10].margin95 == pytest.approx(1.96 * math.sqrt(xt.expected_points(2.0, 0.5)[1] + xt.expected_points(1.8, 0.6)[1]))
    assert lines[0].team_id == 10  # the most expected points goes first, whatever the real points
    assert [x.xpts for x in lines] == sorted((x.xpts for x in lines), reverse=True)
    j = lines[0].as_json()
    assert j["points_minus_xpts"] == round(0 - lines[0].xpts, 2) and set(j) >= {"xpts", "margin95", "xgd"}
    # same expected points: the expected goal difference decides, then the name
    tie = xt.table([xt.Played(4, 1, 2, 0, 0, 1.0, 1.0)], {1: "B", 2: "A"})
    assert [x.name for x in tie] == ["A", "B"]


def test_the_gate_of_the_matrix() -> None:
    assert xt.gate("A", "league") == "visible" and xt.gate("B", "league") == "visible"
    assert xt.gate("C", "league") == "sin_cobertura" and xt.gate("D", "league") == "sin_cobertura"
    assert xt.gate("MI", "league") == "sin_cobertura"
    assert xt.gate(None, "league") == "sin_medir"
    assert xt.gate("A", "cup") == "no_es_liga"


def test_a_match_without_both_xg_is_left_out_and_counted() -> None:
    rows: list[dict[str, object]] = [{"id": 1, "home_team_id": 1, "away_team_id": 2, "goals_home": 1, "goals_away": 0, "xg_home": 1.2, "xg_away": None},
            {"id": 2, "home_team_id": 1, "away_team_id": 2, "goals_home": 1, "goals_away": 0, "xg_home": 1.2, "xg_away": 0.4}]
    played, missing = xt.played_of(rows)
    assert missing == 1 and [m.fixture_id for m in played] == [2]


def test_the_switch_is_off_by_default_and_the_label_names_the_provider() -> None:
    assert xt.mode({}) == "off" and xt.mode({"FBI_EXPECTED_TABLE": "0"}) == "off"
    assert xt.mode({"FBI_EXPECTED_TABLE": "1"}) == "on"
    assert xt.LABEL == "xG de API-Football" and "no un pronóstico" in xt.FORMULA
