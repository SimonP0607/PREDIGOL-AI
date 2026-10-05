"""An upcoming fixture against its capture windows: on schedule, behind, or the provider's gap.

5 Oct 2026: the Data Quality page called 40 of 73 priced fixtures "stale" with a fixed 4-hour rule, although every
window due had been captured: a fixture three days out is priced at T-72 h and next at T-48 h."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.quality.metrics import DEFAULT_WINDOWS, capture_state

AT = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def state(hours_to_ko: float, captured_hours_ago: float | None, asked_hours_ago: float | None = None,
          mapped: bool = True) -> str:
    kickoff = AT + timedelta(hours=hours_to_ko)
    captured = None if captured_hours_ago is None else AT - timedelta(hours=captured_hours_ago)
    asked = None if asked_hours_ago is None else AT - timedelta(hours=asked_hours_ago)
    return capture_state(kickoff, captured, asked, mapped, at=AT, windows=DEFAULT_WINDOWS, tolerance_minutes=45)


def test_a_price_older_than_four_hours_is_on_schedule_between_windows() -> None:
    assert state(60, captured_hours_ago=11) == "current", "T-72 h captured, T-48 h not open yet"
    assert state(80, captured_hours_ago=None) == "not_due", "no window has closed yet"


def test_a_closed_window_without_a_newer_price_is_ours() -> None:
    assert state(20, captured_hours_ago=30) == "stale", "T-24 h closed; newest price from T-50 h"
    assert state(20, captured_hours_ago=None) == "missed"
    assert state(20, captured_hours_ago=3) == "current", "the catch-up priced it after the window"


def test_asked_and_nothing_came_back_is_the_providers() -> None:
    assert state(20, captured_hours_ago=30, asked_hours_ago=2) == "provider_unpriced"
    assert state(20, captured_hours_ago=None, mapped=False) == "provider_unpriced", "never listed as priced"


def test_inside_the_band_the_window_is_not_yet_late() -> None:
    assert state(23.8, captured_hours_ago=30) == "stale", "T-48 h closed long ago without a newer price"
    assert state(47.5, captured_hours_ago=23) == "current", "T-48 h band still open; T-72 h was captured"
