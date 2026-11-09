"""The one freshness rule of the explorer (plan Cuotas, BE-011; ``fbi.odds.freshness``): a price is current when the ask that
confirmed it came at or after the latest scheduled ask whose band has closed, stale when one was missed - with the model windows
alone, or with the book refreshes' points too, and the capture's tolerance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.odds.freshness import (
    book_state,
    due_point,
    is_quarter,
    last_closed_point,
    parlay_ok,
    price_state,
    refresh_points,
    schedule,
)

KO = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
WINDOWS = (4320, 2880, 1440, 720, 360, 180)
TOL = 45


def at(minutes_before: float) -> datetime:
    return KO - timedelta(minutes=minutes_before)


def state(checked: float, now: float, *, refreshes: bool = False, tolerance: int = TOL) -> str:
    return price_state(checked_at=at(checked), kickoff_at=KO, now=at(now), points=schedule(WINDOWS, refreshes=refreshes),
                       tolerance=tolerance)


def test_the_refresh_points_are_the_plans_cadence() -> None:
    points = refresh_points()
    assert points == tuple(sorted(points, reverse=True)) and len(points) == len(set(points)) == 30
    assert points[:23] == tuple(range(4320, 359, -180)), "every 3 h from T-72 h to T-6 h"
    assert points[22:28] == (360, 300, 240, 180, 120, 60), "every hour from T-6 h to T-1 h"
    assert points[-2:] == (30, 10)
    assert set(WINDOWS) <= set(points), "the model windows fall on the refresh grid"
    assert len(set(points) - set(WINDOWS)) == 24, "about 24 more asks a match (plan, section 6)"


def test_the_schedule_is_the_model_windows_unless_the_refreshes_run() -> None:
    assert schedule(WINDOWS, refreshes=False) == WINDOWS
    assert schedule([180, 360, 180], refreshes=False) == (360, 180)
    assert schedule(WINDOWS, refreshes=True) == refresh_points()


@pytest.mark.parametrize(("minutes", "closed"), [
    (5000, None),  # before the first band closes (4320 - 45 = 4275): nothing can have been missed
    (4275, None),  # the band's last minute: still open
    (4274, 4320), (2834, 2880), (1000, 1440), (180, 360), (136, 360), (134, 180), (0, 180), (-30, 180),
])
def test_the_last_closed_band_with_the_model_windows(minutes: float, closed: int | None) -> None:
    assert last_closed_point(WINDOWS, minutes, TOL) == closed


def test_with_the_model_windows_a_price_is_current_until_a_window_is_missed() -> None:
    assert state(checked=4310, now=3000) == "current", "the T-72 capture, before the T-48 band closes"
    assert state(checked=4310, now=2800) == "stale", "the T-48 window closed unasked"
    assert state(checked=2880, now=2800) == "current", "asked at the window's nominal instant"
    assert state(checked=2850, now=2000) == "current", "asked inside its band"
    assert state(checked=2881, now=2800) == "stale", "a minute before the window is not the window"
    assert state(checked=178, now=1) == "current", "the T-180 capture stays current up to kick-off: no later window"
    assert state(checked=358, now=170) == "current", "T-180's band is still open at T-170"
    assert state(checked=358, now=130) == "stale", "and closed at T-130"
    assert state(checked=361, now=300) == "stale", "an ask a minute before T-360 did not serve it"


def test_with_the_refreshes_on_their_points_are_expected_too() -> None:
    assert state(checked=178, now=100) == "current"
    assert state(checked=178, now=100, refreshes=True) == "current", "T-120's band is open until T-75"
    assert state(checked=178, now=70, refreshes=True) == "stale", "T-120 was missed"
    assert state(checked=118, now=70, refreshes=True) == "current"
    assert state(checked=59, now=5, refreshes=True) == "current", "T-30 and T-10 are still within their bands"
    assert state(checked=59, now=-20, refreshes=True) == "stale", "after kick-off T-30's band has closed too"
    assert state(checked=4000, now=3920, refreshes=True) == "current", "T-66 h's band is open until T-65 h 15"
    assert state(checked=4000, now=3910, refreshes=True) == "stale", "and then T-66 h was missed"
    assert state(checked=4000, now=3000) == "current", "without the refreshes only T-48 h could be missed"


def test_the_tolerance_is_the_captures() -> None:
    assert state(checked=400, now=320) == "current"
    assert state(checked=400, now=320, tolerance=30) == "stale", "a narrower band closes sooner"


def test_a_match_without_a_price_has_no_state() -> None:
    assert book_state(checked_at=None, kickoff_at=KO, now=at(100), points=WINDOWS, tolerance=TOL) == "none"
    assert book_state(checked_at=at(170), kickoff_at=KO, now=at(100), points=WINDOWS, tolerance=TOL) == "current"


@pytest.mark.parametrize(("minutes", "due"), [
    (4320, 4320), (4275, 4320), (4274, None), (4140, 4140), (4100, 4140), (60, 60), (25, 30), (31, 60), (10, 10),
    (0, 10), (-30, 10), (-36, None),
])
def test_the_due_point_is_the_tightest_open_band(minutes: float, due: int | None) -> None:
    assert due_point(refresh_points(), minutes, TOL) == due


@pytest.mark.parametrize(("line", "quarter"), [(None, False), (Decimal("0"), False), (Decimal("-0.25"), True),
                                               (Decimal("0.5"), False), (Decimal("2.75"), True), (Decimal("-1"), False),
                                               (Decimal("1.5"), False)])
def test_a_quarter_line(line: Decimal | None, quarter: bool) -> None:
    assert is_quarter(line) is quarter


def test_what_may_go_to_mi_parlay() -> None:
    now = at(100)
    good = {"parlay_market": True, "line": Decimal("-0.5"), "outlier": False, "state": "current", "kickoff_at": KO,
            "now": now}
    assert parlay_ok(**good) is True  # type: ignore[arg-type]
    for change in ({"parlay_market": False}, {"line": Decimal("-0.25")}, {"outlier": True}, {"state": "stale"},
                   {"now": KO}, {"now": KO + timedelta(minutes=1)}):
        assert parlay_ok(**{**good, **change}) is False, change  # type: ignore[arg-type]
