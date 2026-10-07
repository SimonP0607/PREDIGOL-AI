"""Request limits kept in memory, per API process.

Two processes serve the API on the server, so a client can get up to twice a limit; that is fine for what these
are for - stopping a runaway loop or a scraper from pinning the database - and the sign-in lock-out, which must be
exact, lives in the database instead (auth.users.failed_logins). Cloudflare adds its own rule at the edge.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SlidingWindow:
    """At most `per_window` hits per key in any `window_s` seconds."""

    PRUNE_EVERY = 1000

    def __init__(self, per_window: int, window_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._per_window = per_window
        self._window_s = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def _prune_all(self, t: float) -> None:
        stale = [k for k, q in self._hits.items() if not q or t - q[-1] > self._window_s]
        for k in stale:
            del self._hits[k]

    def allow(self, key: str) -> bool:
        with self._lock:
            t = self._clock()
            self._calls += 1
            if self._calls % self.PRUNE_EVERY == 0:
                self._prune_all(t)
            q = self._hits.setdefault(key, deque())
            while q and t - q[0] > self._window_s:
                q.popleft()
            if len(q) >= self._per_window:
                return False
            q.append(t)
            return True

    def keys(self) -> int:
        return len(self._hits)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class BodyTooLargeError(Exception):
    pass


class BodyLimit:
    """Refuses a request body over `max_bytes` with 413 - by its Content-Length when it declares one, and by
    counting when it streams - before the application reads it into memory."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        declared = next((v for k, v in scope.get("headers", []) if k == b"content-length"), None)
        if declared is not None:
            try:
                too_big = int(declared) > self.max_bytes
            except ValueError:
                too_big = True
            if too_big:
                await _refuse(send)
                return
        seen = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except BodyTooLargeError:
            if not started:
                await _refuse(send)


async def _refuse(send: Send) -> None:
    body = b'{"status":"error","error":{"code":"payload_too_large","message":"request body too large"}}'
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            (b"connection", b"close")]})
    await send({"type": "http.response.body", "body": body})
