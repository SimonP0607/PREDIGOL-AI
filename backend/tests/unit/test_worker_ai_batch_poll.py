"""The worker's ``ai_batch_poll`` job (plan IA, section 29): registered on the clock, short, and unable to stop the worker.

``main()`` cannot run in a unit test (it takes the worker lock and starts the clock), so the registration is read from the source of
``apps.worker.scheduler`` - as the other worker jobs' tests do."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from apps.worker import scheduler

from fbi.ai import batch

TREE = ast.parse(Path(scheduler.__file__).read_text())


def _registration(job_id: str) -> ast.Call:
    for node in ast.walk(TREE):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_job":
            for kw in node.keywords:
                if kw.arg == "id" and isinstance(kw.value, ast.Constant) and kw.value.value == job_id:
                    return node
    raise AssertionError(f"{job_id} is not registered on the clock")


def test_the_poll_is_on_the_clock_every_few_minutes_one_at_a_time() -> None:
    call = _registration("ai_batch_poll")
    kw = {k.arg: k.value for k in call.keywords if k.arg is not None}
    assert isinstance(call.args[1], ast.Constant) and call.args[1].value == "interval"
    assert isinstance(kw["max_instances"], ast.Constant) and kw["max_instances"].value == 1
    assert isinstance(kw["coalesce"], ast.Constant) and kw["coalesce"].value is True
    assert scheduler.AI_BATCH_POLL_MINUTES == 5 and "next_run_time" in kw, "it starts shortly after the worker does"


def test_the_poll_is_documented_where_the_other_jobs_are() -> None:
    assert "ai_batch_poll" in (scheduler.__doc__ or "")


class FakeConn:
    pass


@contextmanager
def fake_connect() -> Iterator[FakeConn]:
    yield FakeConn()


def test_the_job_collects_with_the_environments_settings_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def poll(conn: Any, settings: Any, *, at: Any) -> batch.PollReport:
        seen.update(conn=conn, settings=settings, at=at)
        return batch.PollReport(batches=1, ended=1, items=2, counts={"succeeded": 2})

    monkeypatch.setattr(scheduler, "_connect", fake_connect)
    monkeypatch.setattr(batch, "poll", poll)
    scheduler._ai_batch_poll_now()
    assert isinstance(seen["conn"], FakeConn) and seen["settings"].mode in ("off", "shadow", "enforce") and seen["at"] is not None


def test_a_failure_of_the_poll_is_logged_and_does_not_reach_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> Any:
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(scheduler, "_connect", boom)
    scheduler._ai_batch_poll_now()  # must not raise

    monkeypatch.setattr(scheduler, "_connect", fake_connect)
    monkeypatch.setattr(batch, "poll", lambda *a, **k: (_ for _ in ()).throw(ValueError("a handler bug")))
    scheduler._ai_batch_poll_now()  # nor this


class LogSpy:
    """Stands in for the worker's logger and keeps what it was told, as (level, event, fields) (``capture_logs`` depends on the
    process-wide configuration an earlier test may have fixed: see ``tests/integration/test_premature_final.py``)."""

    def __init__(self) -> None:
        self.said: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Any:
        def record(event: str, **fields: Any) -> None:
            self.said.append((level, event, fields))
        return record


def test_what_the_poll_abandons_is_said_as_a_warning_and_a_poll_that_leaves_a_running_cycle_alone_says_nothing(
        monkeypatch: pytest.MonkeyPatch) -> None:
    spy = LogSpy()
    monkeypatch.setattr(scheduler, "log", spy)
    monkeypatch.setattr(scheduler, "_connect", fake_connect)
    monkeypatch.setattr(batch, "poll", lambda conn, settings, *, at: batch.PollReport(abandoned=3))
    scheduler._ai_batch_poll_now()
    assert spy.said == [("warning", "ai.batch_unsent_abandoned", {"items": 3})], "recorded, never sent and no cycle running: worth a line"
    spy.said.clear()
    monkeypatch.setattr(batch, "poll", lambda conn, settings, *, at: batch.PollReport(cycle_running=True))
    scheduler._ai_batch_poll_now()
    assert spy.said == [], "a cycle that is still running owns what it recorded: nothing to say"
