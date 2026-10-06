"""Heavy worker jobs run on an event loop of their own (fbi.core.deadline.run_in_own_loop).

6 Oct 2026: a season of club friendlies (8,327 fixtures in one payload) held the scheduler's loop for 5 min 21 s
with blocking database work, and the in-play capture did not run meanwhile."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from fbi.core.deadline import cancel_reason, run_in_own_loop, run_with_deadline


def test_a_job_blocking_its_own_loop_does_not_hold_the_schedulers() -> None:
    main_thread = threading.get_ident()
    seen: dict[str, Any] = {}

    async def heavy() -> str:
        seen["thread"] = threading.get_ident()
        time.sleep(0.6)  # blocking work, as a psycopg write of a big payload is
        return "written"

    async def scenario() -> tuple[str, int]:
        ticks = 0

        async def live() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.05)
                ticks += 1

        ticker = asyncio.ensure_future(live())
        result = await run_in_own_loop(heavy)
        ticker.cancel()
        return result, ticks

    result, ticks = asyncio.run(scenario())
    assert result == "written" and seen["thread"] != main_thread
    assert ticks >= 6, f"the scheduler's loop ran {ticks} ticks during 0.6 s of blocking work"


def test_a_failure_reaches_the_caller() -> None:
    async def fails() -> None:
        raise ValueError("provider said no")

    with pytest.raises(ValueError, match="provider said no"):
        asyncio.run(run_in_own_loop(fails))


def test_a_deadline_cancels_the_job_in_its_own_loop_says_why_and_waits_for_it() -> None:
    seen: dict[str, Any] = {}

    async def hangs() -> str:
        time.sleep(0.2)  # blocking: the cancellation can only land at the next await
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            seen["reason"] = cancel_reason()
            seen["unwound_at"] = time.monotonic()
            raise
        return "done"

    started = time.monotonic()
    assert asyncio.run(run_with_deadline("hangs", lambda: run_in_own_loop(hangs), 0.05)) is None
    returned = time.monotonic()
    assert seen["reason"] == "timed out after 0.05 s (job deadline)"
    assert seen["unwound_at"] <= returned, "the caller waited for the job to unwind: one run at a time"
    assert returned - started < 5


def test_a_quick_job_returns_its_result_within_the_deadline() -> None:
    async def quick() -> int:
        await asyncio.sleep(0)
        return 7

    assert asyncio.run(run_with_deadline("quick", lambda: run_in_own_loop(quick), 2)) == 7
