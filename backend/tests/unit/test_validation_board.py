"""AD-K02 (IA-113): the validation board - each measure against a case worked by hand, and no verdict the protocol does not allow."""

from __future__ import annotations

import itertools
import math
from datetime import UTC, date, datetime, timedelta

import pytest

from fbi.evaluation import board
from fbi.evaluation.board import Scored
from fbi.research import protocol

D0 = date(2026, 11, 1)


def item(i: int, *, p: float = 0.6, hit: int | None = 1, p_market: float | None = 0.5, clv: float | None = 0.1, taken: bool = True,
         market: str = "OU", days: int = 30) -> Scored:
    return Scored("decision-v1", "core", market, D0 + timedelta(days=i % days), p, "calibrada", hit, p_market, clv, taken)


def test_ece_against_a_case_by_hand() -> None:
    # bin 5: (0.55, 1), (0.55, 0) -> pred 0.55, observed 0.5 ; bin 8: (0.85, 1) -> pred 0.85, observed 1.0
    e, bins = board.ece([(0.55, 1), (0.55, 0), (0.85, 1)])
    assert e == pytest.approx((2 * 0.05 + 1 * 0.15) / 3)
    assert [(b["bin"], b["pred_pct"], b["observed_pct"], b["n"]) for b in bins] == [(5, 55.0, 50.0, 2), (8, 85.0, 100.0, 1)]
    assert board.ece([]) == (None, [])
    assert board.ece([(1.0, 1)])[1][0]["bin"] == 9


def test_the_mean_and_its_interval_resample_whole_days_and_repeat_for_a_seed() -> None:
    values = [(D0 + timedelta(days=d), float(d)) for d in range(10) for _ in range(3)]
    mean, lo, hi = board.by_day_mean_ci(values, level=0.95, seed=7)
    assert mean == pytest.approx(4.5) and lo is not None and hi is not None and lo < 4.5 < hi
    assert board.by_day_mean_ci(values, level=0.95, seed=7) == (mean, lo, hi)
    wider = board.by_day_mean_ci(values, level=0.999, seed=7)
    assert wider[1] is not None and wider[2] is not None and wider[1] <= lo and wider[2] >= hi
    assert board.by_day_mean_ci([(D0, 1.0), (D0, 3.0)], level=0.95, seed=1) == (2.0, None, None)
    assert board.by_day_mean_ci([], level=0.95, seed=1) == (None, None, None)


def test_the_log_loss_against_the_market_is_paired_on_the_same_selections() -> None:
    items = [item(i, p=0.6, hit=1, p_market=0.5) for i in range(40)]
    g = board.group(items, level=0.95, seed=3, needed=10)
    assert g["log_loss"]["diff_vs_market"] == pytest.approx(round(-math.log(0.6) + math.log(0.5), 6))
    assert g["brier"]["diff_vs_market"] == pytest.approx(round(0.16 - 0.25, 6))
    assert g["checks"]["supera_al_mercado"] is True


def test_below_the_needed_sample_the_verdict_is_insufficient_whatever_the_measures() -> None:
    word, failed = board.verdict(299, {"supera_al_mercado": True, "calibrada": True, "supera_la_vara": True})
    assert (word, failed) == ("INSUFICIENTE", [])


def test_validated_only_when_every_rule_holds_and_an_unmeasured_rule_is_a_failure() -> None:
    for values in itertools.product((True, False, None), repeat=3):
        checks = dict(zip(board.CHECKS, values, strict=True))
        word, failed = board.verdict(300, checks)
        assert (word == "VALIDADO") == all(v is True for v in values)
        assert failed == [c for c in board.CHECKS if checks[c] is not True]


def test_the_yardstick_is_the_price_rules_and_the_protocol_says_the_same_numbers() -> None:
    p = protocol.require("AD-K02")
    assert (board.VARA_MEAN, board.VARA_LOW, board.VARA_HIGH) == (0.0577, 0.0528, 0.0624)
    assert "+6,24 %" in p.pass_rule and "+5,77 % [5,28; 6,24] en 2.705" in p.pass_rule
    assert board.NEEDED == 300 and "300 selecciones" in p.min_sample and str(board.REPLICATES).replace("000", ".000") in p.primary_metric
    assert board.ECE_MAX == 0.03 and "≤ 0,03" in p.pass_rule and board.BINS == 10 and "10 tramos" in p.pass_rule


def test_a_clv_that_does_not_beat_the_yardstick_is_not_validated() -> None:
    good = [item(i, p=0.62, hit=i % 5 != 0, p_market=0.5, clv=0.05) for i in range(400)]
    g = board.group(good, level=0.95, seed=1)
    assert g["checks"]["supera_la_vara"] is False and g["verdict"] == "NO_VALIDADO" and "supera_la_vara" in g["failed"]


def test_the_board_judges_only_what_the_layer_would_take_and_counts_the_candidates() -> None:
    items = [item(i, taken=False) for i in range(500)] + [item(i) for i in range(20)]
    b = board.build(items)
    cell = next(c for c in b["cells"] if c["market"] == "OU")
    assert cell["candidates"] == 520 and cell["sample"] == 20 and cell["verdict"] == "INSUFICIENTE"
    assert b["bonferroni"]["m"] == 0 and b["counts"]["VALIDADO"] == 0


def test_bonferroni_counts_the_groups_that_reach_the_sample_before_any_interval() -> None:
    items = [item(i, market="OU") for i in range(300)] + [item(i, market="AH") for i in range(300)] + [item(i, market="DC") for i in range(5)]
    b = board.build(items)
    assert b["bonferroni"]["m"] == 3  # OU, AH and the family as a whole; DC does not reach it
    assert b["bonferroni"]["level"] == round(1 - 0.05 / 3, 6)


def test_no_validated_cell_breaks_the_protocol_on_a_world_that_beats_everything() -> None:
    """A world built to pass every rule: the verdict says VALIDADO only where the sample, the calibration, the market and the yardstick
    all hold - and the board still activates nothing (it is a dictionary, it is never signed by itself)."""
    items = []
    for i in range(600):
        hit = 1 if (i // 30) % 10 < 7 else 0  # 70 % on every day
        items.append(item(i, p=0.7, hit=hit, p_market=0.5, clv=0.12))
    b = board.build(items)
    assert b["counts"]["VALIDADO"] == 2  # the market and its family
    for c in b["cells"]:
        if c["verdict"] == "VALIDADO":
            assert c["sample"] >= c["needed"] and all(c["checks"][k] is True for k in board.CHECKS)
    assert b["signed_by_owner"] is False and b["protocol"]["fingerprint"] == protocol.fingerprint(protocol.require("AD-K02"))


def test_a_row_of_the_table_reads_as_a_scored_item() -> None:
    row = {"layer": "decision-fam-v1", "family": "corners", "market_key": "CORNERS_OU", "kickoff_at": datetime(2026, 11, 2, 3, 0, tzinfo=UTC),
           "p_judged": 0.55, "seal": "sin_calibrar", "hit": None, "p_market": None, "clv": None, "taken": False}
    s = board.scored_of(row)
    assert s.day == date(2026, 11, 1) and not s.complete and s.taken is False  # 03:00 UTC is still the 1st in Bogotá
