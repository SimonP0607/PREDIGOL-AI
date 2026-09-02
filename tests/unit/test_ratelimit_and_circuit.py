"""Rate limiting, quota and circuit breaker."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.errors import CircuitOpenError, QuotaExhaustedError
from fbi.providers.circuit import CircuitBreaker, CircuitState
from fbi.providers.ratelimit import DailyQuota, TokenBucket


@pytest.fixture()
def frozen() -> FrozenClock:
    clock = FrozenClock(datetime(2026, 9, 15, 12, 0, tzinfo=UTC))
    set_clock(clock)
    yield clock
    set_clock(SystemClock())


async def test_a_full_bucket_grants_immediately(frozen: FrozenClock) -> None:
    bucket = TokenBucket(capacity=10, per_seconds=60)
    for _ in range(10):
        assert await bucket.acquire() == 0.0
    assert bucket.available == pytest.approx(0.0, abs=1e-6)


async def test_an_empty_bucket_makes_the_caller_wait(frozen: FrozenClock) -> None:
    """The third call is delayed, not refused. Time is advanced by the fake
    sleep, so the test proves the arithmetic without spending 30 real seconds."""
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        frozen.advance(seconds=seconds)

    bucket = TokenBucket(capacity=2, per_seconds=60, sleep=fake_sleep)
    assert await bucket.acquire() == 0.0
    assert await bucket.acquire() == 0.0

    waited = await bucket.acquire()
    assert slept, "the third call went through without waiting"
    assert waited == pytest.approx(30.0, abs=0.5), "2 tokens per 60s means ~30s per token"


async def test_asking_for_more_than_the_bucket_holds_is_a_programming_error() -> None:
    bucket = TokenBucket(capacity=5)
    with pytest.raises(ValueError, match="cannot acquire"):
        await bucket.acquire(6)


def test_the_daily_budget_stops_the_capturer_instead_of_burning_calls(frozen: FrozenClock) -> None:
    quota = DailyQuota(budget=3)
    for _ in range(3):
        quota.spend()
    assert quota.remaining == 0
    with pytest.raises(QuotaExhaustedError, match="daily budget"):
        quota.spend()


def test_the_budget_resets_at_utc_midnight(frozen: FrozenClock) -> None:
    quota = DailyQuota(budget=2)
    quota.spend(2)
    assert quota.remaining == 0
    frozen.advance(hours=13)  # crosses midnight UTC
    assert quota.remaining == 2
    quota.spend()


def test_the_circuit_opens_after_consecutive_failures(frozen: FrozenClock) -> None:
    breaker = CircuitBreaker("t", failure_threshold=3, reset_seconds=60)
    breaker.before_call()
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    with pytest.raises(CircuitOpenError, match="is open"):
        breaker.before_call()


def test_a_success_before_the_threshold_resets_the_count(frozen: FrozenClock) -> None:
    breaker = CircuitBreaker("t", failure_threshold=3)
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED


def test_the_circuit_half_opens_after_the_reset_window(frozen: FrozenClock) -> None:
    breaker = CircuitBreaker("t", failure_threshold=2, reset_seconds=60)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    frozen.advance(seconds=61)
    assert breaker.state is CircuitState.HALF_OPEN
    breaker.before_call()  # a trial call is allowed
    breaker.record_success()
    assert breaker.state is CircuitState.CLOSED
