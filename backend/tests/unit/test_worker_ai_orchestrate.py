"""The worker's ``ai_orchestrate`` job (plan IA, phase 3): on the clock every few minutes, one at a time, inert until the owner's three words
(``FBI_AI_ENGINES``, ``FBI_AI_SHADOW_SAMPLE``, ``FBI_AI_AGENTS``) switch the shadow on - and then it does not even open a connection - holding no
cycle lock, leaving one row of ``ai.cycles`` of kind ``orchestrate`` and unable to stop the worker.

``main()`` cannot run in a unit test, so the registration is read from the source of ``apps.worker.scheduler``, as the other jobs' tests do. The
orchestrator itself is another module (``fbi.ai.orchestrator``): here a stub stands in its place in ``sys.modules``."""

from __future__ import annotations

import ast
import asyncio
import os
import sys
import threading
import types
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from apps.worker import scheduler

from fbi.ai import cycle
from fbi.ai.cycle import CycleReport

TREE = ast.parse(Path(scheduler.__file__).read_text())
ON = {"FBI_AI_MODE": "shadow", "FBI_AI_ENGINES": "rules,llm,ma-v1,ma-v1-h", "FBI_AI_SHADOW_SAMPLE": "0.3", "FBI_AI_AGENTS": "match,council"}


def _registrations(job_id: str) -> list[ast.Call]:
    found = []
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_job":
            for kw in node.keywords:
                if kw.arg == "id" and isinstance(kw.value, ast.Constant) and kw.value.value == job_id:
                    found.append(node)
    return found


def test_the_job_is_on_the_clock_every_few_minutes_one_at_a_time() -> None:
    (call,) = _registrations("ai_orchestrate")
    kw = {k.arg: k.value for k in call.keywords if k.arg is not None}
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == "_ai_orchestrate"
    assert isinstance(call.args[1], ast.Constant) and call.args[1].value == "interval"
    assert ast.unparse(kw["minutes"]) == "AI_ORCHESTRATE_MINUTES"
    assert isinstance(kw["max_instances"], ast.Constant) and kw["max_instances"].value == 1
    assert isinstance(kw["coalesce"], ast.Constant) and kw["coalesce"].value is True
    assert ast.unparse(kw["misfire_grace_time"]) == "AI_ORCHESTRATE_MINUTES * 60"
    assert ast.unparse(kw["next_run_time"]) == "moment + timedelta(minutes=6)", "staggered after ai_package (+4)"
    assert scheduler.AI_ORCHESTRATE_MINUTES == 5


def test_the_job_is_not_wrapped_in_a_deadline_nor_does_it_take_the_cycle_lock() -> None:
    (call,) = _registrations("ai_orchestrate")
    assert "_deadline" not in ast.unparse(call)
    fn = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == "_ai_orchestrate_now")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert not {n for n in names if "lock" in n.lower()}, "it runs beside the analysis cycle: no CYCLE_LOCK, no advisory lock"


def test_the_job_is_documented_where_the_other_jobs_are() -> None:
    doc = scheduler.__doc__ or ""
    assert "``ai_orchestrate``" in doc and "FBI_AI_ORCHESTRATE_MINUTES" in doc and "ai.cycles" in doc and "fbi.ai.orchestrator" in doc
    assert "FBI_AI_SHADOW_SAMPLE" in doc


@pytest.mark.parametrize(("raw", "minutes"), [("5", 5), ("1", 1), ("0", 1), ("-3", 1), ("12", 12)])
def test_the_period_is_at_least_one_minute(monkeypatch: pytest.MonkeyPatch, raw: str, minutes: int) -> None:
    """The constant is read when the module loads: the same expression, evaluated with the word the owner wrote."""
    node = next(n for n in TREE.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "AI_ORCHESTRATE_MINUTES" for t in n.targets))
    monkeypatch.setenv("FBI_AI_ORCHESTRATE_MINUTES", raw)
    assert eval(compile(ast.Expression(node.value), "<period>", "eval"), {"os": os, "max": max, "int": int}) == minutes


# ── behaviour ─────────────────────────────────────────────────────────────────────────────────────────────────


class FakeConn:
    pass


def connections(monkeypatch: pytest.MonkeyPatch) -> list[FakeConn]:
    opened: list[FakeConn] = []

    @contextmanager
    def fake_connect() -> Iterator[FakeConn]:
        opened.append(FakeConn())
        yield opened[-1]

    monkeypatch.setattr(scheduler, "_connect", fake_connect)
    return opened


class LogSpy:
    def __init__(self) -> None:
        self.said: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Callable[..., None]:
        def record(event: str, **fields: Any) -> None:
            self.said.append((level, event, fields))
        return record


def environment(monkeypatch: pytest.MonkeyPatch, **env: str) -> None:
    monkeypatch.setattr("fbi.ai.config.environment", lambda: dict(env))


@dataclass(frozen=True)
class StubReport:
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return dict(self.data)


class Stub:
    """Stands in ``sys.modules['fbi.ai.orchestrator']`` and records what ``run`` was asked."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, answer: StubReport | Exception) -> None:
        self.calls: list[tuple[Any, Any, dict[str, Any]]] = []
        self.answer = answer
        module = types.ModuleType("fbi.ai.orchestrator")
        module.run = self.run  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "fbi.ai.orchestrator", module)

    def run(self, conn: Any, settings: Any, **kwargs: Any) -> StubReport:
        self.calls.append((conn, settings, kwargs))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class Cycles:
    """Stands in ``open_cycle`` / ``close_cycle``: keeps what the job opened and closed."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.opened: list[tuple[Any, str, datetime, Any]] = []
        self.closed: list[tuple[Any, int, CycleReport, datetime]] = []
        monkeypatch.setattr(cycle, "open_cycle", self.open)
        monkeypatch.setattr(cycle, "close_cycle", self.close)

    def open(self, conn: Any, kind: str, *, at: datetime, settings: Any) -> int:
        self.opened.append((conn, kind, at, settings))
        return 41

    def close(self, conn: Any, cycle_id: int, report: CycleReport, *, at: datetime) -> None:
        self.closed.append((conn, cycle_id, report, at))


REPORT = {"skipped": None, "considered": 6, "sampled": 2, "ran": 2, "failed_open": 0, "calls": 5, "cost_usd": Decimal("0.0421"),
          "invalid": 0, "budget_stop": None, "circuit_open": ["ma-v1"], "too_late": 1, "escalated": 1, "escalation_skipped": 0}


def test_the_job_runs_the_orchestrator_between_a_cycle_opened_and_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    opened, spy, cycles = connections(monkeypatch), LogSpy(), Cycles(monkeypatch)
    stub = Stub(monkeypatch, StubReport(REPORT))
    monkeypatch.setattr(scheduler, "log", spy)
    environment(monkeypatch, **ON, FBI_AI_BATCH_MIN_LEAD_MINUTES="500")
    scheduler._ai_orchestrate_now()

    (conn,) = opened
    ((c_conn, c_settings, kwargs),) = stub.calls
    assert c_conn is conn and c_settings.orchestrate is True and isinstance(kwargs["at"], datetime) and kwargs["at"].tzinfo is not None
    assert set(kwargs) == {"at"}, "the defaults of run (limit, time, provider, ledger) are the orchestrator's own"
    assert c_settings.batch_min_lead_minutes == 500, "it runs with what the environment says"

    ((o_conn, kind, o_at, o_settings),) = cycles.opened
    assert (o_conn, kind, o_at, o_settings) == (conn, "orchestrate", kwargs["at"], c_settings)
    ((x_conn, cycle_id, report, x_at),) = cycles.closed
    assert x_conn is conn and cycle_id == 41 and x_at == kwargs["at"]
    assert report.status == "ok" and report.cost_usd == Decimal("0.0421")
    assert report.detail is not None and report.detail["ran"] == 2 and report.detail["circuit_open"] == ["ma-v1"]
    assert report.detail["cost_usd"] == "0.0421", "plain JSON: a Decimal travels as text"

    ((level, event, fields),) = spy.said
    assert (level, event) == ("info", "ai.orchestrate")
    assert fields["cycle"] == 41 and fields["status"] == "ok" and fields["ran"] == 2 and fields["calls"] == 5 and fields["too_late"] == 1
    assert fields["cost_usd"] == "0.0421" and "circuit_open" not in fields


@pytest.mark.parametrize("env", [{}, {"FBI_AI_MODE": "off", **{k: v for k, v in ON.items() if k != "FBI_AI_MODE"}}, {**ON, "FBI_AI_AGENTS": "match"},
                                  {**ON, "FBI_AI_SHADOW_SAMPLE": "0"}, {**ON, "FBI_AI_ENGINES": "rules,llm"},
                                  {"FBI_AI_ENGINES": "rules,llm,ma-v1", "FBI_AI_SHADOW_SAMPLE": "0.3"}])
def test_switched_off_it_does_not_even_open_a_connection(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    opened, spy, cycles = connections(monkeypatch), LogSpy(), Cycles(monkeypatch)
    stub = Stub(monkeypatch, StubReport(REPORT))
    monkeypatch.setattr(scheduler, "log", spy)
    environment(monkeypatch, **env)
    scheduler._ai_orchestrate_now()
    assert not opened and not stub.calls and not cycles.opened and not cycles.closed and spy.said == []


def test_switched_off_it_does_not_even_look_for_the_orchestrator(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the module absent (as before the engineer's branch is merged) an off job is still silent: nothing is imported before the switch."""
    monkeypatch.delitem(sys.modules, "fbi.ai.orchestrator", raising=False)
    monkeypatch.setattr(sys, "meta_path", [])  # nothing can be imported that is not already loaded
    spy = LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    environment(monkeypatch)
    scheduler._ai_orchestrate_now()
    assert spy.said == []


def test_a_report_that_skipped_is_an_ok_cycle_with_its_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    opened, spy, cycles = connections(monkeypatch), LogSpy(), Cycles(monkeypatch)
    Stub(monkeypatch, StubReport({"skipped": "over_budget", "considered": 0, "ran": 0, "failed_open": 3, "cost_usd": Decimal(0)}))
    monkeypatch.setattr(scheduler, "log", spy)
    environment(monkeypatch, **ON)
    scheduler._ai_orchestrate_now()
    assert len(opened) == 1
    ((_, _, report, _),) = cycles.closed
    assert report.status == "ok", "a run that chose not to run is not a failure, whatever else the report carries"
    assert report.detail is not None and report.detail["skipped"] == "over_budget"
    assert spy.said[0][:2] == ("info", "ai.orchestrate") and spy.said[0][2]["skipped"] == "over_budget"


@pytest.mark.parametrize(("ran", "failed", "status"), [(2, 0, "ok"), (2, 1, "partial"), (0, 2, "failed"), (0, 0, "ok")])
def test_the_status_of_the_cycle_follows_the_engines_that_failed_open(monkeypatch: pytest.MonkeyPatch, ran: int, failed: int, status: str) -> None:
    connections(monkeypatch)
    cycles = Cycles(monkeypatch)
    Stub(monkeypatch, StubReport({**REPORT, "ran": ran, "failed_open": failed}))
    monkeypatch.setattr(scheduler, "log", LogSpy())
    environment(monkeypatch, **ON)
    scheduler._ai_orchestrate_now()
    assert cycles.closed[0][2].status == status


def test_an_odd_report_does_not_break_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cost that is not a number, a negative one, a nested Decimal and a set: all become plain JSON and a valid cost."""
    connections(monkeypatch)
    cycles = Cycles(monkeypatch)
    Stub(monkeypatch, StubReport({"cost_usd": "not a number", "circuit_open": {"ma-v1"}, "nested": {"x": Decimal("1.5")}}))
    monkeypatch.setattr(scheduler, "log", LogSpy())
    environment(monkeypatch, **ON)
    scheduler._ai_orchestrate_now()
    report = cycles.closed[0][2]
    assert report.cost_usd == Decimal(0) and report.detail == {"cost_usd": "not a number", "circuit_open": ["ma-v1"], "nested": {"x": "1.5"}}
    assert scheduler._orchestrate_cycle_report({"cost_usd": "-4"}, cycle_id=1).cost_usd == Decimal(0), "the column refuses a negative cost"


def test_an_orchestrator_that_raises_is_logged_the_cycle_closed_as_failed_and_nothing_reaches_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    opened, spy, cycles = connections(monkeypatch), LogSpy(), Cycles(monkeypatch)
    Stub(monkeypatch, RuntimeError("y" * 1000))
    monkeypatch.setattr(scheduler, "log", spy)
    environment(monkeypatch, **ON)
    scheduler._ai_orchestrate_now()  # must not raise
    assert len(opened) == 1 and len(cycles.closed) == 1
    report = cycles.closed[0][2]
    assert report.status == "failed" and report.cycle_id == 41 and report.detail is None and report.errors[0].startswith("RuntimeError: yyy")
    ((level, event, fields),) = spy.said
    assert (level, event) == ("error", "ai.orchestrate.failed") and len(fields["error"]) == 300


def test_a_report_that_cannot_be_read_is_a_failure_too(monkeypatch: pytest.MonkeyPatch) -> None:
    connections(monkeypatch)
    cycles, spy = Cycles(monkeypatch), LogSpy()
    stub = Stub(monkeypatch, StubReport())
    stub.answer = types.SimpleNamespace(to_json=lambda: (_ for _ in ()).throw(ValueError("no json")))  # type: ignore[assignment]
    monkeypatch.setattr(scheduler, "log", spy)
    environment(monkeypatch, **ON)
    scheduler._ai_orchestrate_now()
    assert cycles.closed[0][2].status == "failed" and spy.said == [("error", "ai.orchestrate.failed", {"error": "ValueError: no json"})]


def test_the_other_failures_are_logged_and_do_not_reach_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    environment(monkeypatch, **ON)
    Cycles(monkeypatch)
    Stub(monkeypatch, StubReport(REPORT))

    def boom() -> Any:
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(scheduler, "_connect", boom)
    scheduler._ai_orchestrate_now()
    assert spy.said == [("error", "ai.orchestrate.failed", {"error": "RuntimeError: the database is gone"})]

    spy.said.clear()
    monkeypatch.setattr("fbi.ai.config.environment", boom)  # an environment that cannot be read
    scheduler._ai_orchestrate_now()
    assert [(level, event) for level, event, _ in spy.said] == [("error", "ai.orchestrate.failed")]

    spy.said.clear()  # the orchestrator module itself is broken (not importable)
    environment(monkeypatch, **ON)
    connections(monkeypatch)
    monkeypatch.setitem(sys.modules, "fbi.ai.orchestrator", None)
    scheduler._ai_orchestrate_now()
    assert [(level, event) for level, event, _ in spy.said] == [("error", "ai.orchestrate.failed")]


def test_a_cycle_that_cannot_be_closed_does_not_reach_the_worker_either(monkeypatch: pytest.MonkeyPatch) -> None:
    connections(monkeypatch)
    Cycles(monkeypatch)
    spy = LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    Stub(monkeypatch, RuntimeError("first"))

    def refuse(*a: Any, **k: Any) -> None:
        raise ConnectionError("gone")

    monkeypatch.setattr(cycle, "close_cycle", refuse)
    environment(monkeypatch, **ON)
    scheduler._ai_orchestrate_now()
    assert [(level, event) for level, event, _ in spy.said] == [("error", "ai.orchestrate.failed")]


def test_the_clock_gives_each_run_a_new_id_and_runs_the_job_off_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    threads: dict[str, int] = {}

    def job() -> None:
        order.append("job")
        threads["job"] = threading.get_ident()

    async def tick() -> None:
        threads["loop"] = threading.get_ident()
        await scheduler._ai_orchestrate()

    monkeypatch.setattr(scheduler, "new_run_id", lambda: order.append("id"))
    monkeypatch.setattr(scheduler, "_ai_orchestrate_now", job)
    asyncio.run(tick())
    assert order == ["id", "job"] and threads["job"] != threads["loop"]


# ── cycle.close_cycle: the additive ``detail`` ─────────────────────────────────────────────────────────────────


class RecordingCursor:
    def __init__(self, sink: list[tuple[str, tuple[Any, ...]]]) -> None:
        self.sink = sink

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.sink.append((sql, params))


class RecordingConn:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.steps: list[str] = []

    def rollback(self) -> None:
        self.steps.append("rollback")

    def commit(self) -> None:
        self.steps.append("commit")

    def cursor(self, **_: Any) -> RecordingCursor:
        return RecordingCursor(self.executed)


def test_close_cycle_keeps_writing_the_counts_unless_a_detail_is_given() -> None:
    at = datetime.fromisoformat("2026-11-03T12:00:00+00:00")
    plain = CycleReport(cycle_id=1, status="partial")
    plain.counts.update({"built": 2})
    conn = RecordingConn()
    cycle.close_cycle(conn, 1, plain, at=at)  # type: ignore[arg-type]
    assert conn.steps == ["rollback", "commit"]
    assert conn.executed[0][1][2].obj == {"built": 2}, "as before: a cycle without a detail writes its counts"

    detailed = CycleReport(cycle_id=2, detail={"skipped": "x", "ran": 0}, errors=["a", "b"])
    conn = RecordingConn()
    cycle.close_cycle(conn, 2, detailed, at=at)  # type: ignore[arg-type]
    params = conn.executed[0][1]
    assert params[2].obj == {"skipped": "x", "ran": 0} and params[4] == "a; b" and params[5] == 2
