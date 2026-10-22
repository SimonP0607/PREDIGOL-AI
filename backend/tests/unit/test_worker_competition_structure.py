"""The worker's ``competition_structure`` job (plan F2): known to the watchdog, bounded, switchable off, and doing what it says.

``main()`` cannot be run in a unit test (it takes the worker lock and starts the clock), so the registration is read from the
source of ``apps.worker.scheduler`` - the part that went wrong before: a job added to the clock and forgotten by the watchdog,
whose runs then stay "running" for ever after a restart."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from apps.worker import scheduler

from fbi.ops.run_watchdog import JOB_TIMEOUTS, timeout_for

TREE = ast.parse(Path(scheduler.__file__).read_text())


def _deadline_jobs() -> list[tuple[str, str]]:
    """(job id, ledger job type) of every ``_deadline("id", "type", fn)`` the scheduler registers."""
    found: list[tuple[str, str]] = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_deadline":
            first, second = node.args[0], node.args[1]
            assert isinstance(first, ast.Constant) and isinstance(second, ast.Constant), "job ids are written out"
            found.append((str(first.value), str(second.value)))
    return found


def _registrations() -> dict[str, ast.Call]:
    """The ``scheduler.add_job(...)`` calls that name their id, by id."""
    out: dict[str, ast.Call] = {}
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_job":
            for kw in node.keywords:
                if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                    out[str(kw.value.value)] = node
    return out


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}


def test_every_job_the_clock_wraps_with_a_deadline_is_one_the_watchdog_knows() -> None:
    jobs = _deadline_jobs()
    assert ("competition_structure", "competition_structure") in jobs
    assert ("competition_structure_sweep", "competition_structure") in jobs
    for job_id, job_type in jobs:
        assert job_type in scheduler.WORKER_JOB_TYPES, (
            f"{job_id}: a run of '{job_type}' left open by a worker that was restarted would never be closed")
        assert job_type in JOB_TIMEOUTS, f"{job_id}: '{job_type}' has no timeout of its own (it would get the 6 hours default)"


def test_the_passes_fit_inside_their_interval_and_the_deadline() -> None:
    deadline = timeout_for("competition_structure").total_seconds()
    assert deadline == 20 * 60
    assert scheduler.STRUCTURE_RUN_SECONDS < scheduler.STRUCTURE_MINUTES * 60, "a pass ends before the next one is due"
    assert scheduler.STRUCTURE_RUN_SECONDS < scheduler.STRUCTURE_SWEEP_SECONDS < deadline, (
        "the time budget stops the work between seasons before the deadline cancels it in the middle of one")


def test_a_pass_and_the_daily_sweep_are_registered_only_while_the_switch_is_on() -> None:
    registered = _registrations()
    assert {"competition_structure", "competition_structure_sweep"} <= set(registered)

    guarded: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "STRUCTURE_ENABLED":
            for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "add_job":
                    for kw in inner.keywords:
                        if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                            guarded.add(str(kw.value.value))
    assert guarded == {"competition_structure", "competition_structure_sweep"}, (
        "FBI_COMPETITION_STRUCTURE=0 is how it is switched off without a deploy")

    every_pass = registered["competition_structure"]
    assert ast.unparse(every_pass.args[1]) == "'interval'"
    assert ast.unparse(_keywords(every_pass)["minutes"]) == "STRUCTURE_MINUTES"
    assert ast.unparse(_keywords(every_pass)["max_instances"]) == "1", "a pass never starts beside the previous one"

    sweep = registered["competition_structure_sweep"]
    assert ast.unparse(sweep.args[1]) == "'cron'"
    sweep_at = _keywords(sweep)
    assert ast.unparse(sweep_at["timezone"]) == "'UTC'"
    assert ast.unparse(sweep_at["hour"]) == "STRUCTURE_SWEEP_HOUR"
    assert (scheduler.STRUCTURE_SWEEP_HOUR, scheduler.STRUCTURE_SWEEP_MINUTE) == (9, 40), (
        "04:40 in Bogotá: after the night's matches are settled, before the AI's 07:05 - 07:50 work")


class FakeConnection:
    pass


@contextmanager
def _fake_connect() -> Iterator[FakeConnection]:
    yield FakeConnection()


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def run_job(conn: Any, **kwargs: Any) -> None:
        seen.append({"conn": conn, **kwargs})

    monkeypatch.setattr(scheduler, "_connect", _fake_connect)
    monkeypatch.setattr("fbi.competitions.builder.run_job", run_job)
    return seen


def test_a_pass_builds_the_pending_seasons_within_its_budget(calls: list[dict[str, Any]]) -> None:
    scheduler._competition_structure_now()

    assert len(calls) == 1
    call = calls[0]
    assert isinstance(call["conn"], FakeConnection)
    assert isinstance(call["now"], datetime) and call["now"].tzinfo is not None
    assert call["max_seconds"] == scheduler.STRUCTURE_RUN_SECONDS
    assert call["limit"] == scheduler.STRUCTURE_PER_RUN
    assert "everything" not in call, "a pass is not the sweep"


def test_the_sweep_reads_every_season_with_no_limit_and_a_longer_budget(calls: list[dict[str, Any]]) -> None:
    scheduler._competition_structure_now(everything=True)

    assert len(calls) == 1
    assert calls[0]["everything"] is True and calls[0]["limit"] is None
    assert calls[0]["max_seconds"] == scheduler.STRUCTURE_SWEEP_SECONDS


def test_the_clock_calls_them_in_a_thread_and_the_sweep_is_the_everything_pass(calls: list[dict[str, Any]]) -> None:
    asyncio.run(scheduler._competition_structure())
    asyncio.run(scheduler._competition_structure_sweep())

    assert [bool(c.get("everything")) for c in calls] == [False, True]
    assert abs(calls[0]["now"] - datetime.now(calls[0]["now"].tzinfo)) < timedelta(minutes=1)
