"""Capture cadence.

The windows are dictated by the provider: /odds refreshes every 3 hours, so a
window below 180 minutes observes nothing new and only spends quota. /odds/live
is published between T-15 and T-5, and is the only view of a price near
kick-off - which this module calls a NEAR-CLOSE snapshot and never a closing
line.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from fbi.odds.schedule import CapturePlanner, ScheduledFixture

KICKOFF = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)


def planner(windows: tuple[int, ...] = (4320, 1440, 720, 360, 180), near: int = 12, tol: int = 45) -> CapturePlanner:
    return CapturePlanner(windows, near, tol)


def at(minutes_before: float) -> datetime:
    return KICKOFF - timedelta(minutes=minutes_before)


FIXTURE = ScheduledFixture(provider_fixture_id=1001, kickoff_at=KICKOFF)


def test_a_window_below_180_minutes_is_refused() -> None:
    with pytest.raises(ValueError, match="/odds refreshes every 3 hours"):
        CapturePlanner((1440, 90), 12, 45)


def test_a_near_close_window_outside_the_providers_band_is_refused() -> None:
    for bad in (2, 30):
        with pytest.raises(ValueError, match=re.escape("T-15..T-5")):
            CapturePlanner((1440,), bad, 45)


@pytest.mark.parametrize("minutes", [1440, 1420, 1396, 1395])
def test_a_window_is_due_from_its_nominal_instant_until_the_tolerance_expires(minutes: float) -> None:
    """Nominal is T-1440; with a 45-minute tolerance the band closes at T-1395.

    minutes_to_kickoff counts DOWN, so "later" means a smaller number here.
    """
    tasks = planner().plan([FIXTURE], at=at(minutes))
    assert [t.window_minutes for t in tasks] == [1440]
    assert tasks[0].kind == "prematch"


@pytest.mark.parametrize("minutes", [1394, 1300])
def test_a_tick_that_arrives_after_the_tolerance_captures_nothing(minutes: float) -> None:
    """One minute past the band is past it. The window is lost rather than
    captured at a distance the key would misdescribe."""
    assert planner().plan([FIXTURE], at=at(minutes)) == []


@pytest.mark.parametrize("minutes", [1500, 1441])
def test_a_tick_that_arrives_before_the_window_opens_captures_nothing(minutes: float) -> None:
    """The band opens AT the nominal instant, never before it, so a snapshot
    filed under window 1440 is never further from kick-off than 1440."""
    assert planner().plan([FIXTURE], at=at(minutes)) == []


def test_waking_at_next_run_at_and_running_late_still_captures_the_window() -> None:
    """The contract between the two halves of this module, and the reason the
    band runs forward: next_run_at names the instant a window opens, so a
    scheduler that sleeps until then and is slow to act is still in time.

    With the band running backwards next_run_at pointed at the instant it
    CLOSED, and a tick 60 seconds late captured nothing at all.
    """
    p = planner()
    moment = p.next_run_at([FIXTURE], at=at(2000))
    assert moment == at(1440), "next_run_at is the nominal instant"
    assert [t.window_minutes for t in p.plan([FIXTURE], at=moment)] == [1440]
    for lateness in (1, 44, 45):
        late = moment + timedelta(minutes=lateness)
        assert [t.window_minutes for t in p.plan([FIXTURE], at=late)] == [1440], (
            f"a tick {lateness} min after next_run_at must still be inside the band"
        )
    assert p.plan([FIXTURE], at=moment + timedelta(minutes=46)) == []


def test_the_near_close_window_uses_the_live_endpoint() -> None:
    tasks = planner().plan([FIXTURE], at=at(12))
    assert len(tasks) == 1
    assert tasks[0].kind == "near_close"
    assert tasks[0].window_minutes == 12


def test_a_capture_already_on_record_is_not_repeated() -> None:
    p = planner()
    done = p.covered_keys([(1001, "prematch", 1435)])
    assert p.plan([FIXTURE], at=at(1430), already_done=done) == []


def test_coverage_is_derived_from_what_was_actually_stored() -> None:
    p = planner()
    assert p.covered_keys([(1001, "prematch", 1430)]) == {"1001:prematch:1440"}


def test_a_snapshot_taken_before_its_window_opened_covers_nothing() -> None:
    """covered_keys and _due_window must agree on the band. If they drift, a
    window is either captured twice or never marked done."""
    p = planner()
    assert p.covered_keys([(1001, "prematch", 1460)]) == set()
    assert p.covered_keys([(1001, "live", 12)]) == {"1001:near_close:12"}
    # 200 minutes past the 720 window: it satisfies nothing, so the window is
    # still owed rather than being quietly written off.
    assert p.covered_keys([(1001, "prematch", 920)]) == set()


def test_a_fixture_that_has_already_kicked_off_is_never_captured() -> None:
    assert planner().plan([FIXTURE], at=KICKOFF + timedelta(minutes=1)) == []


@pytest.mark.parametrize("status", ["1H", "FT", "CANC", "ABD"])
def test_only_fixtures_that_have_not_started_are_planned(status: str) -> None:
    fixture = ScheduledFixture(1001, KICKOFF, status_short=status)
    assert planner().plan([fixture], at=at(1441)) == []


def test_tasks_come_back_nearest_to_kickoff_first() -> None:
    soon = ScheduledFixture(1, KICKOFF)
    later = ScheduledFixture(2, KICKOFF + timedelta(minutes=1080))
    tasks = planner().plan([later, soon], at=at(360))
    assert [t.provider_fixture_id for t in tasks] == [1, 2]
    assert [t.window_minutes for t in tasks] == [360, 1440]


def test_window_keys_are_stable_and_distinct() -> None:
    p = planner()
    first = p.plan([FIXTURE], at=at(1440))[0]
    again = p.plan([FIXTURE], at=at(1410))[0]
    assert first.window_key == again.window_key == "1001:prematch:1440"
    assert p.plan([FIXTURE], at=at(359))[0].window_key == "1001:prematch:360"


def test_next_run_at_points_at_the_next_pending_window() -> None:
    p = planner()
    assert p.next_run_at([FIXTURE], at=at(2000)) == at(1440)
    assert p.next_run_at([FIXTURE], at=at(20)) == at(12)
    assert p.next_run_at([FIXTURE], at=at(1)) is None


def test_nothing_scheduled_means_no_wakeup() -> None:
    assert planner().next_run_at([], at=at(500)) is None


def test_two_ticks_inside_one_tolerance_band_spend_one_request_not_two() -> None:
    """The tolerance is what makes a late scheduler tick still useful; it must
    not also make an early one pay twice.

    With a 45-minute tolerance the 180 window is due anywhere from T-180 to
    T-135, so two consecutive ticks can both land in it. The first captures and
    the snapshot it writes is what removes the window from the second - coverage
    derived from the stored price, not from a separate bookkeeping table.
    """
    p = planner()
    first = p.plan([FIXTURE], at=at(180))
    assert [t.window_minutes for t in first] == [180], "the nominal tick captures the window"

    # What the first capture stored: a prematch price at T-180.
    done = p.covered_keys([(1001, "prematch", 180)])
    assert done == {"1001:prematch:180"}

    second = p.plan([FIXTURE], at=at(150), already_done=done)
    assert second == [], "a later tick in the same band adds nothing once it is on record"


def test_without_the_record_the_same_window_is_offered_again() -> None:
    """The guard is the stored snapshot, so its absence must be visible rather
    than silently forgiven - otherwise a capture that failed to persist would
    look identical to one that succeeded."""
    p = planner()
    assert [t.window_minutes for t in p.plan([FIXTURE], at=at(180))] == [180]
    assert [t.window_minutes for t in p.plan([FIXTURE], at=at(150), already_done=set())] == [180]
