"""A short-lived memory of answers that are the same for every reader: the boards (Home, Picks, best prices, the
parlays, the day's matches), the catalogue and the search.

Why: the rehearsal of 7 Oct 2026 (real data, 100 -> 200 signed-in users) showed every reader recomputing the same
boards - the database's CPU, not the number of people, was the limit. With this, a board is computed once per
`seconds` per process and per set of arguments; the rest of the readers get that answer.

What is never kept here: anything personal (/me/*, the account, sessions), the live board and the match centre
(in-play data), and anything the reader writes. Keys are the arguments after the connection, so a SUPER_ADMIN's
shadow preview (include_shadow=True) is a different entry from what users see.

Off unless FBI_API_CACHE=1: the server's API turns it on (deploy/vps/docker-compose.yml); the worker, the scripts
and the tests, which call the same functions, always compute. One computation per key at a time: while one request
refreshes an entry, the others for the same key wait for it instead of all hitting the database.
"""

from __future__ import annotations

import functools
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

MAX_ENTRIES = 512


def enabled() -> bool:
    return os.environ.get("FBI_API_CACHE", "0").strip().lower() in {"1", "true", "yes", "on"}


class _Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.entries: OrderedDict[tuple[str, str], tuple[float, Any]] = OrderedDict()
        self.key_locks: dict[tuple[str, str], threading.Lock] = {}

    def get(self, key: tuple[str, str]) -> tuple[bool, Any]:
        with self.lock:
            hit = self.entries.get(key)
            if hit is None or hit[0] < time.monotonic():
                return False, None
            self.entries.move_to_end(key)
            return True, hit[1]

    def put(self, key: tuple[str, str], value: Any, seconds: float) -> None:
        with self.lock:
            self.entries[key] = (time.monotonic() + seconds, value)
            self.entries.move_to_end(key)
            while len(self.entries) > MAX_ENTRIES:
                old, _ = self.entries.popitem(last=False)
                self.key_locks.pop(old, None)

    def key_lock(self, key: tuple[str, str]) -> threading.Lock:
        with self.lock:
            lock = self.key_locks.get(key)
            if lock is None:
                lock = self.key_locks[key] = threading.Lock()
            return lock

    def clear(self) -> None:
        with self.lock:
            self.entries.clear()
            self.key_locks.clear()


_STORE = _Store()


def clear() -> None:
    _STORE.clear()


def shared(seconds: float) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """For a service function whose FIRST argument is the database connection: the answer is kept `seconds`,
    keyed by the other arguments (their repr - dates, decimals and frozen dataclasses included)."""

    def wrap(fn: Callable[P, R]) -> Callable[P, R]:
        name = f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def inner(*args: P.args, **kwargs: P.kwargs) -> R:
            if not enabled():
                return fn(*args, **kwargs)
            key = (name, repr((args[1:], sorted(kwargs.items()))))
            found, value = _STORE.get(key)
            if found:
                return value  # type: ignore[no-any-return]
            with _STORE.key_lock(key):
                found, value = _STORE.get(key)  # another request may have just computed it
                if found:
                    return value  # type: ignore[no-any-return]
                value = fn(*args, **kwargs)
                _STORE.put(key, value, seconds)
                return value

        return inner

    return wrap
