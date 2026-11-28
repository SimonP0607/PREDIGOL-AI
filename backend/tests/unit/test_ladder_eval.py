"""RP-2.2: the criterion that lets the coherent ladder replace the stored figures (``ladder-acceptance-v1``, ``LAD-P1``). Pure."""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import pytest

from fbi.forecasting import ladder_eval as ev
from fbi.research.protocol import fingerprint

PINNED = "35ea0f04eca769a19eac3573512016587183e67ba6d29973bdf3127bff8e3fc7"
DAY0 = ev.FROZEN_ON


def rows(
    n_days: int, per_day: int, *, gain: float, start: date = DAY0, win_rate: float = 0.5
) -> list[dict[str, Any]]:
    """Each stored figure said 0.5 to win; the projected one says 0.5 + gain; ``win_rate`` of the outcomes are wins."""
    out = []
    for d in range(n_days):
        for i in range(per_day):
            out.append(
                {
                    "day": (start + timedelta(days=d)).isoformat(),
                    "state": "win" if (i % 10) < win_rate * 10 else "lose",
                    "win": 0.5,
                    "push": 0.0,
                    "p_win": 0.5 + gain,
                    "p_push": 0.0,
                }
            )
    return out


def test_the_protocol_is_registered_with_its_fingerprint_before_any_window_is_measured() -> None:
    assert fingerprint(ev.PROTOCOL) == PINNED, (
        "changing the registered criterion is a visible diff and a new version"
    )
    assert ev.PROTOCOL.registered_on == "2026-11-27" == ev.FROZEN_ON.isoformat()
    assert (ev.MARGIN, ev.MIN_DAYS, ev.MIN_FIGURES, ev.MIN_PUBLISHABLE_GAIN, ev.VARIANT) == (
        0.001,
        30,
        5000,
        0.5,
        "pooled",
    )


def test_log_loss_is_minus_the_log_of_what_happened_and_never_infinite() -> None:
    assert ev.log_loss(0.6, 0.1, "win") == pytest.approx(-math.log(0.6))
    assert ev.log_loss(0.6, 0.1, "push") == pytest.approx(-math.log(0.1))
    assert ev.log_loss(0.6, 0.1, "lose") == pytest.approx(-math.log(0.3))
    assert math.isfinite(ev.log_loss(0.0, 0.0, "win"))
    with pytest.raises(ValueError):
        ev.log_loss(0.5, 0.0, "void")


def test_the_criterion_needs_a_difference_within_the_margin_and_most_refused_matches_publishable() -> (
    None
):
    assert ev.judge_figures(high=0.0005, publishable_share=0.6)
    assert ev.judge_figures(high=0.001, publishable_share=0.5), "the margin and one half are inside"
    assert not ev.judge_figures(high=0.0011, publishable_share=0.9), "worse than the margin"
    assert not ev.judge_figures(high=0.0, publishable_share=0.49), "fewer than half repaired"
    assert not ev.judge_figures(high=None, publishable_share=0.9) and not ev.judge_figures(
        high=0.0, publishable_share=None
    )


def test_a_window_with_few_days_or_figures_is_not_judged() -> None:
    r = ev.judge_window(rows(10, 1000, gain=0.0), publishable_share=0.9)
    assert r.verdict == "pendiente" and r.difference is None
    r = ev.judge_window(rows(40, 50, gain=0.0), publishable_share=0.9)
    assert r.verdict == "pendiente", "2,000 figures are fewer than 5,000"


def test_a_window_with_identical_figures_and_repaired_matches_meets_the_criterion() -> None:
    r = ev.judge_window(rows(40, 200, gain=0.0), publishable_share=0.8)
    assert (
        r.verdict == "cumple"
        and r.difference == pytest.approx(0.0)
        and r.days == 40
        and r.figures == 8000
    ), r.why


def test_figures_that_forecast_better_are_a_negative_difference() -> None:
    r = ev.judge_window(rows(40, 200, gain=0.2, win_rate=0.7), publishable_share=0.8)
    assert (
        r.verdict == "cumple"
        and r.difference is not None
        and r.difference < -0.05
        and r.high is not None
        and r.high < 0
    )


def test_figures_that_forecast_worse_do_not_meet_it_whatever_they_repair() -> None:
    r = ev.judge_window(rows(40, 200, gain=-0.05), publishable_share=0.99)
    assert r.verdict == "no_cumple" and r.difference is not None and r.difference > 0.001
    assert "margen" in r.why


def test_repairing_too_few_matches_does_not_meet_it_even_when_the_figures_forecast_alike() -> None:
    r = ev.judge_window(rows(40, 200, gain=0.0), publishable_share=0.3)
    assert r.verdict == "no_cumple" and "publicables" in r.why


def test_rows_before_the_signing_and_unsettled_outcomes_are_left_out() -> None:
    old = rows(40, 200, gain=-0.2, start=DAY0 - timedelta(days=60))
    unsettled = [{**r, "state": None} for r in rows(40, 200, gain=-0.2)]
    r = ev.judge_window(old + unsettled, publishable_share=0.9)
    assert r.figures == 0 and r.verdict == "pendiente"


def test_the_share_of_repaired_matches_is_over_the_ones_that_were_refused() -> None:
    assert ev.publishable_share(
        [True, False, False, False], [True, True, True, False]
    ) == pytest.approx(2 / 3)
    assert ev.publishable_share([True, True], [True, True]) is None, (
        "nothing was refused: there was nothing to fix"
    )
