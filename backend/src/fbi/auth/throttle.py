"""Sign-in throttling: failures counted per address and per client, in memory.

One API process serves the platform, so a process-local count is exact. Only failures
count: a person who signs in correctly is never slowed down by somebody else's typos.

Per address (``ADDRESSES``) the rule is the account's lock in the database (store.record_failure): the threshold of
consecutive failures, then lock_minutes, doubling with every further block of failures, up to lock_max_minutes. It is
counted for EVERY address, with or without an account, so the answers never tell which addresses have one (R12; plan
UX, A1). Per client (``BY_CLIENT``) a sliding window caps how many failures one machine may make, whatever addresses
it tries.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
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


class AddressLocks:
    """Consecutive failures per address and the lock they lead to.

    ``fail`` counts one more failure and, from the threshold on, (re)locks the address: lock_minutes, doubling with
    every further block of `threshold` failures, never more than max_minutes - exactly store.record_failure, so an
    address with an account and one without get the same answers and the same waits. The streak ends only with a
    successful sign-in (``clear``), as the account's does. At most `max_keys` addresses are remembered (the least
    recently failed are forgotten first): a flood of invented addresses cannot grow the API's memory without end.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, max_keys: int = 100_000) -> None:
        self._clock = clock
        self._max = max_keys
        self._state: OrderedDict[str, tuple[int, float]] = OrderedDict()
        """address -> (consecutive failures, locked until on the clock; 0 = not locked)"""
        self._lock = threading.Lock()

    @staticmethod
    def _seconds(left: float) -> int:
        """A wait as the account's lock says it (service._retry_after): whole seconds, rounded up, at least 1."""
        return max(1, int(left) + 1)

    def wait(self, key: str) -> int:
        """Seconds the address must still wait; 0 when it may try."""
        with self._lock:
            state = self._state.get(key)
            if state is None:
                return 0
            left = state[1] - self._clock()
            return self._seconds(left) if left > 0 else 0

    def fail(self, key: str, *, threshold: int, lock_minutes: int, max_minutes: int) -> int:
        """One more failure. The seconds of the lock it starts, or 0 below the threshold."""
        with self._lock:
            streak = self._state.pop(key, (0, 0.0))[0] + 1
            locked_until = 0.0
            if streak >= threshold:
                minutes = min(max_minutes, lock_minutes * 2 ** min(10, (streak - threshold) // threshold))
                locked_until = self._clock() + minutes * 60
            self._state[key] = (streak, locked_until)
            while len(self._state) > self._max:
                self._state.popitem(last=False)
            return self._seconds(minutes * 60) if locked_until else 0

    def streak(self, key: str) -> int:
        with self._lock:
            return self._state.get(key, (0, 0.0))[0]

    def clear(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)


ADDRESSES = AddressLocks()
"""Every address that is tried, with or without an account: the account's rule (FBI_AUTH_LOCK_*)."""
BY_CLIENT = FailureWindow(max_failures=30, window_s=15 * 60)
"""Thirty failures from one client, whatever addresses it tries."""


def reset_all() -> None:
    with ADDRESSES._lock:
        ADDRESSES._state.clear()
    with BY_CLIENT._lock:
        BY_CLIENT._hits.clear()
