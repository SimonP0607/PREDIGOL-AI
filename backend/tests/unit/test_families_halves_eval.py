"""Grading the derived bets of the halves (plan F10): the outcomes are read right, the menu and the outcomes speak of the same keys, a world
made of independent halves is graded as one (and the model beats the competition's average when the teams differ), and a world whose
second half leans on the first shows up in the residual correlation, where the assumption of the derivation would break."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from fbi.families import evaluate_halves, halves
from fbi.families.evaluate import walk_forward
from fbi.families.fit import NO_DISPERSION, Match, prediction

T0 = datetime(2023, 8, 1, 15, 0, tzinfo=UTC)
N_TEAMS = 14


def _league(seasons: int = 8, seed: int = 31, lean: float = 0.0) -> tuple[list[Match], list[Match]]:
    """The two halves of a double round robin per season with known strengths. ``lean`` > 0 makes the second half's goals depend on what the
    first half produced (a match that opens with goals goes on having them), which independent halves cannot do."""
    rng = np.random.default_rng(seed)
    attack = rng.normal(0.0, 0.35, N_TEAMS)
    defence = rng.normal(0.0, 0.35, N_TEAMS)
    attack -= attack.mean()
    defence -= defence.mean()
    first: list[Match] = []
    second: list[Match] = []
    fid = day = 0
    for _ in range(seasons):
        for h in range(N_TEAMS):
            for a in range(N_TEAMS):
                if h == a:
                    continue
                fid += 1
                day += 1
                kick = T0 + timedelta(days=day)
                m1h = float(np.exp(np.log(0.55) + 0.15 + attack[h] - defence[a]))
                m1a = float(np.exp(np.log(0.45) + attack[a] - defence[h]))
                y1h, y1a = int(rng.poisson(m1h)), int(rng.poisson(m1a))
                boost = 1.0 + lean * (y1h + y1a - 1.0)
                m2h = max(0.05, float(np.exp(np.log(0.75) + 0.15 + attack[h] - defence[a])) * boost)
                m2a = max(0.05, float(np.exp(np.log(0.62) + attack[a] - defence[h])) * boost)
                first.append(Match(fid, kick, h + 1, a + 1, y1h, y1a))
                second.append(Match(fid, kick, h + 1, a + 1, int(rng.poisson(m2h)), int(rng.poisson(m2a))))
    return first, second


def _evaluate(first: list[Match], second: list[Match]) -> dict[str, object]:
    start = first[len(first) // 2].kickoff_at
    end = first[-1].kickoff_at + timedelta(days=1)
    ev1 = walk_forward({1: first}, measure="goals_1h", start=start, end=end, xi=0.0, penalty=1.0)
    ev2 = walk_forward({1: second}, measure="goals_2h", start=start, end=end, xi=0.0, penalty=1.0)
    return evaluate_halves.evaluate(ev1, ev2)


def test_the_outcomes_of_a_match_are_read_half_by_half() -> None:
    o = evaluate_halves.outcomes((1, 0), (1, 2))  # 1-0 at half-time, 2-2 at full time
    assert o["ht_1"] == 1.0 and o["ht_x"] == 0.0 and o["ht_2"] == 0.0
    assert o["h2_2"] == 1.0 and o["h2_1"] == 0.0
    assert o["htft_1_x"] == 1.0 and sum(o[k] for k in evaluate_halves.GROUPS["htft"]) == 1.0
    assert o["best_second"] == 1.0 and o["best_first"] == 0.0 and o["best_tie"] == 0.0  # 1 goal in the first half, 3 in the second
    assert o["btts_1h"] == 0.0 and o["btts_2h"] == 1.0
    assert (o["ou_1h_0.5"], o["ou_1h_1.5"]) == (1.0, 0.0) and (o["ou_2h_2.5"], o["ou_2h_1.5"]) == (1.0, 1.0)
    assert o["odd_1h"] == 1.0 and o["odd_2h"] == 1.0


def test_a_goalless_match_is_the_draw_everywhere_and_the_tie_of_the_halves() -> None:
    o = evaluate_halves.outcomes((0, 0), (0, 0))
    assert o["ht_x"] == o["h2_x"] == o["htft_x_x"] == o["best_tie"] == 1.0
    assert o["btts_1h"] == o["btts_2h"] == o["odd_1h"] == o["ou_1h_0.5"] == 0.0


def test_the_menu_and_the_outcomes_speak_of_the_same_keys() -> None:
    pred = prediction(0.5, 0.4, NO_DISPERSION)
    assert set(halves.menu(pred, pred)) == set(evaluate_halves.outcomes((0, 0), (1, 1)))
    for keys in evaluate_halves.GROUPS.values():
        assert all(k in halves.menu(pred, pred) for k in keys)


def test_in_a_world_of_independent_halves_the_model_beats_the_average_and_the_halves_are_uncorrelated() -> None:
    first, second = _league()
    r = _evaluate(first, second)
    assert isinstance(r["n"], int) and r["n"] > 400
    markets = r["markets"]
    assert isinstance(markets, dict)
    for name in ("result_1h", "result_2h", "htft"):
        gain = markets[name]
        assert gain["gain"] > 2.0 * gain["gain_se"] and gain["gain"] > 0.0, (name, gain)
    corr = r["halves_residual_correlation"]
    assert isinstance(corr, dict)
    assert abs(corr["r"]) < 4.0 * corr["se"], f"independent halves must not look dependent: {corr}"
    means = r["mean_goals"]
    assert isinstance(means, dict) and means["second_half"] > means["first_half"]


def test_the_cells_of_half_time_full_time_are_calibrated_when_the_halves_are_independent() -> None:
    first, second = _league(seasons=10, seed=7)
    r = _evaluate(first, second)
    cells = r["htft_calibration"]
    assert isinstance(cells, list) and len(cells) == 9
    assert sum(c["mean_predicted"] for c in cells) == pytest.approx(1.0, abs=1e-9)
    assert sum(c["observed"] for c in cells) == pytest.approx(1.0, abs=1e-9)
    n = r["n"]
    assert isinstance(n, int)
    for c in cells:
        se = (max(c["observed"], 0.01) * (1 - max(c["observed"], 0.01)) / n) ** 0.5
        assert abs(c["mean_predicted"] - c["observed"]) < 5.0 * se + 0.01, c


def test_a_second_half_that_leans_on_the_first_shows_in_the_correlation_of_the_halves() -> None:
    first, second = _league(seasons=10, seed=12, lean=0.35)
    r = _evaluate(first, second)
    corr = r["halves_residual_correlation"]
    assert isinstance(corr, dict)
    assert corr["r"] > 5.0 * corr["se"], f"dependent halves must be seen: {corr}"


def test_with_nothing_in_common_there_is_nothing_to_grade() -> None:
    a, _b = _league(seasons=2)
    start = a[len(a) // 2].kickoff_at
    ev1 = walk_forward({1: a}, measure="goals_1h", start=start, end=a[-1].kickoff_at + timedelta(days=1), xi=0.0, penalty=1.0)
    ev2 = walk_forward({}, measure="goals_2h", start=start, end=start + timedelta(days=30))
    assert evaluate_halves.evaluate(ev1, ev2) == {"n": 0}
