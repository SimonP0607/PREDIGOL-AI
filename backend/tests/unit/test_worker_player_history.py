"""The worker's ``player_history`` job (plan F3): known to the watchdog, switchable off, every few hours and once a day."""

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
    assert "player_history" in scheduler.WORKER_JOB_TYPES, "a run left open by a restarted worker would never be closed"
    assert "player_history" in JOB_TIMEOUTS
    assert timeout_for("player_history").total_seconds() == 3 * 3600, "room for the daily sweep over everyone"
    assert timeout_for("player_history").total_seconds() <= scheduler.PLAYER_HISTORY_MINUTES * 60, (
        "a pass is over, or cancelled, when the next is due")


def test_the_pass_and_the_daily_sweep_are_registered_only_while_the_switch_is_on() -> None:
    registered = _registrations()
    assert {"player_history", "player_history_sweep"} <= set(registered)
    guarded: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "PLAYER_HISTORY_ENABLED":
            for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr == "add_job":
                    for kw in inner.keywords:
                        if kw.arg == "id" and isinstance(kw.value, ast.Constant):
                            guarded.add(str(kw.value.value))
    assert guarded == {"player_history", "player_history_sweep"}, "FBI_PLAYER_HISTORY=0 switches it off without a deploy"

    every_pass = registered["player_history"]
    assert ast.unparse(every_pass.args[1]) == "'interval'"
    assert ast.unparse(_keywords(every_pass)["minutes"]) == "PLAYER_HISTORY_MINUTES"
    assert ast.unparse(_keywords(every_pass)["max_instances"]) == "1"
    sweep = registered["player_history_sweep"]
    assert ast.unparse(sweep.args[1]) == "'cron'" and ast.unparse(_keywords(sweep)["timezone"]) == "'UTC'"
    assert ast.unparse(_keywords(sweep)["hour"]) == "PLAYER_HISTORY_SWEEP_HOUR"
    assert ast.unparse(_keywords(sweep)["minute"]) == "PLAYER_HISTORY_SWEEP_MINUTE"
    sweep_at = (scheduler.PLAYER_HISTORY_SWEEP_HOUR, scheduler.PLAYER_HISTORY_SWEEP_MINUTE)
    assert sweep_at == (10, 0), "after the sweeps of the structure (09:40) and the referees (09:50)"
    assert sweep_at > (scheduler.REFEREE_SWEEP_HOUR, scheduler.REFEREE_SWEEP_MINUTE) > (
        scheduler.STRUCTURE_SWEEP_HOUR, scheduler.STRUCTURE_SWEEP_MINUTE)


def test_both_clocks_are_wrapped_with_the_deadline_of_the_ledger_job() -> None:
    wrapped = {}
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_deadline":
            wrapped[ast.unparse(node.args[0])] = ast.unparse(node.args[1])
    assert wrapped["'player_history'"] == "'player_history'" and wrapped["'player_history_sweep'"] == "'player_history'"


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
    monkeypatch.setattr("fbi.ingestion.player_history.run_job", run_job)
    return seen


def test_the_clock_runs_the_pass_in_a_thread_and_the_sweep_is_the_audited_one(calls: list[dict[str, Any]]) -> None:
    asyncio.run(scheduler._player_history())
    asyncio.run(scheduler._player_history_sweep())
    assert [bool(c.get("sweep")) for c in calls] == [False, True]
    assert all(isinstance(c["conn"], FakeConnection) for c in calls)
