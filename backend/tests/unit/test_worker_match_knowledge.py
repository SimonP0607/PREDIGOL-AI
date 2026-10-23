"""The worker's ``match_knowledge`` job (plan F7): known to the watchdog, bounded, switchable off, and doing what it says.

``main()`` cannot be run in a unit test (it takes the worker lock and starts the clock), so the registration is read from the source of
``apps.worker.scheduler`` - the part that went wrong before: a job added to the clock and forgotten by the watchdog, whose runs then stay
"running" for ever after a restart."""

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

from fbi.knowledge import builder
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
    out: dict[str, ast.Call] = {}
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_job":
            for kw in node.keywords:
                if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                    out[str(kw.value.value)] = node
    return out


def _keywords(call: ast.Call) -> dict[str, ast.expr]:
    return {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}


def test_the_job_is_one_the_clock_wraps_with_a_deadline_and_the_watchdog_knows() -> None:
    jobs = _deadline_jobs()
    assert ("match_knowledge", "match_knowledge") in jobs and ("match_knowledge_sweep", "match_knowledge") in jobs
    assert "match_knowledge" in scheduler.WORKER_JOB_TYPES, "a run left open by a worker that was restarted would never be closed"
    assert "match_knowledge" in JOB_TIMEOUTS, "it would get the six hours of a job nobody thought about"
    assert builder.JOB == "match_knowledge"


def test_the_passes_fit_inside_their_interval_and_the_deadline() -> None:
    deadline = timeout_for("match_knowledge").total_seconds()
    assert deadline == 20 * 60
    assert scheduler.KNOWLEDGE_RUN_SECONDS < scheduler.KNOWLEDGE_MINUTES * 60, "a pass ends before the next one is due"
    assert scheduler.KNOWLEDGE_RUN_SECONDS < scheduler.KNOWLEDGE_SWEEP_SECONDS < deadline, (
        "the time budget stops the work between chunks of matches before the deadline cancels it in the middle of one")


def test_the_pass_looks_at_the_last_days_and_the_sweep_at_the_last_year_and_a_bit() -> None:
    assert scheduler.KNOWLEDGE_DAYS == builder.DEFAULT_DAYS == 10
    assert scheduler.KNOWLEDGE_SWEEP_DAYS == 400 > scheduler.KNOWLEDGE_DAYS
    assert scheduler.KNOWLEDGE_PER_RUN == 300


def test_a_pass_and_the_daily_sweep_are_registered_only_while_the_switch_is_on() -> None:
    registered = _registrations()
    assert {"match_knowledge", "match_knowledge_sweep"} <= set(registered)

    guarded: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "KNOWLEDGE_ENABLED":
            for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "add_job":
                    for kw in inner.keywords:
                        if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                            guarded.add(str(kw.value.value))
    assert guarded == {"match_knowledge", "match_knowledge_sweep"}, "FBI_MATCH_KNOWLEDGE=0 is how it is switched off without a deploy"

    every_pass = registered["match_knowledge"]
    assert ast.unparse(every_pass.args[1]) == "'interval'"
    assert ast.unparse(_keywords(every_pass)["minutes"]) == "KNOWLEDGE_MINUTES"
    assert ast.unparse(_keywords(every_pass)["max_instances"]) == "1", "a pass never starts beside the previous one"

    sweep = registered["match_knowledge_sweep"]
    assert ast.unparse(sweep.args[1]) == "'cron'"
    sweep_at = _keywords(sweep)
    assert ast.unparse(sweep_at["timezone"]) == "'UTC'"
    assert ast.unparse(sweep_at["hour"]) == "KNOWLEDGE_SWEEP_HOUR"
    assert (scheduler.KNOWLEDGE_SWEEP_HOUR, scheduler.KNOWLEDGE_SWEEP_MINUTE) == (10, 30), (
        "05:30 in Bogotá: after the stages and ties (09:40), the referees (09:50) and the players (10:00) of the day have been refreshed, "
        "before the research monitor (12:05) and the leak audit (12:50)")


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
    monkeypatch.setattr("fbi.ingestion.match_knowledge.run_job", run_job)
    return seen


def test_a_pass_builds_the_matches_of_the_last_days_within_its_budget(calls: list[dict[str, Any]]) -> None:
    scheduler._match_knowledge_now()

    assert len(calls) == 1
    call = calls[0]
    assert isinstance(call["conn"], FakeConnection)
    assert isinstance(call["now"], datetime) and call["now"].tzinfo is not None
    assert (call["days"], call["max_seconds"], call["limit"]) == (scheduler.KNOWLEDGE_DAYS, scheduler.KNOWLEDGE_RUN_SECONDS,
                                                                  scheduler.KNOWLEDGE_PER_RUN)


def test_the_sweep_reads_the_wide_window_with_no_limit_and_a_longer_budget(calls: list[dict[str, Any]]) -> None:
    scheduler._match_knowledge_now(sweep=True)

    assert len(calls) == 1
    assert (calls[0]["days"], calls[0]["limit"], calls[0]["max_seconds"]) == (scheduler.KNOWLEDGE_SWEEP_DAYS, None,
                                                                             scheduler.KNOWLEDGE_SWEEP_SECONDS)


def test_the_clock_calls_them_in_a_thread_and_the_sweep_is_the_wide_pass(calls: list[dict[str, Any]]) -> None:
    asyncio.run(scheduler._match_knowledge())
    asyncio.run(scheduler._match_knowledge_sweep())

    assert [c["days"] for c in calls] == [scheduler.KNOWLEDGE_DAYS, scheduler.KNOWLEDGE_SWEEP_DAYS]
    assert abs(calls[0]["now"] - datetime.now(calls[0]["now"].tzinfo)) < timedelta(minutes=1)
