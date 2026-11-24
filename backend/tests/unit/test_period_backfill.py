"""PM-05-02: the night's window and its arithmetic (``scripts.period_backfill``)."""

from __future__ import annotations

from datetime import UTC, datetime, time

import pytest
from scripts import period_backfill as pb


def at(h: int, m: int = 0, day: int = 24) -> datetime:
    return datetime(2026, 11, day, h, m, tzinfo=UTC)


@pytest.mark.parametrize(("hour", "minute", "inside"), [(22, 29, False), (22, 30, True), (23, 59, True), (0, 0, True), (3, 24, True),
                                                        (3, 25, False), (12, 0, False)])
def test_the_window_runs_from_2230_to_0325_utc(hour: int, minute: int, inside: bool) -> None:
    assert pb.in_window(at(hour, minute)) is inside


def test_the_stop_is_the_next_0325() -> None:
    assert pb.stop_time(at(22, 31)) == at(3, 25, day=25)
    assert pb.stop_time(at(1, 0)) == at(3, 25)
    assert pb.stop_time(at(3, 25)) == at(3, 25, day=25)


def test_the_stop_is_before_the_copies_start() -> None:
    assert time(3, 50) > pb.STOP_AT  # the lane's quiet window and the copies' 03:50


@pytest.mark.parametrize(("requests", "nights"), [(0, 0), (1, 1), (5_000, 1), (5_001, 2), (53_500, 11)])
def test_nights_needed(requests: int, nights: int) -> None:
    assert pb.nights_needed(requests) == nights


def test_the_pace_stays_under_a_fifth_of_the_per_minute_limit() -> None:
    assert 60 / pb.PACE_SECONDS <= 40
