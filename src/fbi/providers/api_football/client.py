"""HTTP client for API-Football.

One persistent httpx.AsyncClient (connection reuse), one token bucket, one daily
quota, one circuit breaker, bounded concurrency, and retries with exponential
backoff plus full jitter.

Rules that are not negotiable:
  * The API key lives in a header, never in a URL or a log line.
  * Every log record passes through ``sanitize`` first.
  * A 429 is not a transient error to hammer: it consumes the retry budget and
    honours ``Retry-After`` when the provider sends one.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import structlog

from fbi.core.clock import now
from fbi.core.config.providers import ApiFootballSettings
from fbi.core.errors import ProviderError, ProviderPayloadError, RateLimitError
from fbi.ingestion.payload_store import PayloadStore, StoredPayload, sanitize

log = structlog.get_logger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class ApiResponse:
    endpoint: str
    params: dict[str, str]
    fetched_at: datetime
    http_status: int
    body: dict[str, Any]
    stored: StoredPayload

    @property
    def results(self) -> list[dict[str, Any]]:
        response = self.body.get("response")
        return response if isinstance(response, list) else []

    @property
    def results_count(self) -> int:
        return len(self.results)


class ApiFootballClient:
    def __init__(
        self,
        settings: ApiFootballSettings,
        store: PayloadStore,
        *,
        rate_limiter: Any = None,
        quota: Any = None,
        breaker: Any = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        from fbi.providers.circuit import CircuitBreaker
        from fbi.providers.ratelimit import DailyQuota, TokenBucket

        self._settings = settings
        self._store = store
        # A margin below the published limit: being throttled costs more than
        # the handful of calls this leaves on the table.
        self._bucket = rate_limiter or TokenBucket(max(1, int(settings.per_minute_limit * 0.9)))
        # In-memory fallback, for tests and for any caller that has no database.
        # It counts only within this process, so it is NOT the production path:
        # real callers go through build_client, which attaches the persistent
        # counter. The structural guard in the test suite enforces that.
        self._quota = quota or DailyQuota(budget=min(settings.daily_budget, settings.per_day_limit))
        self._breaker = breaker or CircuitBreaker(
            "api_football",
            failure_threshold=settings.circuit_failure_threshold,
            reset_seconds=settings.circuit_reset_seconds,
        )
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.timeout_seconds, connect=10.0),
            headers={
                "x-apisports-key": settings.key,  # header, never a query parameter
                "accept": "application/json",
                "user-agent": "football-intelligence/0.1 (private, non-commercial)",
            },
            limits=httpx.Limits(
                max_connections=settings.max_concurrency,
                max_keepalive_connections=settings.max_concurrency,
            ),
            transport=transport,
        )

    @property
    def quota_remaining(self) -> int:
        return self._quota.remaining

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ApiFootballClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, 60.0)
        # Exponential with FULL jitter: without jitter, parallel workers that
        # fail together retry together and reproduce the burst that failed.
        ceiling = min(2.0**attempt, 30.0)
        return random.uniform(0.0, ceiling)  # jitter, not cryptography

    async def get(self, endpoint: str, params: dict[str, Any]) -> ApiResponse:
        safe_params = sanitize(params)
        last_error: Exception | None = None

        for attempt in range(self._settings.max_retries + 1):
            self._breaker.before_call()
            self._quota.spend(1)
            await self._bucket.acquire(1)

            try:
                async with self._semaphore:
                    response = await self._client.get(endpoint, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                self._breaker.record_failure()
                last_error = ProviderError(f"{endpoint}: {exc.__class__.__name__}: {exc}")
                log.warning(
                    "provider.transport_error",
                    endpoint=endpoint,
                    params=safe_params,
                    attempt=attempt,
                    error=exc.__class__.__name__,
                )
            else:
                if response.status_code in RETRYABLE_STATUS:
                    self._breaker.record_failure()
                    retry_after = _retry_after(response)
                    last_error = (
                        RateLimitError(f"{endpoint}: HTTP 429")
                        if response.status_code == 429
                        else ProviderError(f"{endpoint}: HTTP {response.status_code}")
                    )
                    log.warning(
                        "provider.retryable_status",
                        endpoint=endpoint,
                        params=safe_params,
                        status=response.status_code,
                        attempt=attempt,
                        retry_after=retry_after,
                    )
                    if attempt < self._settings.max_retries:
                        await asyncio.sleep(self._backoff(attempt, retry_after))
                    continue

                if response.status_code >= 400:
                    self._breaker.record_failure()
                    raise ProviderError(f"{endpoint}: HTTP {response.status_code} (not retryable)")

                self._breaker.record_success()
                return self._finalise(endpoint, params, safe_params, response)

            if attempt < self._settings.max_retries:
                await asyncio.sleep(self._backoff(attempt, None))

        raise last_error or ProviderError(f"{endpoint}: exhausted retries")

    def _finalise(
        self,
        endpoint: str,
        params: dict[str, Any],
        safe_params: dict[str, str],
        response: httpx.Response,
    ) -> ApiResponse:
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderPayloadError(f"{endpoint}: response was not JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise ProviderPayloadError(f"{endpoint}: expected a JSON object, got {type(body).__name__}")

        # API-Football answers 200 with a populated "errors" object on quota and
        # parameter problems. Treating that as success is how the legacy system
        # silently stored empty days.
        errors = body.get("errors")
        if errors and not isinstance(errors, list):
            raise ProviderError(f"{endpoint}: provider reported errors: {errors}")

        fetched_at = now()
        stored = self._store.store(
            endpoint=endpoint,
            params=params,
            fetched_at=fetched_at,
            http_status=response.status_code,
            body=body,
        )
        log.info(
            "provider.ok",
            endpoint=endpoint,
            params=safe_params,
            status=response.status_code,
            results=len(body.get("response") or []),
            payload_hash=stored.hash[:12],
            cached=stored.already_present,
            quota_remaining=self._quota.remaining,
        )
        return ApiResponse(
            endpoint=endpoint,
            params=safe_params,
            fetched_at=fetched_at,
            http_status=response.status_code,
            body=body,
            stored=stored,
        )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
