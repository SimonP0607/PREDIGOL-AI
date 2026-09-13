"""Single source of time.

Nothing in the codebase calls ``datetime.now()`` directly. Everything goes through
here, which makes every time-dependent code path testable by swapping the clock.
The legacy system called ``datetime.now()`` and ``datetime.utcnow()`` in 40+ places,
which is why none of its temporal logic could be tested.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Real wall-clock time, always timezone-aware UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Deterministic clock for tests."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock requires a timezone-aware datetime")
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, **kwargs: float) -> None:
        from datetime import timedelta

        self._at = self._at + timedelta(**kwargs)


_clock: Clock = SystemClock()


def set_clock(clock: Clock) -> None:
    global _clock
    _clock = clock


def now() -> datetime:
    return _clock.now()


def today() -> date:
    return _clock.now().date()


def day_start() -> datetime:
    """Midnight UTC of the current day, by the application clock.

    "Today" has to mean exactly one thing across the quota counter, the health
    checks and the quality snapshot, or the three of them disagree about how
    many requests have been spent. It used to be computed in three places, and
    one of them used the DATABASE's clock, which is how that disagreement was
    found.
    """
    return _clock.now().replace(hour=0, minute=0, second=0, microsecond=0)
