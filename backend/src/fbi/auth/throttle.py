"""Sign-in throttling: the lock of an address, and a cap per client.

Per address, the rule is the account's: the threshold of consecutive failures, then lock_minutes, doubling with every
further block of `threshold` failures, never more than lock_max_minutes. It is applied to EVERY address, with or
without an account, from the streak the database's audit trail holds (store.address_streak), so the answers never
tell which addresses have one (R12; plan UX, A1) - whichever of the API's worker processes answers, and after a
restart. Only failures count: a person who signs in correctly is never slowed down by somebody else's typos.

Per client (``BY_CLIENT``), a sliding window in each process's memory caps how many failures one machine may make,
whatever addresses it tries; it is the same for every address, so it tells nothing about accounts.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta


class FailureWindow:
    """At most `max_failures` failures per key in any `window_s` seconds. Only a failure keeps a key in memory, and
    the keys whose failures have all aged out are dropped every PRUNE_EVERY failures: asking whether a client is
    blocked never adds it (third review of A1 - every client that tried to sign in stayed in memory for good, about
    850 bytes each, so a stream of new addresses could fill a worker's memory)."""

    PRUNE_EVERY = 1000

    def __init__(self, *, max_failures: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._max = max_failures
        self._window = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._failures = 0

    def _recent(self, key: str, t: float) -> deque[float] | None:
        """The failures of `key` inside the window, or None (and the key forgotten) when there are none."""
        q = self._hits.get(key)
        if q is None:
            return None
        while q and t - q[0] > self._window:
            q.popleft()
        if not q:
            del self._hits[key]
            return None
        return q

    def _prune_all(self, t: float) -> None:
        stale = [k for k, q in self._hits.items() if not q or t - q[-1] > self._window]
        for k in stale:
            del self._hits[k]

    def blocked(self, key: str) -> bool:
        with self._lock:
            q = self._recent(key, self._clock())
            return q is not None and len(q) >= self._max

    def retry_after(self, key: str) -> int:
        with self._lock:
            t = self._clock()
            q = self._recent(key, t)
            if q is None or len(q) < self._max:
                return 0
            return max(1, int(self._window - (t - q[0])) + 1)

    def fail(self, key: str) -> None:
        with self._lock:
            t = self._clock()
            self._failures += 1
            if self._failures % self.PRUNE_EVERY == 0:
                self._prune_all(t)
            q = self._recent(key, t)
            if q is None:
                q = self._hits[key] = deque()
            q.append(t)

    def keys(self) -> int:
        """How many keys are held in memory."""
        with self._lock:
            return len(self._hits)

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


def lock_minutes(streak: int, *, threshold: int, minutes: int, max_minutes: int) -> int:
    """The lock a streak of consecutive failures starts: 0 below the threshold, then `minutes`, doubling with every
    further block of `threshold` failures, never more than max_minutes (store.set_failures applies the same)."""
    if streak < threshold:
        return 0
    return min(max_minutes, minutes * (1 << min(10, (streak - threshold) // threshold)))


def wait_seconds(streak: int, last_at: datetime | None, now: datetime, *, threshold: int, minutes: int,
                 max_minutes: int) -> int:
    """Seconds an address must still wait before it may try again; 0 when it may. The lock runs from its last
    failure; a wait is said in whole seconds, rounded up, at least 1 (as service._retry_after says the account's)."""
    span = lock_minutes(streak, threshold=threshold, minutes=minutes, max_minutes=max_minutes)
    if not span or last_at is None:
        return 0
    left = (last_at + timedelta(minutes=span) - now).total_seconds()
    return max(1, int(left) + 1) if left > 0 else 0


BY_CLIENT = FailureWindow(max_failures=30, window_s=15 * 60)
"""Thirty failures from one client, whatever addresses it tries."""


def reset_all() -> None:
    """The per-client windows of this process (the addresses' streaks are in the database)."""
    with BY_CLIENT._lock:
        BY_CLIENT._hits.clear()
