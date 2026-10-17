"""The capture tick cannot be coarser than the window it is trying to hit.

The provider publishes /odds/live only between T-15 and T-5 and keeps NO history for it,
so the closing price of a fixture is observable exactly once. The planner opens a
six-minute opportunity around the configured near-close window; the worker's tick was
every fifteen minutes, so it landed inside that opportunity on about 40% of fixtures and
the rest closed unobserved, permanently.

The closing line is the most informative price there is - the market's final word, and the
benchmark any claimed edge is measured against. So this is not a tuning preference, it is
the difference between having that number and not.
"""

from __future__ import annotations

from apps.worker.scheduler import NEAR_CLOSE_SPAN_MINUTES, TICK_MINUTES

from fbi.core.config import settings
from fbi.odds.schedule import NEAR_CLOSE_TOLERANCE_MINUTES


def test_the_tick_fits_inside_the_near_close_opportunity() -> None:
    """A window of width W is guaranteed to contain a tick only when the interval is at
    most W. Fifteen against six is why the closing price was usually missed."""
    assert TICK_MINUTES <= NEAR_CLOSE_SPAN_MINUTES, (
        f"a {TICK_MINUTES}-minute tick against a {NEAR_CLOSE_SPAN_MINUTES}-minute window "
        f"hits it {NEAR_CLOSE_SPAN_MINUTES / TICK_MINUTES:.0%} of the time, and "
        "/odds/live keeps no history to recover the rest from"
    )


def test_the_span_is_derived_from_the_planner_not_copied() -> None:
    """The defect was two numbers that had no reason to agree. The span is now computed
    from the tolerance the planner actually applies."""
    assert NEAR_CLOSE_SPAN_MINUTES == 2 * NEAR_CLOSE_TOLERANCE_MINUTES


def test_the_near_close_window_sits_inside_what_the_provider_publishes() -> None:
    """Measured and documented: /odds/live carries a fixture between T-15 and T-5. A
    window whose tolerance reaches outside that band would plan requests for a moment the
    provider has nothing to say about."""
    window = settings.odds.odds_nearclose_window
    earliest = window + NEAR_CLOSE_TOLERANCE_MINUTES
    latest = window - NEAR_CLOSE_TOLERANCE_MINUTES
    assert earliest <= 15, f"T-{earliest} is before the provider publishes anything"
    assert latest >= 5, f"T-{latest} is after the provider stops publishing"


def test_the_prematch_windows_stay_out_of_the_live_band() -> None:
    """/odds refreshes every three hours, so a prematch window below 180 minutes returns
    the same row and burns quota - the near-close window is what covers that ground."""
    assert min(settings.odds.prematch_windows) >= 180


# ── how late a tick may still run ───────────────────────────────────────────


def test_the_misfire_grace_comes_from_the_tolerance_not_the_interval() -> None:
    """A tick that could not start on time is still worth running late, and how late is
    a property of the capture window - not of how often the job is scheduled.

    Tying the grace to the interval meant tightening the tick to 5 minutes for the
    near-close window silently cut the grace from 900s to 300s. A database busy for
    longer than that then dropped every tick instead of running them late: a restore
    test on the live machine did exactly that for five hours and twenty minutes, and the
    capture stopped dead. The two must not move together.
    """
    grace_minutes = settings.odds.odds_window_tolerance
    assert grace_minutes > TICK_MINUTES, (
        "a grace no wider than the interval turns any slowdown into dropped ticks"
    )
    assert grace_minutes >= 45, (
        "a prematch capture stays valid for the whole tolerance band, so a tick that is "
        "late by less than that is still worth running"
    )


# ── what /odds/live actually serves, measured ───────────────────────────────


def test_near_close_is_not_planned_before_kick_off_by_default() -> None:
    """MEASURED 2026-10-01: one unfiltered /odds/live call returned 11 fixtures, every
    one in play (elapsed 6 to 93 minutes, in-play markets like "Last Corner"), and not
    one before kick-off. Two fixtures probed at T-14 and again at T-9 each came back
    `results: 0, errors: []`.

    So a near-close task planned before kick-off spends a request to learn nothing, every
    time, for every fixture that reaches kick-off. The capture path is kept - what is off
    is asking for a price the provider does not hold yet.
    """
    from datetime import UTC, datetime, timedelta

    from fbi.odds.schedule import CapturePlanner, ScheduledFixture

    at = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    fixture = ScheduledFixture(provider_fixture_id=1, kickoff_at=at + timedelta(minutes=12),
                               status_short="NS")

    off = CapturePlanner([180], 12, 45).plan([fixture], at=at, already_done=set())
    on = CapturePlanner([180], 12, 45, plan_near_close=True).plan([fixture], at=at,
                                                                  already_done=set())

    assert [t for t in off if t.kind == "near_close"] == [], "measured to return nothing"
    assert [t.kind for t in on] == ["near_close"], "the capability is kept, not deleted"


def test_the_setting_defaults_to_the_measured_answer() -> None:
    assert settings.odds.odds_capture_near_close is False
