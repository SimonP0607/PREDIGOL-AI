"""A deadline for an async job: past it, the job is cancelled and its run says why.

APScheduler starts a job only if its previous instance has ended (``max_instances=1``), so one request that
never returns used to block that job for ever. ``run_with_deadline`` cancels the job's task at its deadline;
the ledger's close (``fbi.ingestion.ledger``) reads ``cancel_reason`` for the task it runs in and records
"interrupted: timed out after N s" instead of a bare cancellation.

``run_in_own_loop`` runs a job on an event loop of its own, in a worker thread: see there.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import weakref
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_REASONS: weakref.WeakKeyDictionary[asyncio.Task[object], str] = weakref.WeakKeyDictionary()


def cancel_reason() -> str | None:
    """Why the current task is being cancelled, when a deadline did it."""
    try:
        task = asyncio.current_task()
    except RuntimeError:
        return None
    return _REASONS.get(task) if task is not None else None


async def run_with_deadline[T](name: str, job: Callable[[], Awaitable[T]], seconds: float) -> T | None:
    """Run ``job`` as its own task; cancel it after ``seconds``. Returns its result, or None when cancelled."""
    task: asyncio.Task[T] = asyncio.ensure_future(job())
    try:
        done, _ = await asyncio.wait({task}, timeout=seconds)
    except asyncio.CancelledError:  # the worker is stopping: the job stops with it
        task.cancel()
        raise
    if task in done:
        return task.result()
    _REASONS[task] = f"timed out after {seconds:g} s (job deadline)"
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    log.error("job.timed_out", job=name, seconds=int(seconds))
    return None


async def run_in_own_loop[T](job: Callable[[], Awaitable[T]]) -> T:
    """Run ``job`` on an event loop of its own, in a worker thread, and wait for it.

    The worker's jobs do their database work with blocking psycopg calls. On the scheduler's loop that work
    holds every other job: on 6 Oct 2026 one season of club friendlies (8,327 fixtures in one payload) kept the
    loop for 5 min 21 s, and on 5 Oct a fixture sync and a reference refresh for 5 min 8 s and 7 min - while
    the in-play capture, whose prices are gone if not read, did not run. A job run here keeps its blocking work
    off that loop.

    A cancellation of the caller (a deadline, the worker stopping) is passed on to the job's own task, with its
    reason (``cancel_reason``), and the caller waits for the job to unwind: ``max_instances=1`` keeps meaning
    one run at a time.
    """
    ready = threading.Event()
    handle: dict[str, Any] = {}

    async def main() -> T:
        handle["loop"] = asyncio.get_running_loop()
        handle["task"] = asyncio.current_task()
        ready.set()
        return await job()

    def target() -> T:
        try:
            with asyncio.Runner() as runner:
                return runner.run(main())
        finally:
            ready.set()

    thread = asyncio.ensure_future(asyncio.to_thread(target))
    try:
        return await asyncio.shield(thread)
    except asyncio.CancelledError:
        reason = cancel_reason()
        await asyncio.to_thread(ready.wait)
        loop, task = handle.get("loop"), handle.get("task")
        if loop is not None and task is not None:
            if reason is not None:
                _REASONS[task] = reason
            with contextlib.suppress(RuntimeError):  # the job's loop has already closed: nothing to cancel
                loop.call_soon_threadsafe(task.cancel)
        with contextlib.suppress(BaseException):
            await thread
        raise
