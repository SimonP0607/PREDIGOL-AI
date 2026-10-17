"""Kick-off changes read back from stored /fixtures payloads, in fetch order."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fbi.ingestion.kickoff_history import kickoff_changes


def body(pid: int, date: str) -> dict[str, Any]:
    return {"response": [{
        "fixture": {"id": pid, "date": date, "status": {"short": "NS"}, "venue": {"id": None}},
        "league": {"id": 667, "season": 2026, "round": "Club Friendlies 2"},
        "teams": {"home": {"id": 1, "name": "A"}, "away": {"id": 2, "name": "B"}}}]}


def test_a_placeholder_time_corrected_after_the_match_is_one_change() -> None:
    t = [datetime(2026, 9, 29, 18, 55, tzinfo=UTC), datetime(2026, 9, 30, 18, 23, tzinfo=UTC),
         datetime(2026, 10, 4, 6, 48, tzinfo=UTC)]
    changes = kickoff_changes([
        (t[0], "h0", body(1642915, "2026-10-02T12:00:00+00:00")),
        (t[1], "h1", body(1642915, "2026-10-02T12:00:00+00:00")),
        (t[2], "h2", body(1642915, "2026-10-02T08:30:00+00:00")),
    ])
    assert len(changes) == 1
    c = changes[0]
    assert (c.observed_at, c.payload_hash) == (t[2], "h2")
    assert (c.before.hour, c.after.hour, c.after.minute) == (12, 8, 30)


def test_an_unchanged_kick_off_is_no_change() -> None:
    t = datetime(2026, 9, 29, tzinfo=UTC)
    assert kickoff_changes([(t, "a", body(1, "2026-10-02T12:00:00+00:00")),
                            (t, "b", body(1, "2026-10-02T12:00:00+00:00"))]) == []
