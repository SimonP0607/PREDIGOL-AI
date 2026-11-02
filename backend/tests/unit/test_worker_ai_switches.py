"""The worker's ``ai_switches`` job (plan IA, review of phase 2, M5): on the clock every ten minutes and a minute after the worker starts, one at a
time, writing the owner's words to the ledger when they changed - and on whatever the switches say, because it is the trace OF the switches - and
unable to stop the worker.

``main()`` cannot run in a unit test (it takes the worker lock and starts the clock), so the registration is read from the source of
``apps.worker.scheduler`` - as the other worker jobs' tests do."""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from apps.worker import scheduler

from fbi.ai import gates

TREE = ast.parse(Path(scheduler.__file__).read_text())


def _registrations(job_id: str) -> list[ast.Call]:
    found = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_job":
            for kw in node.keywords:
                if kw.arg == "id" and isinstance(kw.value, ast.Constant) and kw.value.value == job_id:
                    found.append(node)
    return found


def test_the_job_is_on_the_clock_every_ten_minutes_one_at_a_time_and_starts_with_the_worker() -> None:
    (call,) = _registrations("ai_switches")  # once, and only once
    kw = {k.arg: k.value for k in call.keywords if k.arg is not None}
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "_ai_switches"
    assert isinstance(call.args[1], ast.Constant) and call.args[1].value == "interval"
    assert ast.unparse(kw["minutes"]) == "AI_SWITCHES_MINUTES"
    assert isinstance(kw["max_instances"], ast.Constant) and kw["max_instances"].value == 1
    assert isinstance(kw["coalesce"], ast.Constant) and kw["coalesce"].value is True
    assert ast.unparse(kw["misfire_grace_time"]) == "AI_SWITCHES_MINUTES * 60"
    assert ast.unparse(kw["next_run_time"]) == "moment + timedelta(minutes=1)", "a new worker - a changed environment - writes it within the minute"
    assert scheduler.AI_SWITCHES_MINUTES == 10


def test_the_job_is_documented_where_the_other_jobs_are() -> None:
    doc = scheduler.__doc__ or ""
    assert "``ai_switches``" in doc and "gate ``switches``" in doc and "ai.feature_gates" in doc


class FakeConn:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


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


def test_the_job_writes_the_words_of_the_environment_and_says_the_row(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def record(conn: Any, settings: Any, *, at: datetime, code_version: str | None = None) -> int:
        seen.update(conn=conn, settings=settings, at=at, code_version=code_version)
        return 41

    opened, spy = connections(monkeypatch), LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    monkeypatch.setattr(gates, "record_switches", record)
    environment(monkeypatch, FBI_AI_NATIVE_SCHEMA="1", FBI_AI_RESEARCH_V2="shadow")  # words the defaults do not have
    scheduler._ai_switches_now()
    assert len(opened) == 1 and seen["conn"] is opened[0] and opened[0].commits == 1, "one connection, committed"
    words = gates.switch_words(seen["settings"])
    assert words["switches"]["native_schema"] == "on" and words["research_v2"] == "shadow", "the job runs with what the environment says"
    assert isinstance(seen["at"], datetime) and seen["at"].tzinfo is not None
    assert seen["code_version"], "and says which code wrote the row"
    assert spy.said == [("info", "ai.switches.recorded", {"row": 41})]


def test_when_the_words_did_not_change_it_leaves_no_trace_in_the_log(monkeypatch: pytest.MonkeyPatch) -> None:
    opened, spy = connections(monkeypatch), LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    monkeypatch.setattr(gates, "record_switches", lambda conn, settings, *, at, code_version=None: None)
    environment(monkeypatch)
    scheduler._ai_switches_now()
    assert len(opened) == 1 and spy.said == [], "it asked once and found the same words: no line in the log"


@pytest.mark.parametrize("env", [{"FBI_AI_MODE": "off"}, {"FBI_AI_PACKAGE": "0"}, {"FBI_AI_BATCH": "0"}, {"FBI_AI_CACHE": "off", "FBI_AI_MODE": "off"}])
def test_no_switch_turns_it_off_because_it_is_the_trace_of_the_switches(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    called: list[int] = []
    opened = connections(monkeypatch)
    monkeypatch.setattr(gates, "record_switches", lambda conn, settings, *, at, code_version=None: called.append(1))
    environment(monkeypatch, **env)
    scheduler._ai_switches_now()
    assert len(opened) == 1 and called == [1]


def test_a_failure_is_logged_and_does_not_reach_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    connections(monkeypatch)

    def boom(conn: Any, settings: Any, *, at: datetime, code_version: str | None = None) -> int:
        raise RuntimeError("the table is not there " + "x" * 500)

    monkeypatch.setattr(gates, "record_switches", boom)
    environment(monkeypatch)
    scheduler._ai_switches_now()  # must not raise
    (level, event, fields), = spy.said
    assert (level, event) == ("error", "ai.switches.failed") and fields["error"].startswith("RuntimeError: the table is not there")
    assert len(fields["error"]) <= 300


def test_not_even_a_connection_that_cannot_be_opened_reaches_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)

    @contextmanager
    def no_database() -> Iterator[None]:
        raise ConnectionError("down")
        yield  # pragma: no cover

    monkeypatch.setattr(scheduler, "_connect", no_database)
    environment(monkeypatch)
    scheduler._ai_switches_now()  # nor this
    assert [(level, event) for level, event, _ in spy.said] == [("error", "ai.switches.failed")]
