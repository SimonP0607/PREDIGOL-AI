"""The probe measures; it does not assume.

On the Free plan the result horizon was THREE DAYS and nothing in the code knew,
so eight fixtures we had prices for stayed permanently 'NS'. These tests pin the
two things that matter about a measurement: an error inside HTTP 200 is not
success, and no visible window is reported as None rather than as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from fbi.odds.windows_probe import DateWindow, OddsWindow, WindowReport, _books_and_bets, _errors

MEASURED = datetime(2026, 9, 29, 6, 0, tzinfo=UTC)


@dataclass
class _Body:
    body: dict[str, Any]


def test_an_error_inside_http_200_is_not_a_visible_window() -> None:
    """API-Football reports failure in `errors` with a 200 status. A window that
    'returned 0 results' because the plan refused it is not an empty window."""
    refused = DateWindow(offset_days=-365, on=MEASURED.date(), results=0,
                         provider_errors={"plan": "Your plan does not allow this date"})
    assert not refused.visible
    empty = DateWindow(offset_days=3, on=MEASURED.date(), results=0)
    assert not empty.visible, "no fixtures that day is also not a visible window"
    seen = DateWindow(offset_days=0, on=MEASURED.date(), results=42)
    assert seen.visible


def test_errors_are_read_only_when_the_provider_populated_them() -> None:
    assert _errors({"errors": []}) == {}
    assert _errors({"errors": {}}) == {}
    assert _errors({"errors": {"plan": "no"}}) == {"plan": "no"}
    assert _errors(None) == {}


def test_no_visible_window_is_none_not_zero() -> None:
    """Zero would read as "today", which is a different claim entirely."""
    report = WindowReport(measured_at=MEASURED.isoformat(), dates=[
        DateWindow(offset_days=-3, on=MEASURED.date(), results=0),
        DateWindow(offset_days=0, on=MEASURED.date(), results=0),
    ])
    assert report.earliest_visible_offset is None and report.latest_visible_offset is None
    assert report.furthest_priced_minutes is None
    assert report.as_dict()["earliest_visible_offset"] is None


def test_the_visible_range_is_the_outermost_offsets_that_answered() -> None:
    report = WindowReport(measured_at=MEASURED.isoformat(), dates=[
        DateWindow(offset_days=-365, on=MEASURED.date(), results=0, provider_errors={"plan": "no"}),
        DateWindow(offset_days=-3, on=MEASURED.date(), results=7),
        DateWindow(offset_days=0, on=MEASURED.date(), results=9),
        DateWindow(offset_days=30, on=MEASURED.date(), results=4),
        DateWindow(offset_days=90, on=MEASURED.date(), results=0),
    ])
    assert (report.earliest_visible_offset, report.latest_visible_offset) == (-3, 30)


def test_the_furthest_priced_distance_ignores_unpriced_fixtures() -> None:
    report = WindowReport(measured_at=MEASURED.isoformat(), odds=[
        OddsWindow(provider_fixture_id=1, minutes_to_kickoff=43200, bookmakers=0, bets=0),
        OddsWindow(provider_fixture_id=2, minutes_to_kickoff=20160, bookmakers=3, bets=40),
        OddsWindow(provider_fixture_id=3, minutes_to_kickoff=180, bookmakers=9, bets=120),
    ])
    assert report.furthest_priced_minutes == 20160, "14 days, not the 30 that had no prices"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({}, (0, 0)),
        ({"response": []}, (0, 0)),
        ({"response": [{"bookmakers": [{"bets": [1, 2]}, {"bets": [3]}]}]}, (2, 3)),
        ({"response": [{"bookmakers": None}]}, (0, 0)),
    ],
)
def test_books_and_bets_are_counted_defensively(body: dict[str, Any],
                                                expected: tuple[int, int]) -> None:
    assert _books_and_bets(body) == expected


def test_the_report_carries_the_date_it_was_measured() -> None:
    """A capability claim without a date is how a stale measurement becomes a
    permanent belief."""
    report = WindowReport(measured_at=MEASURED.isoformat())
    assert report.as_dict()["measured_at"] == MEASURED.isoformat()
