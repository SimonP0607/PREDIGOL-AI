"""The account centre's one read (plan UX, B1): the pure parts of what the profile's folded blocks say."""

from __future__ import annotations

from datetime import UTC, date, datetime

from fbi.customer.account import help_counts, latest_decision, open_requests


def test_help_counts_waiting_and_answered_as_ayuda_shows_them() -> None:
    counts = help_counts(["open", "answered", "closed", "open", "answered", "closed", "closed"])
    assert (counts.waiting, counts.answered) == (2, 2)
    assert help_counts([]) == help_counts(["closed"])
    assert help_counts([]).waiting == 0


def test_open_requests_count_the_open_ones_and_the_nearest_deadline() -> None:
    pairs = [("open", date(2026, 11, 20)), ("answered", date(2026, 11, 1)), ("open", date(2026, 11, 9)),
             ("closed", date(2026, 10, 30)), ("open", None)]
    assert open_requests(pairs) == (3, date(2026, 11, 9))
    assert open_requests([("closed", date(2026, 11, 1))]) == (0, None)
    assert open_requests([("open", None)]) == (1, None)


def test_latest_decision_is_the_newest_or_none() -> None:
    a = datetime(2026, 10, 1, 12, tzinfo=UTC)
    b = datetime(2026, 10, 20, 8, tzinfo=UTC)
    assert latest_decision([a, b]) == b
    assert latest_decision([]) is None
