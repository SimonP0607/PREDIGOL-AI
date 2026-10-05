"""A deadline for an async job: past it, the job is cancelled and its run says why.

APScheduler starts a job only if its previous instance has ended (``max_instances=1``), so one request that
never returns used to block that job for ever. ``run_with_deadline`` cancels the job's task at its deadline;
the ledger's close (``fbi.ingestion.ledger``) reads ``cancel_reason`` for the task it runs in and records
"interrupted: timed out after N s" instead of a bare cancellation.
"""

from __future__ import annotations

import asyncio
import contextlib
import weakref
from collections.abc import Awaitable, Callable

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
