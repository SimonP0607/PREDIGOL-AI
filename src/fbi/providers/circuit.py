"""A circuit breaker for the provider.

Without one, an outage turns into thousands of failing calls that burn the daily
quota and fill the logs. After ``failure_threshold`` consecutive failures the
circuit opens and calls fail immediately for ``reset_seconds``; one trial call
then decides whether to close it again.
"""

from __future__ import annotations

from enum import StrEnum

import structlog

from fbi.core.clock import now
from fbi.core.errors import CircuitOpenError

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
