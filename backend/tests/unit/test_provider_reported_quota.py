"""What the provider says of our quota in its answers' headers (plan Cuotas, BE-011; E18 of the plan: nobody read them): parsed in
any case, kept through the client's reporter at most every ``REPORT_EVERY_SECONDS`` and once more on close, and never at the cost
of a request. Against a mock transport; no network, no database."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.quota import ReportedQuota, parse_reported
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from fbi.storage.payload_store import PayloadStore

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
BODY = {"response": [{"fixture": {"id": 1001}}], "errors": [], "paging": {"current": 1, "total": 1}}
HEADERS = {"x-ratelimit-requests-limit": "75000", "x-ratelimit-requests-remaining": "51234",
           "X-RateLimit-Limit": "450", "X-RateLimit-Remaining": "449"}


@pytest.fixture(autouse=True)
def frozen() -> Iterator[FrozenClock]:
    clock = FrozenClock(NOW)
    set_clock(clock)
    yield clock
    set_clock(SystemClock())


def client(tmp_path: Path, responses: list[httpx.Response], kept: list[ReportedQuota], *,
           report_every: float = 30.0, reporter: object | None = None) -> ApiFootballClient:
    queue = list(responses)

    def handler(_request: httpx.Request) -> httpx.Response:
        return queue.pop(0)

    async def no_sleep(_seconds: float) -> None:
        return None

    settings = ApiFootballSettings(key="k" * 32, plan="pro", daily_budget=100, max_retries=1, timeout_seconds=1.0)
    return ApiFootballClient(settings, PayloadStore(tmp_path), transport=httpx.MockTransport(handler),
                             rate_limiter=TokenBucket(settings.per_minute_limit, sleep=no_sleep),
                             quota=DailyQuota(budget=100), sleep=no_sleep,
                             quota_reporter=reporter or kept.append,  # type: ignore[arg-type]
                             report_every=report_every)


def test_the_four_headers_are_read_in_any_case() -> None:
    got = parse_reported(httpx.Headers(HEADERS), at=NOW)
    assert got == ReportedQuota(NOW, 75000, 51234, 450, 449)
    shouted = httpx.Headers({k.upper(): v for k, v in HEADERS.items()})
    assert parse_reported(shouted, at=NOW) == got


def test_an_answer_without_them_or_with_garbage_says_nothing() -> None:
    assert parse_reported(httpx.Headers({"content-type": "application/json"}), at=NOW) is None
    assert parse_reported(httpx.Headers({"x-ratelimit-requests-remaining": "many"}), at=NOW) is None
    partial = parse_reported(httpx.Headers({"x-ratelimit-requests-remaining": " 12 "}), at=NOW)
    assert partial == ReportedQuota(NOW, None, 12, None, None)


async def test_every_answer_is_read_and_kept_at_most_every_thirty_seconds_and_on_close(tmp_path: Path) -> None:
    kept: list[ReportedQuota] = []
    responses = [httpx.Response(200, json=BODY, headers={**HEADERS, "x-ratelimit-requests-remaining": str(n)})
                 for n in (100, 99, 98)]
    c = client(tmp_path, responses, kept)
    async with c:
        await c.get("/odds", {"fixture": 1})
        await c.get("/odds", {"fixture": 2})
        await c.get("/odds", {"fixture": 3})
        assert c.reported_quota is not None and c.reported_quota.requests_remaining == 98, "the newest answer's"
        assert [k.requests_remaining for k in kept] == [100], "the first at once; the next ones wait for the interval"
    assert [k.requests_remaining for k in kept] == [100, 98], "and the newest when the client closes"


async def test_a_429_carries_the_count_too(tmp_path: Path) -> None:
    kept: list[ReportedQuota] = []
    responses = [httpx.Response(429, headers={**HEADERS, "x-ratelimit-requests-remaining": "0"}),
                 httpx.Response(200, json=BODY, headers={**HEADERS, "x-ratelimit-requests-remaining": "0"})]
    c = client(tmp_path, responses, kept, report_every=0.0)
    async with c:
        await c.get("/odds", {"fixture": 1})
    assert [k.requests_remaining for k in kept] == [0, 0]


async def test_a_reporter_that_fails_never_costs_the_request(tmp_path: Path) -> None:
    def broken(_reported: ReportedQuota) -> None:
        raise RuntimeError("the database is away")

    c = client(tmp_path, [httpx.Response(200, json=BODY, headers=HEADERS)], [], reporter=broken)
    async with c:
        answer = await c.get("/odds", {"fixture": 1})
    assert answer.http_status == 200 and c.reported_quota is not None


async def test_without_a_reporter_the_count_is_still_read(tmp_path: Path) -> None:
    settings = ApiFootballSettings(key="k" * 32, plan="pro", daily_budget=100, max_retries=0, timeout_seconds=1.0)
    c = ApiFootballClient(settings, PayloadStore(tmp_path),
                          transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=BODY, headers=HEADERS)),
                          quota=DailyQuota(budget=100))
    async with c:
        await c.get("/odds", {"fixture": 1})
    assert c.reported_quota == ReportedQuota(NOW, 75000, 51234, 450, 449)
