"""The bets of a half, derived from two fitted halves (plan F10). Every derivation is held to a closed form (Poisson halves have one) or to a
brute-force enumeration of the four counts of a match: the goals of each side in each half."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from fbi.families import derive, halves
from fbi.families.counts import MAX_COUNT, nb_pmf
from fbi.families.fit import NO_DISPERSION, Dispersion, Prediction, prediction

FIRST = (0.55, 0.40)
SECOND = (0.70, 0.55)


def _poisson(mu: float, k: int) -> float:
    return math.exp(-mu) * mu**k / math.factorial(k)


def _pred(means: tuple[float, float], d: Dispersion = NO_DISPERSION) -> Prediction:
    return prediction(means[0], means[1], d)


def _enumerate(first: tuple[float, float], second: tuple[float, float], kmax: int = 10) -> dict[str, float]:
    """HT/FT cells and the highest scoring half by summing over the four counts (means are small: the mass beyond ``kmax`` is ~1e-10)."""
    cells = dict.fromkeys(halves.HTFT_LABELS, 0.0)
    best = {"first": 0.0, "tie": 0.0, "second": 0.0}

    def sign(d: int) -> str:
        return "1" if d > 0 else ("X" if d == 0 else "2")

    for h1, a1, h2, a2 in itertools.product(range(kmax + 1), repeat=4):
        p = _poisson(first[0], h1) * _poisson(first[1], a1) * _poisson(second[0], h2) * _poisson(second[1], a2)
        cells[f"{sign(h1 - a1)}/{sign(h1 + h2 - a1 - a2)}"] += p
        g1, g2 = h1 + a1, h2 + a2
        best["first" if g1 > g2 else ("tie" if g1 == g2 else "second")] += p
    mass = sum(cells.values())
    return {**{k: v / mass for k, v in cells.items()}, **{f"best_{k}": v / mass for k, v in best.items()}}


def test_half_time_full_time_equals_an_enumeration_of_the_four_counts() -> None:
    got = halves.half_time_full_time(_pred(FIRST), _pred(SECOND))
    expected = _enumerate(FIRST, SECOND)
    assert set(got) == set(halves.HTFT_LABELS)
    for label in halves.HTFT_LABELS:
        assert got[label] == pytest.approx(expected[label], abs=1e-8), label
    assert sum(got.values()) == pytest.approx(1.0, abs=1e-12)


def test_half_time_full_time_has_the_two_results_as_its_marginals() -> None:
    first, second = _pred(FIRST), _pred(SECOND)
    cells = halves.half_time_full_time(first, second)
    ht = derive.result(first)
    ft = derive.result(halves.full_time(first, second))
    for i, s in enumerate(halves.SIGNS):
        assert sum(cells[f"{s}/{t}"] for t in halves.SIGNS) == pytest.approx(ht[i], abs=1e-9)
        assert sum(cells[f"{t}/{s}"] for t in halves.SIGNS) == pytest.approx(ft[i], abs=1e-9)


def test_a_team_that_leads_at_half_time_usually_wins_and_never_more_than_it_should() -> None:
    cells = halves.half_time_full_time(_pred(FIRST), _pred(SECOND))
    assert cells["1/1"] > cells["1/X"] > cells["1/2"] > 0.0
    assert cells["2/2"] > cells["2/X"] > cells["2/1"] > 0.0


def test_highest_scoring_half_equals_an_enumeration() -> None:
    first, second = _pred(FIRST), _pred(SECOND)
    got = halves.highest_scoring_half(first.pmf_total, second.pmf_total)
    expected = _enumerate(FIRST, SECOND)
    assert got == pytest.approx((expected["best_first"], expected["best_tie"], expected["best_second"]), abs=1e-8)
    assert sum(got) == pytest.approx(1.0, abs=1e-12)
    # the second half has more goals, so it is the likelier highest
    assert got[2] > got[0]


def test_highest_scoring_half_of_one_side_uses_that_side_only() -> None:
    first, second = _pred(FIRST), _pred(SECOND)
    got = halves.highest_scoring_half(first.pmf_home, second.pmf_home)
    mass = 0.0
    tie = 0.0
    for i, j in itertools.product(range(12), repeat=2):
        p = _poisson(FIRST[0], i) * _poisson(SECOND[0], j)
        mass += p
        tie += p if i == j else 0.0
    assert got[1] == pytest.approx(tie / mass, abs=1e-8)


def test_adding_up_two_poisson_halves_gives_the_poisson_of_the_sum() -> None:
    ft = halves.full_time(_pred(FIRST), _pred(SECOND))
    assert (ft.mean_home, ft.mean_away) == pytest.approx((FIRST[0] + SECOND[0], FIRST[1] + SECOND[1]))
    expected_home = nb_pmf(FIRST[0] + SECOND[0], 0.0, MAX_COUNT)
    assert ft.pmf_home[: MAX_COUNT + 1] == pytest.approx(expected_home / expected_home.sum(), abs=1e-9)
    total = nb_pmf(sum(FIRST) + sum(SECOND), 0.0, 2 * MAX_COUNT)
    assert ft.pmf_total[: 2 * MAX_COUNT + 1] == pytest.approx(total / total.sum(), abs=1e-9)
    assert float(ft.pmf_total.sum()) == pytest.approx(1.0, abs=1e-12)


def test_the_menu_has_stable_keys_and_each_group_adds_up() -> None:
    m = halves.menu(_pred(FIRST), _pred(SECOND))
    assert m["ht_1"] + m["ht_x"] + m["ht_2"] == pytest.approx(1.0)
    assert m["h2_1"] + m["h2_x"] + m["h2_2"] == pytest.approx(1.0)
    assert m["best_first"] + m["best_tie"] + m["best_second"] == pytest.approx(1.0)
    htft = [v for k, v in m.items() if k.startswith("htft_")]
    assert len(htft) == 9 and sum(htft) == pytest.approx(1.0)
    assert {"btts_1h", "btts_2h", "odd_1h", "odd_2h", "ou_1h_0.5", "ou_1h_1.5", "ou_1h_2.5", "ou_2h_0.5", "ou_2h_2.5"} <= set(m)
    assert all(0.0 <= v <= 1.0 + 1e-12 for v in m.values())
    # the over of a higher line is never likelier than the over of a lower one
    assert m["ou_1h_0.5"] > m["ou_1h_1.5"] > m["ou_1h_2.5"]
    assert m["ou_2h_0.5"] > m["ou_2h_1.5"] > m["ou_2h_2.5"]
    # the second half is the one with more goals
    assert m["ou_2h_1.5"] > m["ou_1h_1.5"]


def test_over_dispersed_halves_keep_every_identity() -> None:
    d = Dispersion(0.25, 0.25, 0.25)
    first, second = _pred(FIRST, d), _pred(SECOND, d)
    cells = halves.half_time_full_time(first, second)
    assert sum(cells.values()) == pytest.approx(1.0, abs=1e-12)
    ht = derive.result(first)
    assert sum(cells[f"1/{t}"] for t in halves.SIGNS) == pytest.approx(ht[0], abs=1e-9)
    # more variance than a Poisson of the same mean: more goalless halves
    assert float(first.pmf_total[0]) > math.exp(-sum(FIRST))
    m = halves.menu(first, second)
    assert m["best_first"] + m["best_tie"] + m["best_second"] == pytest.approx(1.0)


def test_the_prediction_helper_is_what_a_fitted_model_returns() -> None:
    pred = _pred(FIRST)
    assert isinstance(pred, Prediction)
    assert float(pred.pmf_home.sum()) == pytest.approx(1.0) and float(pred.pmf_total.sum()) == pytest.approx(1.0)
    assert np.asarray(pred.pmf_total).size == 2 * MAX_COUNT + 1
