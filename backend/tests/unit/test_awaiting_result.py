"""A match in play is live, not "awaiting its result"."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.api.services.matches import awaiting_result

NOW = datetime(2026, 10, 3, 1, 0, tzinfo=UTC)


def test_a_match_being_played_is_not_awaiting() -> None:
    assert awaiting_result(NOW - timedelta(minutes=50), "live", NOW) is False


def test_still_scheduled_a_quarter_hour_after_kickoff_is_awaiting() -> None:
    assert awaiting_result(NOW - timedelta(minutes=10), "scheduled", NOW) is False
    assert awaiting_result(NOW - timedelta(minutes=20), "scheduled", NOW) is True


def test_still_live_long_after_any_match_could_end_is_awaiting() -> None:
    assert awaiting_result(NOW - timedelta(hours=4), "live", NOW) is True


def test_finished_and_future_matches_are_never_awaiting() -> None:
    assert awaiting_result(NOW - timedelta(days=1), "finished", NOW) is False
    assert awaiting_result(NOW + timedelta(hours=1), "scheduled", NOW) is False
