"""The provider abstraction.

Everything above this line is provider agnostic. API-Football is ONE
implementation, and the rest of the platform must never import it directly, so
swapping or adding a data source is a matter of writing another class here -
not of touching the pick engine.

The DTOs are intentionally poor in behaviour and rich in provenance: every one
carries the payload hash it came from, so any row in the database can be traced
back to the exact bytes the provider returned.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

OddsSource = Literal["prematch", "live"]


@dataclass(frozen=True, slots=True)
class RawResponse:
    """One provider response, already persisted to the raw store."""

    endpoint: str
    params: dict[str, str]
    fetched_at: datetime
    http_status: int
    results_count: int
    payload_hash: str
    file_path: str
    bytes_written: int
    body: dict[str, object]


@dataclass(frozen=True, slots=True)
class SeasonRef:
    """One season of one competition, as the provider currently sees it.

    ``is_current`` is the provider's answer, not ours. Our catalogue came from a
    backup and drifts by a whole season every August; this is how it gets
    corrected instead of silently querying a season that ended months ago.

    ``has_odds`` comes from the provider's own coverage flags: a season the
    provider does not cover for odds cannot be a capture pilot, however many
    fixtures it has.
    """

    provider_league_id: int
    season: int
    is_current: bool
    start_date: str | None
    end_date: str | None
    has_odds: bool
    has_fixtures: bool


@dataclass(frozen=True, slots=True)
class FixtureRef:
    provider_fixture_id: int
    provider_league_id: int
    season: int
    kickoff_at: datetime
    provider_home_team_id: int
    provider_away_team_id: int
    status_short: str


@dataclass(frozen=True, slots=True)
class OddsQuote:
    """A single price, at a single instant, from a single bookmaker.

    ``captured_at`` is part of the identity of this record, not metadata about
    it. The legacy schema treated it as metadata and therefore overwrote every
    price with the next one.
    """

    provider_fixture_id: int
    provider_bookmaker_id: int
    bookmaker_name: str
    market_key: str
    selection: str
    line: Decimal
    odds_decimal: Decimal
    captured_at: datetime
    minutes_to_ko: int
    source: OddsSource
    payload_hash: str


@runtime_checkable
class FootballDataProvider(Protocol):
    """What the platform needs from any football data source."""

    name: str

    async def fetch_league_seasons(
        self, *, league_id: int
    ) -> tuple[list[SeasonRef], RawResponse]: ...

    async def fetch_fixtures(
        self, *, league_id: int, season: int, date_from: str | None = None, date_to: str | None = None
    ) -> tuple[list[FixtureRef], RawResponse]: ...

    async def fetch_fixtures_by_date(
        self, *, on: date
    ) -> tuple[list[FixtureRef], RawResponse]: ...

    async def fetch_prematch_odds(
        self, *, provider_fixture_id: int, kickoff_at: datetime
    ) -> tuple[list[OddsQuote], list[RawResponse]]: ...

    async def fetch_live_odds(
        self, *, provider_fixture_id: int, kickoff_at: datetime
    ) -> tuple[list[OddsQuote], RawResponse]: ...

    async def aclose(self) -> None: ...
