"""RP-11.1 / RP-11.3: the owner's criterion for the joint of a parlay, registered before the prospective window is measured (``parlay-acceptance-v1``). Pure."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np

from fbi.parlays import acceptance as acc
from fbi.parlays import replay
from fbi.research.protocol import fingerprint

PINNED = "4680ee9da82b53c3358ba8d18d4a22c057df62e75a6d9b818bd9cc42694eddcd"
DAY0 = acc.FROZEN_ON


def parlays(n_days: int, per_day: int, *, said: float, true: float, seed: int = 5, start: date = DAY0) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    out: list[dict[str, Any]] = []
    for d in range(n_days):
        for _ in range(per_day):
            won = bool(rng.random() < true)
            out.append({"day": (start + timedelta(days=d)).isoformat(), "status": "WON" if won else "LOST", "p_joint": said, "p_market_joint": said - 0.05,
                        "p_product": said + 0.02, "p_joint_low": said / 2})
    return out


def test_the_protocol_is_registered_with_its_fingerprint_before_any_window_is_measured() -> None:
    assert fingerprint(acc.PROTOCOL) == PINNED, "changing the registered criterion is a visible diff and a new version"
    assert acc.PROTOCOL.registered_on == "2026-11-27" == acc.FROZEN_ON.isoformat()
    assert (acc.MAX_OPTIMISM, acc.MIN_DAYS, acc.MIN_SETTLED, acc.MIN_COMBINATIONS) == (0.02, 30, 100, 1500)
    assert acc.SAID == "p_joint" and acc.ESTIMATORS[0] == acc.SAID


def test_the_criterion_needs_optimism_of_two_points_or_less_and_an_interval_that_holds_zero() -> None:
    assert acc.judge_figures(optimism=0.01, low=-0.03, high=0.05)
    assert acc.judge_figures(optimism=0.02, low=-0.0, high=0.04), "two points exactly is inside; the interval's edge at zero holds it"
    assert not acc.judge_figures(optimism=0.021, low=-0.01, high=0.05), "above two points"
    assert not acc.judge_figures(optimism=0.01, low=0.002, high=0.03), "optimism that is significantly positive"
    assert not acc.judge_figures(optimism=-0.04, low=-0.07, high=-0.01), "a joint that is too pessimistic is not calibrated either"
    assert not acc.judge_figures(optimism=0.0, low=None, high=0.03) and not acc.judge_figures(optimism=0.0, low=-0.03, high=None)


def test_the_figures_of_the_historical_repetition_of_27_nov_do_not_pass_and_are_not_adjusted_to_pass() -> None:
    assert acc.historical(combinations=542018, optimism=0.0578, interval=(0.0252, 0.1110)) is False
    assert acc.historical(combinations=542018, optimism=0.0242, interval=(-0.0077, 0.0787)) is False, "the market's own reference is above two points too"
    assert acc.historical(combinations=1499, optimism=0.0, interval=(-0.01, 0.01)) is None, "fewer than 1,500 combinations decide nothing"
    assert acc.historical(combinations=2000, optimism=None, interval=None) is None
    assert acc.historical(combinations=2000, optimism=0.01, interval=None) is False, "no interval, no compatibility"
    assert acc.historical(combinations=2000, optimism=0.01, interval=(-0.02, 0.03)) is True


def test_the_replay_report_now_carries_the_verdict_it_used_to_leave_to_the_owner() -> None:
    rng = np.random.default_rng(11)
    legs = [replay.Leg(f"c{i}", i, DAY0 + timedelta(days=i % 6), frozenset({2 * i, 2 * i + 1}), 0.62, 0.55, "win" if rng.random() < 0.34 else "loss") for i in range(90)]
    rep = replay.report(legs)
    assert rep["combinations"] >= acc.MIN_COMBINATIONS and rep["acceptance"]["version"] == acc.VERSION
    assert rep["within_bound"] is False, "legs that say 62 % and win a third of the time: the joint says far more than what came in"
    few = replay.report(legs[:6])
    assert few["within_bound"] is None


def test_a_window_with_fewer_days_or_parlays_than_the_minimum_says_nothing_and_is_never_stretched() -> None:
    short_days = acc.judge_window(parlays(20, 10, said=0.1, true=0.1), "p_joint")
    assert short_days.verdict == "pendiente" and short_days.settled == 200 and short_days.days == 20 and short_days.optimism is None
    few = acc.judge_window(parlays(35, 2, said=0.1, true=0.1), "p_joint")
    assert few.verdict == "pendiente" and few.settled == 70 and "70 de 100" in few.why


def test_a_calibrated_joint_over_a_full_window_meets_the_criterion_and_an_optimistic_one_does_not() -> None:
    good = acc.judge_window(parlays(40, 8, said=0.12, true=0.12, seed=2), "p_joint")
    assert good.verdict == "cumple" and good.days == 40 and good.settled == 320 and good.low is not None and good.low <= 0.0 <= (good.high or 0.0)
    bad = acc.judge_window(parlays(40, 8, said=0.16, true=0.09, seed=3), "p_joint")
    assert bad.verdict == "no_cumple" and (bad.optimism or 0) > acc.MAX_OPTIMISM and "por encima" in bad.why
    pessimistic = acc.judge_window(parlays(60, 20, said=0.03, true=0.15, seed=4), "p_joint")
    assert pessimistic.verdict == "no_cumple" and "no contiene el cero" in pessimistic.why


def test_every_stored_estimator_is_judged_on_the_same_parlays_and_only_the_one_that_is_said_opens_the_door() -> None:
    rows = parlays(40, 8, said=0.12, true=0.12, seed=2)
    readings = acc.judge_all(rows)
    assert set(readings) == set(acc.ESTIMATORS) and {r.settled for r in readings.values()} == {320}
    assert readings["p_joint"].verdict == "cumple" and readings["p_market_joint"].verdict == "no_cumple", "the market's joint here says five points less than what came in"
    assert readings["p_joint_low"].verdict == "no_cumple"


def test_what_happened_before_the_signature_or_is_not_won_or_lost_never_counts() -> None:
    old = parlays(40, 8, said=0.30, true=0.05, start=DAY0 - timedelta(days=60))
    voided = [{**r, "status": "VOID"} for r in parlays(40, 8, said=0.30, true=0.05)]
    no_value = [{**r, "p_joint": None} for r in parlays(40, 8, said=0.30, true=0.05)]
    for rows in (old, voided, no_value):
        r = acc.judge_window(rows, "p_joint")
        assert r.verdict == "pendiente" and r.settled == 0, "a window of a past that was already looked at is empty, not a verdict"
    mixed = acc.judge_window([*old, *parlays(40, 8, said=0.12, true=0.12, seed=2)], "p_joint")
    assert mixed.verdict == "cumple" and mixed.settled == 320, "the past does not enter the window"
    try:
        acc.judge_window([], "p_whatever")
    except ValueError:
        pass
    else:
        raise AssertionError("an estimator the shadow does not store is refused")
