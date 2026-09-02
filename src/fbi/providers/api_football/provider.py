"""API-Football as one implementation of FootballDataProvider."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from fbi.core.clock import now
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.normalize import iter_fixtures, iter_odds
from fbi.providers.base import FixtureRef, OddsQuote, RawResponse

log = structlog.get_logger(__name__)

# /odds paginates at 10 fixtures per page for a league query, but a single
# fixture always fits on one page. We query per fixture, so pagination is a
# safety net rather than the normal path.
MAX_PAGES = 10


class ApiFootballProvider:
    name = "api_football"

    def __init__(self, client: ApiFootballClient, *, market_filter: set[str] | None = None) -> None:
        self._client = client
        self._market_filter = market_filter or set()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_fixtures(
        self,
        *,
        league_id: int,
        season: int,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[list[FixtureRef], RawResponse]:
        params: dict[str, Any] = {"league": league_id, "season": season}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        response = await self._client.get("/fixtures", params)
        return list(iter_fixtures(response.body)), _raw(response)

    async def fetch_prematch_odds(
        self, *, provider_fixture_id: int, kickoff_at: datetime
    ) -> tuple[list[OddsQuote], list[RawResponse]]:
        quotes: list[OddsQuote] = []
        raws: list[RawResponse] = []
        page = 1
        while page <= MAX_PAGES:
            response = await self._client.get(
                "/odds", {"fixture": provider_fixture_id, "page": page}
            )
            captured_at = response.fetched_at
            quotes.extend(
                iter_odds(
                    response.body,
                    kickoff_at=kickoff_at,
                    captured_at=captured_at,
                    payload_hash=response.stored.hash,
                    source="prematch",
                    market_filter=self._market_filter or None,
                )
            )
            raws.append(_raw(response))
            paging = response.body.get("paging") or {}
            total = paging.get("total") if isinstance(paging, dict) else 1
            if not isinstance(total, int) or page >= total:
                break
            page += 1
        return quotes, raws

    async def fetch_live_odds(
        self, *, provider_fixture_id: int, kickoff_at: datetime
    ) -> tuple[list[OddsQuote], RawResponse]:
        response = await self._client.get("/odds/live", {"fixture": provider_fixture_id})
        quotes = list(
            iter_odds(
                response.body,
                kickoff_at=kickoff_at,
                captured_at=response.fetched_at,
                payload_hash=response.stored.hash,
                source="live",
                market_filter=self._market_filter or None,
            )
        )
        return quotes, _raw(response)


def _raw(response: Any) -> RawResponse:
    return RawResponse(
        endpoint=response.endpoint,
        params=response.params,
        fetched_at=response.fetched_at or now(),
        http_status=response.http_status,
        results_count=response.results_count,
        payload_hash=response.stored.hash,
        file_path=response.stored.file_path,
        bytes_written=response.stored.bytes_written,
        body=response.body,
    )
