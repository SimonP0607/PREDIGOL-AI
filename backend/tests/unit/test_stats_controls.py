"""RP-6.4: the three controls a statistical fact passes before it is cited, and the provoked leak that must fail."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.stats import controls
from fbi.stats.reading import Document

AS_OF = datetime(2026, 11, 26, 12, tzinfo=UTC)


def doc(*, computed: datetime | None = AS_OF - timedelta(hours=10), sample: int = 20, status: str = "ok") -> Document:
    return Document(status, "team", 42, 7, "season", "all", "stats-docs-v1", "stat:team:42:7:season:all:stats-docs-v1",  # type: ignore[arg-type]
                    sample, computed, ())


def test_a_document_that_passes_every_control_is_citable() -> None:
    assert controls.problems(doc(), as_of=AS_OF, last_match_at=AS_OF - timedelta(days=2), min_sample=8) == ()


def test_a_document_computed_after_the_cutoff_is_refused_and_says_nothing_else() -> None:
    assert controls.problems(doc(computed=AS_OF + timedelta(seconds=1)), as_of=AS_OF, last_match_at=None, min_sample=8) == (controls.AFTER_CUTOFF,)
    assert controls.problems(Document("after_cutoff", "team", 42, 7, "season", "all"), as_of=AS_OF, last_match_at=None, min_sample=8) == (
        controls.AFTER_CUTOFF,)


def test_a_document_older_than_the_last_match_played_is_stale() -> None:
    last = AS_OF - timedelta(hours=11)
    assert controls.problems(doc(), as_of=AS_OF, last_match_at=last, min_sample=8) == ()
    assert controls.problems(doc(computed=last - timedelta(minutes=1)), as_of=AS_OF, last_match_at=last, min_sample=8) == (controls.STALE,)
    assert controls.problems(doc(computed=last), as_of=AS_OF, last_match_at=last, min_sample=8) == ()


def test_a_sample_under_the_threshold_is_said_not_cited() -> None:
    assert controls.problems(doc(sample=7), as_of=AS_OF, last_match_at=None, min_sample=8) == (controls.SMALL_SAMPLE,)
    assert controls.problems(doc(sample=8), as_of=AS_OF, last_match_at=None, min_sample=8) == ()


def test_the_controls_are_independent_and_come_in_a_fixed_order() -> None:
    found = controls.problems(doc(computed=AS_OF - timedelta(days=9), sample=3), as_of=AS_OF, last_match_at=AS_OF - timedelta(days=1),
                              min_sample=8)
    assert found == (controls.STALE, controls.SMALL_SAMPLE) and set(found) <= set(controls.CODES)


def test_a_document_that_is_not_there_has_nothing_to_check() -> None:
    assert controls.problems(Document("no_document", "team", 42, 7, "season", "all"), as_of=AS_OF, last_match_at=None, min_sample=8) == ()


def test_a_provoked_leak_fails() -> None:
    clean = {"document_id": "a", "known_at": (AS_OF - timedelta(hours=1)).isoformat()}
    assert controls.assert_no_leak([clean, None, {"document_id": "b", "known_at": AS_OF.isoformat()}], as_of=AS_OF) == 2
    leak = {"document_id": "leak", "known_at": (AS_OF + timedelta(minutes=1)).isoformat()}
    with pytest.raises(controls.LeakError, match="leak"):
        controls.assert_no_leak([clean, leak], as_of=AS_OF)
    with pytest.raises(controls.LeakError, match="without its date"):
        controls.assert_no_leak([{"document_id": "undated", "known_at": None}], as_of=AS_OF)


def test_a_verdict_is_citable_only_without_codes() -> None:
    assert controls.Verdict("x", ()).citable and not controls.Verdict("x", (controls.STALE,)).citable
    assert controls.Verdict("x", (), "nota").citable, "the calendar note never refuses a fact"
