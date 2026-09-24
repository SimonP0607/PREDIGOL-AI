"""API-Football as one implementation of FootballDataProvider."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import structlog

from fbi.core.clock import now
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.normalize import (
    iter_fixture_results,
    iter_fixtures,
    iter_league_seasons,
    iter_odds,
)
from fbi.providers.base import FixtureRef, FixtureResultRef, OddsQuote, RawResponse, SeasonRef

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

    # -- pure parsing: no I/O, so a stored payload can be re-normalised ------

    def parse_fixtures(self, body: dict[str, Any]) -> list[FixtureRef]:
        """Fixture identities from a /fixtures response already in hand.

        The network methods below call this on what they just fetched; the raw
        replay calls it on what was fetched days ago. One normaliser, so a
        replayed payload cannot be read differently from a live one.
        """
        return list(iter_fixtures(body))

    def parse_results(self, body: dict[str, Any]) -> list[FixtureResultRef]:
        """Scores of the finished fixtures in the same response. Zero extra
        requests: /fixtures always carried the goals."""
        return list(iter_fixture_results(body))

    async def fetch_league_seasons(
        self, *, league_id: int
    ) -> tuple[list[SeasonRef], RawResponse]:
        """One request. Tells us which season the provider calls current and
        whether it covers odds for it."""
        response = await self._client.get("/leagues", {"id": league_id})
        return list(iter_league_seasons(response.body)), _raw(response)

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

    async def fetch_fixtures_by_date(
        self, *, on: date
    ) -> tuple[list[FixtureRef], RawResponse]:
        """Every fixture the provider has for one calendar day, all leagues.

        One request covers every tracked competition at once, and it is the only
        fixtures query a restricted plan allows: `league` + `season` is refused
        with "Free plans do not have access to this season", while `date` alone
        is served. The caller filters to the competitions it tracks.
        """
        response = await self._client.get("/fixtures", {"date": on.isoformat()})
        return list(iter_fixtures(response.body)), _raw(response)

    async def fetch_results_by_date(
        self, *, on: date
    ) -> tuple[list[FixtureResultRef], RawResponse]:
        """Scores for one calendar day. Same endpoint, same cost, as
        ``fetch_fixtures_by_date`` - the goals were always in that payload."""
        response = await self._client.get("/fixtures", {"date": on.isoformat()})
        return list(iter_fixture_results(response.body)), _raw(response)

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
