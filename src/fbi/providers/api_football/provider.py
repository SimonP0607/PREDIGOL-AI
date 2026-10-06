"""API-Football as one implementation of FootballDataProvider."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import structlog

from fbi.core.clock import now
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.details import (
    AbsenceRef,
    CoverageRef,
    FixtureDetail,
    StandingRef,
    iter_coverage,
    iter_fixture_details,
    iter_injuries,
    iter_standings,
)
from fbi.providers.api_football.live import (
    LiveFixtureState,
    LiveMarketSeen,
    LiveOddsQuote,
    iter_live_odds,
)
from fbi.providers.api_football.normalize import (
    iter_fixture_results,
    iter_fixtures,
    iter_league_seasons,
    iter_odds,
)
from fbi.providers.base import (
    FixtureRef,
    FixtureResultRef,
    OddsParseLog,
    OddsQuote,
    RawResponse,
    SeasonRef,
)

log = structlog.get_logger(__name__)

# /odds paginates at 10 fixtures per page for a league query, but a single
# fixture always fits on one page. We query per fixture, so pagination is a
# safety net rather than the normal path.
MAX_PAGES = 10
MAX_IDS = 20
"""/fixtures?ids= and /injuries?ids= accept at most 20 ids (documented)."""


@dataclass(frozen=True, slots=True)
class FinalPrematch:
    """What /odds said about a played match: its last pre-match prices, or why there are none."""

    update_at: datetime | None
    quotes: list[OddsQuote]
    raws: list[RawResponse]
    refused_after_kickoff: bool
    """The provider's stamp was at or after kick-off: possibly in-play prices, so none kept."""


def _update_stamp(entry: dict[str, Any]) -> datetime | None:
    value = entry.get("update")
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo is not None else None


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
        self, *, provider_fixture_id: int, kickoff_at: datetime,
        parse_log: OddsParseLog | None = None,
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
                    parse_log=parse_log,
                )
            )
            raws.append(_raw(response))
            paging = response.body.get("paging") or {}
            total = paging.get("total") if isinstance(paging, dict) else 1
            if not isinstance(total, int) or page >= total:
                break
            page += 1
        return quotes, raws

    async def fetch_final_prematch_odds(
        self, *, provider_fixture_id: int, kickoff_at: datetime, parse_log: OddsParseLog | None = None,
    ) -> FinalPrematch:
        """The provider's LAST pre-match prices for a match already played.

        /odds keeps pre-match prices for 7 days. Each response item carries the provider's
        own ``update`` stamp; the quotes are stamped with it rather than with our fetch time,
        so ``minutes_to_ko`` is how long before kick-off the provider last moved them. A stamp
        at or after kick-off could be an in-play price: nothing is returned for it.
        """
        response = await self._client.get("/odds", {"fixture": provider_fixture_id})
        raw = _raw(response)
        entries = [e for e in response.body.get("response") or [] if isinstance(e, dict)]
        stamps = [s for s in (_update_stamp(e) for e in entries) if s is not None]
        if not entries:
            return FinalPrematch(None, [], [raw], refused_after_kickoff=False)
        update_at = max(stamps) if stamps else None
        if update_at is None or update_at >= kickoff_at:
            return FinalPrematch(update_at, [], [raw], refused_after_kickoff=update_at is not None)
        quotes = list(iter_odds(response.body, kickoff_at=kickoff_at, captured_at=update_at,
                                payload_hash=response.stored.hash, source="prematch",
                                market_filter=self._market_filter or None, parse_log=parse_log))
        return FinalPrematch(update_at, quotes, [raw], refused_after_kickoff=False)

    async def fetch_live_odds_all(
        self, *, parse_log: OddsParseLog | None = None, persist_raw: bool = False
    ) -> tuple[list[LiveFixtureState], list[LiveOddsQuote], list[LiveMarketSeen], RawResponse]:
        """Every fixture the provider is pricing in play, in ONE request.

        Measured: an unfiltered /odds/live returns all of them - 8 fixtures
        across 7 competitions on the probe call - so asking per fixture would
        multiply the cost by the number of live matches for no extra data.

        Returns live DTOs, never OddsQuote. A live price cannot reach
        market.odds_snapshots through this method, which is the point: the two
        series are different observations and the pre-match backtest must never
        be able to read an in-play number.

        The body is NOT written to the RAW store unless ``persist_raw``: only the present of the in-play book is
        kept (revision 0068), so its payloads are evidence of nothing stored. The returned RawResponse carries the
        body, so the caller can still keep it (``PayloadStore.store``) when it holds evidence of an anomaly.
        """
        response = await self._client.get("/odds/live", {}, persist=persist_raw)
        states, quotes, markets = iter_live_odds(
            response.body,
            captured_at=response.fetched_at,
            payload_hash=response.stored.hash,
            parse_log=parse_log,
        )
        return states, quotes, markets, _raw(response)


    # -- historical migration ------------------------------------------------

    async def fetch_coverage(self, *, league_id: int | None = None) -> tuple[list[CoverageRef], RawResponse]:
        """/leagues: every league (or one) with every season and its coverage flags. One request."""
        response = await self._client.get("/leagues", {"id": league_id} if league_id is not None else {})
        return list(iter_coverage(response.body)), _raw(response)

    async def fetch_fixture_details(self, *, provider_fixture_ids: list[int]) -> tuple[list[FixtureDetail], RawResponse]:
        """Events, lineups, statistics and player statistics for up to 20 fixtures, one request."""
        ids = sorted(set(provider_fixture_ids))
        if not 1 <= len(ids) <= MAX_IDS:
            raise ValueError(f"/fixtures?ids= takes 1 to {MAX_IDS} ids, got {len(ids)}")
        response = await self._client.get("/fixtures", {"ids": "-".join(str(i) for i in ids)})
        return list(iter_fixture_details(response.body)), _raw(response)

    async def fetch_standings(self, *, league_id: int, season: int) -> tuple[list[StandingRef], RawResponse]:
        response = await self._client.get("/standings", {"league": league_id, "season": season})
        return list(iter_standings(response.body)), _raw(response)

    async def fetch_injuries(self, *, league_id: int, season: int) -> tuple[list[AbsenceRef], RawResponse]:
        response = await self._client.get("/injuries", {"league": league_id, "season": season})
        return list(iter_injuries(response.body)), _raw(response)

    async def fetch_teams(self, *, league_id: int, season: int) -> RawResponse:
        """Stored raw: team and venue identity per season (normalised later if a page needs it)."""
        return _raw(await self._client.get("/teams", {"league": league_id, "season": season}))

    async def fetch_player_profiles_page(self, *, page: int) -> RawResponse:
        """One page (250 players) of /players/profiles, every player the provider knows, by id."""
        return _raw(await self._client.get("/players/profiles", {"page": page}))

    async def fetch_squad(self, *, team_id: int) -> RawResponse:
        """A team's current squad (/players/squads): shirt number, position, age."""
        return _raw(await self._client.get("/players/squads", {"team": team_id}))

    async def fetch_players_page(self, *, league_id: int, season: int, page: int) -> RawResponse:
        """One page (20 players) of season player statistics. Stored raw."""
        return _raw(await self._client.get("/players", {"league": league_id, "season": season, "page": page}))

    async def fetch_raw(self, endpoint: str, params: dict[str, Any]) -> RawResponse:
        """Any documented GET, stored raw; the caller's normalizer reads ``body``. Used by the reference
        feeds (fbi.ingestion.reference), whose endpoints carry no odds and no live state."""
        return _raw(await self._client.get(endpoint, params))


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
        persisted=getattr(response.stored, "persisted", True),
    )
