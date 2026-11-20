"""A circuit breaker for the provider.

Without one, an outage turns into thousands of failing calls that burn the daily
quota and fill the logs. After ``failure_threshold`` consecutive failures the
circuit opens and calls fail immediately for ``reset_seconds``; one trial call
then decides whether to close it again.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from enum import StrEnum

import structlog

from fbi.core.clock import now
from fbi.core.errors import CircuitOpenError, ProviderAccountError

log = structlog.get_logger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, reset_seconds: float = 60.0) -> None:
        self.name = name
        self._threshold = failure_threshold
        self._reset_seconds = reset_seconds
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if self._opened_at is None:
            return CircuitState.CLOSED
        if now().timestamp() - self._opened_at >= self._reset_seconds:
            return CircuitState.HALF_OPEN
        return CircuitState.OPEN

    def before_call(self) -> None:
        state = self.state
        if state is CircuitState.OPEN:
            remaining = self._reset_seconds - (now().timestamp() - (self._opened_at or 0.0))
            raise CircuitOpenError(
                f"circuit {self.name!r} is open after {self._failures} consecutive failures; "
                f"retrying in {remaining:.0f}s"
            )

    def record_success(self) -> None:
        if self._opened_at is not None:
            log.info("circuit.closed", circuit=self.name)
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold and self._opened_at is None:
            self._opened_at = now().timestamp()
            log.warning(
                "circuit.opened",
                circuit=self.name,
                failures=self._failures,
                reset_seconds=self._reset_seconds,
            )
        elif self.state is CircuitState.HALF_OPEN:
            self._opened_at = now().timestamp()


# ── the account (plan PM, PM-04-02; BE-061: the correction of PM-01-03) ─────────────────────────────────────────────────


ACCOUNT_KEYS = frozenset({"requests", "token", "access", "subscription", "suspended"})
"""Keys of the provider's ``errors`` object that speak of the account, not of the request."""


def account_refusal(errors: Mapping[str, object], *, paid_plan: bool) -> str | None:
    """Which part of the account an HTTP 200 answer's ``errors`` object refused, or None when the error is the request's.

    On 29 Oct 2026 (OPS-009) the paid plan lapsed at 04:45 UTC and the provider answered every request with 200 and
    ``{"requests": "You have reached the request limit for the day..."}`` or ``{"plan": "Free plans do not have access..."}``: the
    breaker saw successes, and 47,000 requests of our budget went out in 16 hours for nothing. A ``plan`` error is the account's
    only on a PAID plan: on the free plan it is the honest answer for one season or date (the backfill records it as a refusal)."""
    for key, value in errors.items():
        name, text = str(key).strip().lower(), str(value).lower()
        if name in ACCOUNT_KEYS or "request limit" in text or "suspended" in text or "subscription" in text:
            return "requests" if (name == "requests" or "request limit" in text) else name
        if paid_plan and (name == "plan" or "free plan" in text):
            return "plan"
    return None


class AccountPause:
    """Every request of the process waits while the provider refuses the account (``ProviderAccountError``, raised before the
    budget is spent): ``trip`` starts a pause of ``seconds``; after it, requests go out again and the first refused one starts the
    next. On a day like 29 Oct 2026 that is one request every 15 minutes instead of thousands an hour. One per process (the worker
    is one process: ``build_client`` gives every client the same one)."""

    def __init__(self, *, seconds: float = 900.0, enabled: bool = True) -> None:
        self.seconds = seconds
        self.enabled = enabled
        self._lock = threading.Lock()
        self._until: float | None = None
        self.reason: str | None = None
        self.trips = 0

    @property
    def paused_until(self) -> float | None:
        with self._lock:
            return self._until if self._until is not None and now().timestamp() < self._until else None

    def trip(self, reason: str, *, endpoint: str = "") -> None:
        if not self.enabled:
            return
        with self._lock:
            self._until = now().timestamp() + self.seconds
            self.reason = reason
            self.trips += 1
            trips = self.trips
        log.warning("provider.account_paused", reason=reason, endpoint=endpoint, seconds=self.seconds, trips=trips,
                    hint="the provider refused the account inside an HTTP 200; no request goes out until the pause ends")

    def before_call(self) -> None:
        if not self.enabled:
            return
        until = self.paused_until
        if until is not None:
            raise ProviderAccountError(
                f"the provider refused the account ({self.reason}): every request waits "
                f"{until - now().timestamp():.0f}s more (FBI_APIFOOTBALL_ACCOUNT_GUARD)")
