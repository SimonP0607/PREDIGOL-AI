"""RP-9.7 (EXP-E7): the table of dependence between goals, corners and cards with its two halves and its stability mark. Pure: simulated matches."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from fbi.families import dependence
from fbi.families import exp_e7 as e7
from fbi.proposals import from_verdicts

T0 = datetime(2026, 1, 5, 15, tzinfo=UTC)


def world(n: int, *, tied: bool, seed: int = 4) -> list[dependence.Row]:
    """``n`` matches over four competitions and a year. Independent: goals, corners and cards are drawn separately. ``tied``: a match with many goals also has many
    cards (a real dependence inside every competition)."""
    rng = np.random.default_rng(seed)
    rows: list[dependence.Row] = []
    for i in range(n):
        competition = i % 4
        at = T0 + timedelta(hours=int(i * 24 * 330 / n))
        heat = float(rng.normal()) if tied else 0.0
        gh, ga = int(rng.poisson(max(0.2, 1.4 + 0.5 * heat))), int(rng.poisson(max(0.2, 1.2 + 0.5 * heat)))
        ch, ca = int(rng.poisson(5.0)), int(rng.poisson(4.5))
        kh, ka = int(rng.poisson(max(0.2, 2.0 + 1.2 * heat))), int(rng.poisson(max(0.2, 2.2 + 1.2 * heat)))
        rows.append(dependence.Row(i, competition, at, (gh, ga), (ch, ca), (kh, ka)))
    return rows


def test_the_family_pairs_are_those_of_the_protocol_and_an_event_pair_belongs_to_one() -> None:
    assert e7.FAMILY_PAIRS == ("goles-córneres", "goles-tarjetas", "córneres-tarjetas")
    assert e7.family_pair("goals.over_2_5", "corners.over_9_5") == "goles-córneres"
    assert e7.family_pair("corners.over_9_5", "cards.over_4_5") == "córneres-tarjetas"
    assert e7.family_pair("goals.btts", "cards.home_more") == "goles-tarjetas"


def test_the_halves_are_two_stretches_of_time_with_the_same_number_of_matches() -> None:
    rows = world(301, tied=False)
    first, second = e7.split(rows)
    assert (len(first), len(second)) == (150, 151) and max(r.kickoff_at for r in first) <= min(r.kickoff_at for r in second)


def test_independent_families_give_a_table_with_no_material_pair_and_a_success_that_only_says_it_was_measured() -> None:
    j, pop = e7.table(world(2400, tied=False), replicates=400)
    assert j.verdict == "exito" and "descriptivo" in j.reason and j.n == 2400
    assert set(pop["family_pairs"]) == set(e7.FAMILY_PAIRS) and pop["summary"]["pairs"] > 0
    assert pop["summary"][dependence.MATERIAL] <= 4, "nothing was put in: at most the pairs that chance puts outside the tolerance (96 pairs, 384 intervals)"
    assert not [t for t in pop["top"] if t["verdict"] == dependence.MATERIAL and t["stable"]], "and none of them repeats in both halves with its own interval"
    assert j.low <= j.mean <= j.high


def test_a_planted_dependence_is_a_material_pair_in_both_halves_and_is_marked_stable() -> None:
    j, pop = e7.table(world(2400, tied=True), replicates=400)
    assert j.verdict == "exito" and pop["summary"][dependence.MATERIAL] > 0
    tied = [t for t in pop["top"] if t["verdict"] == dependence.MATERIAL and t["stable"]]
    assert tied, "a dependence that is there in every competition and in both halves is stable"
    assert any(t["family_pair"] == "goles-tarjetas" for t in tied)


def test_too_few_matches_give_no_table_and_nothing_is_declared() -> None:
    j, pop = e7.table(world(100, tied=False), replicates=20)
    assert j.verdict == "insuficiente" and pop == {"matches": 100}


def test_the_success_of_a_descriptive_experiment_proposes_nothing() -> None:
    row = {"id": 1, "experiment": "EXP-E7", "verdict": "exito", "n": 9000, "mean": 1.1, "low": 1.0, "high": 1.2, "protocol_version": "proto-exp-e7-v1",
           "protocol_fingerprint": "a" * 64, "thresholds": {}, "population": {}, "computed_at": "2026-12-01"}
    assert from_verdicts([row]) == []
    assert len(from_verdicts([{**row, "experiment": "EXP-E1"}])) == 1
