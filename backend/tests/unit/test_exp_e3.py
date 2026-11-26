"""RP-9.3 (EXP-E3): the daily calibration (only the past), the over/under reading and the verdict on simulated selections. Pure."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from fbi.research import exp_e3 as e3
from fbi.research import exp_protocol

THRESHOLDS = exp_protocol.THRESHOLDS["EXP-E3"]
SIGNED = date(2026, 11, 26)


def test_the_calibrator_recovers_a_known_distortion_and_needs_both_outcomes_and_enough_points() -> None:
    rng = np.random.default_rng(3)
    true = rng.uniform(0.2, 0.8, 4000)
    stated = 1 / (1 + np.exp(-1.6 * np.log(true / (1 - true))))  # the model is over-confident: it stretches the log odds by 1.6
    y = (rng.random(4000) < true).astype(int)
    coef = e3.platt(stated.tolist(), y.tolist())
    assert coef is not None and abs(coef[0]) < 0.15 and coef[1] == pytest.approx(1 / 1.6, abs=0.08)
    assert e3.platt([0.5] * 99, [0, 1] * 49 + [0]) is None, "fewer than MIN_TRAIN points"
    assert e3.platt([0.5] * 200, [1] * 200) is None, "an outcome that is always the same"
    assert e3.apply((0.0, 1.0), 0.7) == pytest.approx(0.7)


def sel(i: int, day: date, p: float, q: float, over: int, family: str = "córneres") -> e3.Selection:
    return e3.Selection(i, family, day, p, q, over)


def world(days: int, per_day: int, *, seed: int = 1, noise: float = 0.0) -> list[e3.Selection]:
    """Selections whose market is the truth and whose raw model is the truth stretched (so calibrating it recovers the truth)."""
    rng = np.random.default_rng(seed)
    out: list[e3.Selection] = []
    start = SIGNED - timedelta(days=30)
    for d in range(days):
        for k in range(per_day):
            true = float(rng.uniform(0.25, 0.75))
            stated = float(1 / (1 + np.exp(-1.5 * np.log(true / (1 - true)) - noise * rng.normal())))
            out.append(sel(d * per_day + k, start + timedelta(days=d), stated, true, int(rng.random() < true)))
    return out


def test_a_day_is_calibrated_only_on_the_days_before_it_and_the_past_includes_what_came_before_the_signature() -> None:
    rows = world(60, 20)
    scored, skipped = e3.calibrated(rows, after=SIGNED)
    days = sorted({s.day for s, _ in scored["córneres"]})
    assert days[0] == SIGNED + timedelta(days=1) and skipped == 0, "the first scored day is the day after the signature, trained on the 30 days before it"
    # nothing of a day changes when a LATER day changes: the calibrated figures of a day depend on the earlier days only
    changed = [s if s.day <= SIGNED + timedelta(days=5) else sel(s.fixture, s.day, s.p, s.q, 1 - s.over) for s in rows]
    other, _ = e3.calibrated(changed, after=SIGNED)
    first = {s.fixture: c for s, c in scored["córneres"] if s.day <= SIGNED + timedelta(days=5)}
    second = {s.fixture: c for s, c in other["córneres"] if s.day <= SIGNED + timedelta(days=5)}
    assert first == second


def test_a_day_with_no_calibrator_is_not_scored_and_is_counted() -> None:
    rows = [sel(i, SIGNED + timedelta(days=1), 0.6, 0.5, 1) for i in range(10)]
    scored, skipped = e3.calibrated(rows, after=SIGNED)
    assert scored["córneres"] == [] and skipped == 10


def test_a_calibrated_model_that_is_the_market_is_a_success_in_its_family_and_with_too_few_selections_nothing_is_declared() -> None:
    rows = world(150, 16)
    j, pop = e3.judge(rows, after=SIGNED, required=1500, thresholds=THRESHOLDS, seed=5)
    assert pop["families"]["córneres"]["n"] > 1500 and pop["families"]["tarjetas"]["n"] == 0
    assert j.verdict == "exito" and "córneres" in j.reason and j.mean < 0.005
    short, pop2 = e3.judge(world(60, 10), after=SIGNED, required=1500, thresholds=THRESHOLDS, seed=5)
    assert short.verdict == "insuficiente" and pop2["families"]["córneres"]["verdict"] is None


def test_a_model_far_from_the_market_does_not_succeed_and_abandons_only_with_both_families() -> None:
    rows = world(150, 16, noise=2.0)
    j, pop = e3.judge(rows, after=SIGNED, required=1500, thresholds=THRESHOLDS, seed=5)
    assert pop["families"]["córneres"]["verdict"] == "abandono" and j.verdict == "insuficiente", "cards have no sample yet: the experiment goes on"
    both = rows + [sel(10_000 + s.fixture, s.day, s.p, s.q, s.over, "tarjetas") for s in rows]
    j2, _ = e3.judge(both, after=SIGNED, required=1500, thresholds=THRESHOLDS, seed=5)
    assert j2.verdict == "abandono" and j2.low >= 0.005
