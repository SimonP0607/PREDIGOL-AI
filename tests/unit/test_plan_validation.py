"""A plan that would capture nonsense is refused before any request is spent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fbi.odds.schedule import CaptureTask, validate_plan

NOW = datetime(2026, 9, 14, 19, 0, tzinfo=UTC)
KO = NOW + timedelta(hours=24)


def task(
    fid: int = 1001,
    kind: Literal["prematch", "near_close"] = "prematch",
    window: int = 1440,
    mtk: int = 1440,
    ko: datetime = KO,
) -> CaptureTask:
    return CaptureTask(provider_fixture_id=fid, kickoff_at=ko, kind=kind, window_minutes=window, minutes_to_ko=mtk)


def test_a_clean_plan_passes_and_estimates_one_request_per_task() -> None:
    check = validate_plan([task(1001), task(1002)], at=NOW, budget_remaining=100, known_fixture_ids={1001, 1002})
    assert check.ok and check.estimated_requests == 2


def test_duplicate_windows_are_refused() -> None:
    check = validate_plan([task(), task()], at=NOW, budget_remaining=100)
    assert any("duplicate" in i for i in check.issues)


def test_a_fixture_that_already_kicked_off_is_refused() -> None:
    check = validate_plan([task(ko=NOW - timedelta(minutes=1))], at=NOW, budget_remaining=100)
    assert any("not in the future" in i for i in check.issues)


def test_an_unknown_fixture_is_refused() -> None:
    check = validate_plan([task(9999)], at=NOW, budget_remaining=100, known_fixture_ids={1001})
    assert any("unknown to the database" in i for i in check.issues)


def test_a_plan_beyond_the_remaining_budget_is_refused() -> None:
    check = validate_plan([task(i) for i in range(1, 7)], at=NOW, budget_remaining=5)
    assert any("budget" in i for i in check.issues)
    assert check.estimated_requests == 6


def test_an_implausible_distance_to_kickoff_is_refused() -> None:
    check = validate_plan([task(mtk=60 * 24 * 30)], at=NOW, budget_remaining=100)
    assert any("implausible" in i for i in check.issues)
