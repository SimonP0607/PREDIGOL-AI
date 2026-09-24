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
    """A fixture as the provider describes it at one instant.

    ``round`` and the venue fields are optional because the provider omits
    them for some competitions; an absent value is stored as NULL, never
    guessed.
    """

    provider_fixture_id: int
    provider_league_id: int
    season: int
    kickoff_at: datetime
    provider_home_team_id: int
    provider_away_team_id: int
    status_short: str
    round: str | None = None
    provider_venue_id: int | None = None
    venue_name: str | None = None
    venue_city: str | None = None


@dataclass(frozen=True, slots=True)
class FixtureResultRef:
    """The score of a fixture that has actually been played.

    Separate from ``FixtureRef`` on purpose: a fixture exists from the moment
    it is scheduled, a result exists only once it has been played, and
    conflating the two is how a cancelled match ends up with a 0-0 "result".
    Only fixtures the provider reports as finished produce one of these.

    ``goals_home``/``goals_away`` are the 90-minute score the provider settles
    markets on. Extra time and penalties are carried separately because a
    1X2 market settles on the former and a cup winner on the latter; merging
    them silently would mis-settle every knockout tie.
    """

    provider_fixture_id: int
    status_short: str
    goals_home: int
    goals_away: int
    ht_goals_home: int | None = None
    ht_goals_away: int | None = None
    et_goals_home: int | None = None
    et_goals_away: int | None = None
    pen_home: int | None = None
    pen_away: int | None = None


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

    def parse_fixtures(self, body: dict[str, object]) -> list[FixtureRef]: ...

    def parse_results(self, body: dict[str, object]) -> list[FixtureResultRef]: ...

    async def fetch_league_seasons(
        self, *, league_id: int
    ) -> tuple[list[SeasonRef], RawResponse]: ...

    async def fetch_fixtures(
        self, *, league_id: int, season: int, date_from: str | None = None, date_to: str | None = None
    ) -> tuple[list[FixtureRef], RawResponse]: ...

    async def fetch_fixtures_by_date(
        self, *, on: date
    ) -> tuple[list[FixtureRef], RawResponse]: ...

    async def fetch_results_by_date(
        self, *, on: date
    ) -> tuple[list[FixtureResultRef], RawResponse]: ...

    async def fetch_prematch_odds(
        self, *, provider_fixture_id: int, kickoff_at: datetime
    ) -> tuple[list[OddsQuote], list[RawResponse]]: ...

    async def fetch_live_odds(
        self, *, provider_fixture_id: int, kickoff_at: datetime
    ) -> tuple[list[OddsQuote], RawResponse]: ...

    async def aclose(self) -> None: ...
