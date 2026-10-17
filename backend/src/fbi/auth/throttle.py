"""Sign-in throttling: failures counted per address and per client, in memory.

One API process serves the platform, so a process-local window is exact. Only failures
count: a person who signs in correctly is never slowed down by somebody else's typos.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class FailureWindow:
    def __init__(self, *, max_failures: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._max = max_failures
        self._window = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, t: float) -> deque[float]:
        q = self._hits.setdefault(key, deque())
        while q and t - q[0] > self._window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, self._clock())) >= self._max

    def retry_after(self, key: str) -> int:
        with self._lock:
            t = self._clock()
            q = self._prune(key, t)
            if len(q) < self._max:
                return 0
            return max(1, int(self._window - (t - q[0])) + 1)

    def fail(self, key: str) -> None:
        with self._lock:
            t = self._clock()
            self._prune(key, t).append(t)

    def clear(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


BY_EMAIL = FailureWindow(max_failures=5, window_s=15 * 60)
"""Five wrong passwords for one address in fifteen minutes and that address waits."""
BY_CLIENT = FailureWindow(max_failures=30, window_s=15 * 60)
"""Thirty failures from one client, whatever addresses it tries."""


def reset_all() -> None:
    for w in (BY_EMAIL, BY_CLIENT):
        with w._lock:
            w._hits.clear()
