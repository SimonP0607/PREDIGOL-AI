"""The worker's ``referee_identity`` job (plan F3): known to the watchdog, switchable off, once an hour and once a day."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from apps.worker import scheduler

from fbi.ops.run_watchdog import JOB_TIMEOUTS, timeout_for

TREE = ast.parse(Path(scheduler.__file__).read_text())


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


def test_the_watchdog_knows_the_job_and_gives_it_a_deadline_of_its_own() -> None:
    assert "referee_identity" in scheduler.WORKER_JOB_TYPES, "a run left open by a restarted worker would never be closed"
    assert "referee_identity" in JOB_TIMEOUTS
    assert timeout_for("referee_identity").total_seconds() == 30 * 60


def test_the_pass_and_the_daily_sweep_are_registered_only_while_the_switch_is_on() -> None:
    registered = _registrations()
    assert {"referee_identity", "referee_identity_sweep"} <= set(registered)
    guarded: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "REFEREE_ENABLED":
            for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "add_job":
                    for kw in inner.keywords:
                        if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                            guarded.add(str(kw.value.value))
    assert guarded == {"referee_identity", "referee_identity_sweep"}, "FBI_REFEREE_IDENTITY=0 switches it off without a deploy"

    every_pass = registered["referee_identity"]
    assert ast.unparse(every_pass.args[1]) == "'interval'"
    assert ast.unparse(_keywords(every_pass)["minutes"]) == "REFEREE_MINUTES"
    assert ast.unparse(_keywords(every_pass)["max_instances"]) == "1"
    sweep = registered["referee_identity_sweep"]
    assert ast.unparse(sweep.args[1]) == "'cron'" and ast.unparse(_keywords(sweep)["timezone"]) == "'UTC'"
    assert ast.unparse(_keywords(sweep)["hour"]) == "REFEREE_SWEEP_HOUR"
    assert (scheduler.REFEREE_SWEEP_HOUR, scheduler.REFEREE_SWEEP_MINUTE) == (9, 50), "after the structure sweep of 09:40"
    assert (scheduler.REFEREE_SWEEP_HOUR, scheduler.REFEREE_SWEEP_MINUTE) > (scheduler.STRUCTURE_SWEEP_HOUR, scheduler.STRUCTURE_SWEEP_MINUTE)
    assert timeout_for("referee_identity").total_seconds() < scheduler.REFEREE_MINUTES * 60, "a pass ends before the next is due"


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
    monkeypatch.setattr("fbi.ingestion.referee_identity.run_job", run_job)
    return seen


def test_the_clock_runs_the_pass_in_a_thread_and_the_sweep_is_the_audited_one(calls: list[dict[str, Any]]) -> None:
    asyncio.run(scheduler._referee_identity())
    asyncio.run(scheduler._referee_identity_sweep())
    assert [bool(c.get("sweep")) for c in calls] == [False, True]
    assert all(isinstance(c["conn"], FakeConnection) for c in calls)
