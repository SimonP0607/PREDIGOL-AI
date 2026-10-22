"""HTTP client behaviour, against a mock transport. No network is touched."""

from __future__ import annotations

import gzip
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.core.errors import CircuitOpenError, ProviderError, QuotaExhaustedError
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from fbi.storage.payload_store import PayloadStore

SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
OK_BODY = {"response": [{"fixture": {"id": 1001}}], "errors": [], "paging": {"current": 1, "total": 1}}


@pytest.fixture(autouse=True)
def frozen() -> Iterator[FrozenClock]:
    clock = FrozenClock(datetime(2026, 9, 15, 12, 0, tzinfo=UTC))
    set_clock(clock)
    yield clock
    set_clock(SystemClock())


def build(
    tmp_path: Path,
    handler: object,
    *,
    max_retries: int = 2,
    budget: int = 100,
) -> tuple[ApiFootballClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)  # type: ignore[operator]

    settings = ApiFootballSettings(
        key=SECRET, plan="pro", daily_budget=budget, max_retries=max_retries, timeout_seconds=1.0
    )

    async def _no_sleep(_seconds: float) -> None:
        return None

    client = ApiFootballClient(
        settings,
        PayloadStore(tmp_path),
        transport=httpx.MockTransport(_record),
        rate_limiter=TokenBucket(settings.per_minute_limit, sleep=_no_sleep),
        quota=DailyQuota(budget=budget),
    )
    return client, seen


async def test_the_key_travels_in_a_header_and_never_in_the_url(tmp_path: Path) -> None:
    client, seen = build(tmp_path, lambda r: httpx.Response(200, json=OK_BODY))
    async with client:
        await client.get("/odds", {"fixture": 1001})
    request = seen[0]
    assert request.headers["x-apisports-key"] == SECRET
    assert SECRET not in str(request.url), "a credential must never reach a URL"
    assert "fixture=1001" in str(request.url)


async def test_the_stored_payload_carries_no_credential(tmp_path: Path) -> None:
    client, _ = build(tmp_path, lambda r: httpx.Response(200, json=OK_BODY))
    async with client:
        response = await client.get("/odds", {"fixture": 1001, "apikey": SECRET})
    with gzip.open(tmp_path / response.stored.file_path, "rb") as fh:
        body = fh.read().decode()
    assert SECRET not in body
    assert response.params["apikey"] == "[REDACTED]"


async def test_a_retryable_status_is_retried_then_succeeds(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=OK_BODY)

    client, _ = build(tmp_path, handler, max_retries=3)
    async with client:
        response = await client.get("/odds", {"fixture": 1})
    assert calls["n"] == 3
    assert response.http_status == 200


async def test_a_429_consumes_the_retry_budget_and_then_raises(tmp_path: Path) -> None:
    client, seen = build(tmp_path, lambda r: httpx.Response(429, headers={"retry-after": "0"}), max_retries=2)
    async with client:
        with pytest.raises(ProviderError):
            await client.get("/odds", {"fixture": 1})
    assert len(seen) == 3, "one initial call plus two retries"


async def test_a_client_error_is_not_retried(tmp_path: Path) -> None:
    client, seen = build(tmp_path, lambda r: httpx.Response(404), max_retries=3)
    async with client:
        with pytest.raises(ProviderError, match="not retryable"):
            await client.get("/odds", {"fixture": 1})
    assert len(seen) == 1


async def test_repeated_failures_open_the_circuit(tmp_path: Path) -> None:
    client, _ = build(tmp_path, lambda r: httpx.Response(503), max_retries=0)
    async with client:
        for _ in range(5):
            with pytest.raises(ProviderError):
                await client.get("/odds", {"fixture": 1})
        with pytest.raises(CircuitOpenError):
            await client.get("/odds", {"fixture": 1})


async def test_the_daily_budget_stops_the_client(tmp_path: Path) -> None:
    client, seen = build(tmp_path, lambda r: httpx.Response(200, json=OK_BODY), budget=2)
    async with client:
        await client.get("/odds", {"fixture": 1})
        await client.get("/odds", {"fixture": 2})
        with pytest.raises(QuotaExhaustedError):
            await client.get("/odds", {"fixture": 3})
    assert len(seen) == 2, "no call is issued once the budget is gone"


async def test_a_non_json_body_is_a_payload_error_not_a_crash(tmp_path: Path) -> None:
    client, _ = build(tmp_path, lambda r: httpx.Response(200, text="<html>maintenance</html>"))
    async with client:
        with pytest.raises(ProviderError, match="not JSON"):
            await client.get("/odds", {"fixture": 1})


async def test_a_200_carrying_a_provider_error_object_is_not_treated_as_success(
    tmp_path: Path,
) -> None:
    """API-Football answers 200 with a populated `errors` object for quota and
    parameter problems. Accepting that is how a day of empty captures looks
    like a successful run."""
    body = {"response": [], "errors": {"token": "invalid"}}
    client, _ = build(tmp_path, lambda r: httpx.Response(200, json=body))
    async with client:
        with pytest.raises(ProviderError, match="provider reported errors"):
            await client.get("/odds", {"fixture": 1})


async def test_the_per_minute_limit_answered_in_the_body_is_waited_out_and_retried(tmp_path: Path) -> None:
    """5 Oct 2026 02:46 UTC: HTTP 200 with errors {"rateLimit": ...} was taken as a plain error and a backfill
    unit was lost. It is a rate limit: wait for the next minute and ask again (within the retry budget)."""
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"errors": {"rateLimit": "Too many requests. You have exceeded the "
                                                                      "limit of requests per minute of your "
                                                                      "subscription."}, "response": []})
        return httpx.Response(200, json=OK_BODY)

    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    settings = ApiFootballSettings(key=SECRET, plan="pro", daily_budget=10, max_retries=2, timeout_seconds=1.0)
    client = ApiFootballClient(settings, PayloadStore(tmp_path), transport=httpx.MockTransport(handler),
                               rate_limiter=TokenBucket(100, sleep=_sleep), quota=DailyQuota(budget=10), sleep=_sleep)
    async with client:
        response = await client.get("/players", {"league": 32, "season": 2024})
    assert response.results_count == 1 and calls["n"] == 2
    assert len(slept) == 1 and 48 <= slept[0] <= 63, "until the next minute (the clock is frozen at :00)"
