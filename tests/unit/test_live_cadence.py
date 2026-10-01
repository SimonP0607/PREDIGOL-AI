"""The live cadence: what it refuses to spend, and when it spends nothing at all."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fbi.odds.live_cadence import (
    DEFAULT_LIVE_DAILY_BUDGET,
    IDLE_RECHECK_SECONDS,
    JITTER_GRACE_SECONDS,
    POLL_FLOOR_SECONDS,
    CadenceDecision,
    decide,
    possibly_live_count,
    seconds_until_next_kickoff,
    wake_interval,
)

NOW = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)


def at(**kw: float) -> datetime:
    return NOW + timedelta(**kw)


def call(**kw: Any) -> CadenceDecision:
    base: dict[str, Any] = {
        "kickoffs": [],
        "at": NOW,
        "live_calls_today": 0,
        "remaining_quota": 50_000,
    }
    base.update(kw)
    return decide(**base)


def test_the_floor_is_the_measured_refresh_period() -> None:
    """30 s, because 12 calls 10.4 s apart returned 5 distinct payloads: every
    fixture's update stamp moved together once every three ticks. Asking faster
    cannot return a price that is not already in hand."""
    assert POLL_FLOOR_SECONDS == 30


def test_nothing_in_play_costs_no_request() -> None:
    """The saving that makes the whole thing affordable. Football is not live
    24 hours a day, and being told so costs a request."""
    d = call(kickoffs=[at(hours=6)])
    assert d.should_capture is False
    assert "nothing in play" in d.reason
    assert d.fixtures_possibly_live == 0


def test_it_wakes_in_time_for_the_next_kick_off() -> None:
    d = call(kickoffs=[at(minutes=2)])
    assert d.should_capture is False
    assert d.next_in_seconds <= 120


def test_a_distant_kick_off_falls_back_to_the_idle_recheck() -> None:
    d = call(kickoffs=[at(hours=9)])
    assert d.next_in_seconds == IDLE_RECHECK_SECONDS


def test_an_empty_calendar_still_schedules_a_look() -> None:
    d = call(kickoffs=[])
    assert d.should_capture is False
    assert d.next_in_seconds == IDLE_RECHECK_SECONDS
    assert "nothing scheduled" in d.reason


def test_a_match_underway_is_captured_at_the_floor() -> None:
    d = call(kickoffs=[at(minutes=-50)])
    assert d.should_capture is True
    assert d.next_in_seconds == POLL_FLOOR_SECONDS
    assert d.fixtures_possibly_live == 1


def test_a_match_that_kicked_off_long_ago_is_no_longer_live() -> None:
    d = call(kickoffs=[at(minutes=-200)])
    assert d.should_capture is False


def test_the_window_errs_wide_rather_than_missing_stoppages() -> None:
    """A fixture counted wrongly costs one call returning an empty list; one
    missed loses prices /odds/live will never serve again."""
    assert possibly_live_count([at(minutes=-140)], at=NOW) == 1
    assert possibly_live_count([at(minutes=-151)], at=NOW) == 0


def test_an_exhausted_day_quota_stops_the_live_path_too() -> None:
    """Live has priority over history, never over the guard that protects the
    whole day."""
    d = call(kickoffs=[at(minutes=-30)], remaining_quota=0)
    assert d.should_capture is False
    assert "quota exhausted" in d.reason


def test_the_live_budget_is_its_own_ceiling() -> None:
    d = call(
        kickoffs=[at(minutes=-30)],
        live_calls_today=DEFAULT_LIVE_DAILY_BUDGET,
        remaining_quota=50_000,
    )
    assert d.should_capture is False
    assert "live budget spent" in d.reason


def test_a_thin_budget_stretches_the_interval_instead_of_stopping() -> None:
    """Degrade the resolution of the series rather than lose its tail."""
    d = call(
        kickoffs=[at(minutes=-10)],
        live_calls_today=DEFAULT_LIVE_DAILY_BUDGET - 10,
        remaining_quota=50_000,
    )
    assert d.should_capture is True
    assert d.next_in_seconds > POLL_FLOOR_SECONDS
    assert "stretched" in d.reason


def test_the_interval_is_honoured_across_wake_ups() -> None:
    """The scheduler wakes at the floor; a stretched interval must still hold,
    and the elapsed time comes from the record of captures so a worker restart
    does not double-spend."""
    d = call(
        kickoffs=[at(minutes=-30)],
        last_capture_at=at(seconds=-5),
    )
    assert d.should_capture is False
    assert "since last capture" in d.reason
    assert d.next_in_seconds == POLL_FLOOR_SECONDS - 5


def test_a_capture_a_full_interval_ago_goes_ahead() -> None:
    d = call(kickoffs=[at(minutes=-30)], last_capture_at=at(seconds=-POLL_FLOOR_SECONDS))
    assert d.should_capture is True


def test_a_day_of_football_fits_well_inside_the_budget() -> None:
    """The cost is per tick, not per match: one unfiltered call covers every live
    fixture, so 24 hours at the floor is under 5% of the 60,000/day guard."""
    ticks_per_day = 24 * 60 * 60 // POLL_FLOOR_SECONDS
    assert ticks_per_day == 2880
    assert ticks_per_day < DEFAULT_LIVE_DAILY_BUDGET
    assert ticks_per_day / 60_000 < 0.05


def test_ninety_live_matches_cost_the_same_as_two() -> None:
    few = call(kickoffs=[at(minutes=-30)] * 2)
    many = call(kickoffs=[at(minutes=-30)] * 90)
    assert few.next_in_seconds == many.next_in_seconds == POLL_FLOOR_SECONDS
    assert many.fixtures_possibly_live == 90


def test_seconds_until_next_kickoff_ignores_matches_already_started() -> None:
    assert seconds_until_next_kickoff([at(minutes=-30)], at=NOW) is None
    assert seconds_until_next_kickoff([at(minutes=-30), at(minutes=10)], at=NOW) == 600


# --- the defect that halved the first night's capture rate ------------------


def test_the_scheduler_wakes_more_often_than_it_captures() -> None:
    """Waking exactly as often as the deadline halves the rate.

    Measured in production: with both set to 30 s the series came out at 60 s
    gaps. A wake-up lands a few hundred milliseconds before the deadline it
    exists to meet, the gate says "not yet", and the next one is a full interval
    late. A wake-up costs a database query; a missed in-play refresh costs a
    price that /odds/live will never serve again.
    """
    assert wake_interval(POLL_FLOOR_SECONDS) < POLL_FLOOR_SECONDS
    assert wake_interval(30) == 15
    assert wake_interval(1) >= 1, "never zero, or the scheduler would spin"


def test_a_wake_up_a_hair_early_still_captures() -> None:
    """The floor stops us asking faster than the provider answers. Asking after
    29.9 s is not asking faster in any way that matters."""
    d = call(
        kickoffs=[at(minutes=-30)],
        last_capture_at=at(seconds=-(POLL_FLOOR_SECONDS - 1)),
    )
    assert d.should_capture is True


def test_a_wake_up_genuinely_too_early_still_waits() -> None:
    d = call(
        kickoffs=[at(minutes=-30)],
        last_capture_at=at(seconds=-(POLL_FLOOR_SECONDS - JITTER_GRACE_SECONDS - 1)),
    )
    assert d.should_capture is False


def test_waking_twice_per_interval_cannot_double_spend() -> None:
    """The halves must not both capture: the gate, not the alarm, decides."""
    wake = wake_interval(POLL_FLOOR_SECONDS)
    mid = call(kickoffs=[at(minutes=-30)], last_capture_at=at(seconds=-wake))
    assert mid.should_capture is False, "the intermediate wake-up must not spend"
    due = call(
        kickoffs=[at(minutes=-30)], last_capture_at=at(seconds=-POLL_FLOOR_SECONDS)
    )
    assert due.should_capture is True


def test_the_worst_case_gap_is_the_interval_plus_one_wake() -> None:
    """With the alarm at half the interval, a tick that declines is retried half
    an interval later - so the series degrades to 45 s, never to 60 s."""
    wake = wake_interval(POLL_FLOOR_SECONDS)
    worst = POLL_FLOOR_SECONDS + wake
    assert worst < 2 * POLL_FLOOR_SECONDS
