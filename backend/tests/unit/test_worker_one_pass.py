"""The pick pipeline runs one pass at a time, and the capture never waits for it (9 Oct 2026, on the server).

Two passes at once only waited on each other's locks - twenty waits of about four minutes - and the tick that
waited for its pass missed its windows and its heartbeat, so the worker was restarted as stale.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
from apps.worker import scheduler
from apps.worker.scheduler import OnePass


def _blocking_pass() -> tuple[OnePass, threading.Event, threading.Event, list[float]]:
    started, release = threading.Event(), threading.Event()
    runs: list[float] = []

    def work() -> None:
        runs.append(time.monotonic())
        started.set()
        release.wait(5)

    return OnePass(work, "test"), started, release, runs


def test_requests_during_a_pass_become_exactly_one_more_pass() -> None:
    gate, started, release, runs = _blocking_pass()
    first = threading.Thread(target=gate)
    first.start()
    assert started.wait(5)
    # Three requests while the pass runs: none runs beside it, none waits for it.
    t0 = time.monotonic()
    assert [gate(), gate(), gate()] == [False, False, False]
    assert time.monotonic() - t0 < 1, "a request must never wait for the running pass"
    assert len(runs) == 1
    release.set()
    first.join(5)
    assert len(runs) == 2, "the three requests are folded into one more pass, run when the first ended"
    assert not gate.running


def test_a_request_with_nothing_running_runs_at_once() -> None:
    calls: list[int] = []
    gate = OnePass(lambda: calls.append(1), "test")
    assert gate() is True
    assert gate() is True
    assert calls == [1, 1]


def test_a_failed_pass_does_not_lose_the_request_that_waited_for_it() -> None:
    started, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def work() -> None:
        calls.append(1)
        if len(calls) == 1:
            started.set()
            release.wait(5)
            raise RuntimeError("the database went away")

    gate = OnePass(work, "test")
    first = threading.Thread(target=gate)
    first.start()
    assert started.wait(5)
    assert gate() is False
    release.set()
    first.join(5)
    assert calls == [1, 1]


def test_many_threads_never_run_two_passes_at_once() -> None:
    inside = 0
    most = 0
    lock = threading.Lock()

    def work() -> None:
        nonlocal inside, most
        with lock:
            inside += 1
            most = max(most, inside)
        time.sleep(0.01)
        with lock:
            inside -= 1

    gate = OnePass(work, "test")
    threads = [threading.Thread(target=gate) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert most == 1
    assert not gate.running


async def test_the_capture_asks_for_a_pass_without_waiting_for_it(monkeypatch: pytest.MonkeyPatch) -> None:
    gate, started, release, runs = _blocking_pass()
    monkeypatch.setattr(scheduler, "_pipeline_now", gate)
    t0 = time.monotonic()
    scheduler._request_pipeline()
    assert time.monotonic() - t0 < 0.5
    await asyncio.to_thread(started.wait, 5)
    assert gate.running and len(runs) == 1
    release.set()
    while scheduler._background:
        await asyncio.sleep(0.01)
    assert len(runs) == 1 and not gate.running
