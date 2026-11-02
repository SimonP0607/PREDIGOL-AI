"""The worker's ``ai_package`` job (plan IA, phase 1): on the clock every few minutes, one at a time, switched off by ``FBI_AI_PACKAGE=0`` or
``FBI_AI_MODE=off`` without even opening a connection, and unable to stop the worker.

``main()`` cannot run in a unit test (it takes the worker lock and starts the clock), so the registration is read from the source of
``apps.worker.scheduler`` - as the other worker jobs' tests do."""

from __future__ import annotations

import ast
import asyncio
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from apps.worker import scheduler

from fbi.ai import match_runs
from fbi.ai.cycle import CycleReport

TREE = ast.parse(Path(scheduler.__file__).read_text())


def _registrations(job_id: str) -> list[ast.Call]:
    found = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_job":
            for kw in node.keywords:
                if kw.arg == "id" and isinstance(kw.value, ast.Constant) and kw.value.value == job_id:
                    found.append(node)
    return found


def test_the_job_is_on_the_clock_every_few_minutes_one_at_a_time() -> None:
    (call,) = _registrations("ai_package")  # once, and only once
    kw = {k.arg: k.value for k in call.keywords if k.arg is not None}
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "_ai_package"
    assert isinstance(call.args[1], ast.Constant) and call.args[1].value == "interval"
    assert ast.unparse(kw["minutes"]) == "AI_PACKAGE_MINUTES"
    assert isinstance(kw["max_instances"], ast.Constant) and kw["max_instances"].value == 1
    assert isinstance(kw["coalesce"], ast.Constant) and kw["coalesce"].value is True
    assert ast.unparse(kw["misfire_grace_time"]) == "AI_PACKAGE_MINUTES * 60"
    assert "next_run_time" in kw, "it starts shortly after the worker does"
    assert scheduler.AI_PACKAGE_MINUTES == 10


def test_the_job_is_documented_where_the_other_jobs_are() -> None:
    doc = scheduler.__doc__ or ""
    assert "``ai_package``" in doc and "FBI_AI_PACKAGE=0" in doc and "ai.match_runs" in doc


class FakeConn:
    pass


def connections(monkeypatch: pytest.MonkeyPatch) -> list[FakeConn]:
    """Stands in for the worker's connection and keeps the ones it opened."""
    opened: list[FakeConn] = []

    @contextmanager
    def fake_connect() -> Iterator[FakeConn]:
        opened.append(FakeConn())
        yield opened[-1]

    monkeypatch.setattr(scheduler, "_connect", fake_connect)
    return opened


class LogSpy:
    """Stands in for the module's logger and keeps what it was told, as (level, event, fields)."""

    def __init__(self) -> None:
        self.said: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Callable[..., None]:
        def record(event: str, **fields: Any) -> None:
            self.said.append((level, event, fields))
        return record


def environment(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    monkeypatch.setattr("fbi.ai.config.environment", lambda: dict(env))


def test_the_job_builds_with_the_environments_settings_and_says_what_it_did(monkeypatch: pytest.MonkeyPatch) -> None:
    report = CycleReport(cycle_id=7, status="partial")
    report.counts.update({"pending": 3, "built": 2, "refused": 1})
    seen: dict[str, Any] = {}

    def run(conn: Any, settings: Any, *, at: datetime) -> CycleReport:
        seen.update(conn=conn, settings=settings, at=at)
        return report

    opened, spy = connections(monkeypatch), LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    monkeypatch.setattr(match_runs, "run", run)
    environment(monkeypatch, FBI_AI_MODE="shadow", FBI_AI_BATCH_MIN_LEAD_MINUTES="500")  # a value the defaults do not have
    scheduler._ai_package_now()
    assert len(opened) == 1 and seen["conn"] is opened[0]
    assert seen["settings"].mode == "shadow" and seen["settings"].package is True
    assert seen["settings"].batch_min_lead_minutes == 500, "the job runs with what the environment says, not with the defaults"
    assert isinstance(seen["at"], datetime) and seen["at"].tzinfo is not None
    assert spy.said == [("info", "ai.package", {"status": "partial", "cycle": 7, "pending": 3, "built": 2, "refused": 1})]


def test_a_run_with_nothing_to_do_leaves_no_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    opened, spy = connections(monkeypatch), LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    monkeypatch.setattr(match_runs, "run", lambda conn, settings, *, at: None)
    environment(monkeypatch)
    scheduler._ai_package_now()
    assert len(opened) == 1 and spy.said == [], "it asked once and found nothing: no line in the log"


def test_what_it_could_not_do_is_said_with_the_first_three_reasons_cut_short(monkeypatch: pytest.MonkeyPatch) -> None:
    report = CycleReport(cycle_id=8, status="failed")
    report.counts["failed"] = 5
    report.errors = [f"failed, match {n}: {'x' * 400}" for n in range(5)]
    spy = LogSpy()
    connections(monkeypatch)
    monkeypatch.setattr(scheduler, "log", spy)
    monkeypatch.setattr(match_runs, "run", lambda conn, settings, *, at: report)
    environment(monkeypatch)
    scheduler._ai_package_now()
    assert [(level, event) for level, event, _ in spy.said] == [("info", "ai.package"), ("warning", "ai.package.errors")]
    fields = spy.said[1][2]
    assert fields["total"] == 5 and len(fields["errors"]) == 3
    assert fields["errors"] == [e[:200] for e in report.errors[:3]] and all(len(e) == 200 for e in fields["errors"])


@pytest.mark.parametrize("env", [{"FBI_AI_MODE": "off"}, {"FBI_AI_PACKAGE": "0"}, {"FBI_AI_PACKAGE": "off"}, {"FBI_AI_PACKAGE": " False "},
                                  {"FBI_AI_MODE": "off", "FBI_AI_PACKAGE": "0"}])
def test_switched_off_it_does_not_even_open_a_connection(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    called: list[int] = []
    opened, spy = connections(monkeypatch), LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    monkeypatch.setattr(match_runs, "run", lambda *a, **k: called.append(1))
    environment(monkeypatch, **env)
    scheduler._ai_package_now()
    assert not opened and not called and spy.said == []


@pytest.mark.parametrize("env", [{}, {"FBI_AI_MODE": "shadow"}, {"FBI_AI_MODE": "enforce"}, {"FBI_AI_PACKAGE": "1"}, {"FBI_AI_PACKAGE": "yes"},
                                  {"FBI_AI_MODE": "shadow", "FBI_AI_PACKAGE": "on"}])
def test_otherwise_it_runs_and_by_default(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    called: list[int] = []
    opened = connections(monkeypatch)
    monkeypatch.setattr(match_runs, "run", lambda *a, **k: called.append(1))
    environment(monkeypatch, **env)
    scheduler._ai_package_now()
    assert len(opened) == 1 and called == [1]


def test_a_failure_is_logged_and_does_not_reach_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    environment(monkeypatch)

    def boom() -> Any:
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(scheduler, "_connect", boom)
    scheduler._ai_package_now()  # must not raise
    assert spy.said == [("error", "ai.package.failed", {"error": "RuntimeError: the database is gone"})]

    spy.said.clear()
    connections(monkeypatch)
    monkeypatch.setattr(match_runs, "run", lambda *a, **k: (_ for _ in ()).throw(ValueError("a handler bug")))
    scheduler._ai_package_now()  # nor this
    assert spy.said == [("error", "ai.package.failed", {"error": "ValueError: a handler bug"})]

    spy.said.clear()
    monkeypatch.setattr("fbi.ai.config.environment", boom)  # nor an environment that cannot be read
    scheduler._ai_package_now()
    assert [(level, event) for level, event, _ in spy.said] == [("error", "ai.package.failed")]


def test_the_error_line_is_short(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    connections(monkeypatch)
    environment(monkeypatch)
    monkeypatch.setattr(match_runs, "run", lambda *a, **k: (_ for _ in ()).throw(ValueError("y" * 1000)))
    scheduler._ai_package_now()
    assert len(spy.said[0][2]["error"]) == 300


def test_the_clock_gives_each_run_a_new_id_and_runs_the_job_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    threads: dict[str, int] = {}

    def job() -> None:
        order.append("job")
        threads["job"] = threading.get_ident()

    async def tick() -> None:
        threads["loop"] = threading.get_ident()
        await scheduler._ai_package()

    monkeypatch.setattr(scheduler, "new_run_id", lambda: order.append("id"))
    monkeypatch.setattr(scheduler, "_ai_package_now", job)
    asyncio.run(tick())
    assert order == ["id", "job"]
    assert threads["job"] != threads["loop"], "a build that takes seconds must not hold the event loop of the worker"
