"""``write_events`` of the match review: which evidence verdicts write which memory event, and what it counts.

Pinned when a newer ruff asked for the nested ``if`` of the ``right`` branch to be written as one condition (CI-009): the
branch must remember an ``injury_signal`` only for a ``right`` verdict, count it only when the memory wrote a new row, and
leave every other verdict alone.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fbi.intel import match_review

AT = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _evidence(verdict: str, n: int) -> dict[str, Any]:
    return {"evidence_id": n, "tier": 2, "claim": f"claim {n}", "verdict": verdict}


def _run(
    monkeypatch: pytest.MonkeyPatch, verdicts: list[str], writes: list[bool]
) -> tuple[tuple[int, int], list[str]]:
    kinds: list[str] = []
    answers = iter(writes)

    def fake_remember(_conn: Any, **kwargs: Any) -> bool:
        kinds.append(kwargs["kind"])
        return next(answers)

    monkeypatch.setattr(match_review, "remember", fake_remember)
    outcome = {"score": (1, 0)}
    expected: dict[str, Any] = {"selections": []}
    findings = {
        "evidence": [_evidence(v, i) for i, v in enumerate(verdicts)],
        "missing_information": [],
    }
    result = match_review.write_events(None, 7, outcome, expected, findings, at=AT)  # type: ignore[arg-type]
    return result, kinds


def test_a_right_verdict_remembers_an_injury_signal_and_counts_it_when_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # match_result, then the evidence: written, not written
    result, kinds = _run(monkeypatch, ["right", "right"], [True, True, False])
    assert kinds == ["match_result", "injury_signal", "injury_signal"]
    assert result == (2, 0)  # the result and the first signal counted; the second was already there


def test_a_wrong_verdict_is_an_error_and_a_context_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, kinds = _run(monkeypatch, ["wrong"], [True, True])
    assert kinds == ["match_result", "context_error"]
    assert result == (2, 1)


def test_any_other_verdict_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    result, kinds = _run(monkeypatch, ["unknown", "unverifiable"], [True])
    assert kinds == ["match_result"]
    assert result == (1, 0)
