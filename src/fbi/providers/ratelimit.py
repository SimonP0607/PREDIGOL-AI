"""Rate limiting and quota accounting.

Two independent limits, because the provider enforces two:

  * requests per minute  -> a token bucket, which smooths bursts instead of
    sleeping a fixed interval between calls.
  * requests per day     -> a hard budget. When it is gone the capturer stops
    rather than issuing calls it knows will be refused.

The daily budget is deliberately configurable BELOW the plan limit, so a runaway
job cannot spend a whole day's quota in one afternoon.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date

from fbi.core.clock import now
from fbi.core.errors import QuotaExhaustedError


class TokenBucket:
    """Async token bucket. Refills continuously at ``rate`` tokens per second."""

    def __init__(
        self,
        capacity: int,
        per_seconds: float = 60.0,
        *,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._rate = capacity / per_seconds
        self._updated = now().timestamp()
        self._lock = asyncio.Lock()
        # Injectable so waiting is testable without actually waiting. Time is
        # read from the clock; only the yielding is delegated.
        self._sleep = sleep or asyncio.sleep

    @property
    def available(self) -> float:
        return self._tokens

    def _refill(self) -> None:
        current = now().timestamp()
        elapsed = max(0.0, current - self._updated)
        self._updated = current
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)

    async def acquire(self, tokens: int = 1) -> float:
        """Wait until ``tokens`` are available. Returns the seconds waited."""
        if tokens > self._capacity:
            raise ValueError(f"cannot acquire {tokens} tokens from a bucket of {self._capacity}")
        waited = 0.0
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                deficit = tokens - self._tokens
                delay = deficit / self._rate
            await self._sleep(delay)
            waited += delay


@dataclass
class DailyQuota:
    """A hard per-day call budget that resets at UTC midnight."""

    budget: int
    _day: date = field(default_factory=lambda: now().date())
    _spent: int = 0

    @property
    def spent(self) -> int:
        self._roll()
        return self._spent

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.spent)

    def _roll(self) -> None:
        today = now().date()
        if today != self._day:
            self._day = today
            self._spent = 0

    def spend(self, calls: int = 1) -> None:
        self._roll()
        if self._spent + calls > self.budget:
            raise QuotaExhaustedError(
                f"daily budget of {self.budget} calls exhausted "
                f"({self._spent} spent). The capturer stops instead of issuing "
                f"calls the provider will refuse."
            )
        self._spent += calls
