from __future__ import annotations

from datetime import date, datetime

from fbi.api.contracts.common import Contract, TeamRef, VenueRef
from fbi.api.contracts.matches import MatchSummary
from fbi.api.envelope import Section


class SeasonSummary(Contract):
    id: int
    season: int
    start_date: date | None
    end_date: date | None
    is_current: bool
    has_odds: bool
    fixtures: int
    finished: int
    with_results: int


class CompetitionSummary(Contract):
    id: int
    provider_league_id: int
    name: str
    country: str | None
    type: str
    competition_type: str
    tier: int | None
    is_tracked: bool
    seasons: int
    current_season: int | None
    fixtures: int
    teams: int
    logo_url: str | None = None
    flag_url: str | None = None
    country_code: str | None = None


class CompetitionDetail(Contract):
    competition: CompetitionSummary
    seasons: list[SeasonSummary]
    teams: list[TeamRef]


class TeamSummary(Contract):
    id: int
    provider_team_id: int
    name: str
    country: str | None
    fixtures: int
    results: int
    logo_url: str | None = None


class TeamRecord(Contract):
    """Counted from recorded results only - a fixture without a score is not a draw. The final score
    decides (extra time included); a match settled on penalties stays a draw, as in a league table.

    ``scope`` says what was added up: ``competition_season`` (one competition, one season - the
    provider's and the standings' scope) or ``all`` (every competition and season stored, from
    ``since``). Until 4 Oct 2026 the team page showed only ``all``, unlabelled, next to per-season
    tables (data truth audit V2, PRODUCT_SCOPE)."""

    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    scope: str = "competition_season"
    competition: str | None = None
    competition_type: str | None = None
    season: int | None = None
    since: datetime | None = None
    competitions: int | None = None


class TeamDetail(Contract):
    team: TeamSummary
    venue: VenueRef | None
    #: The domestic league's current season (a national team: its latest competition).
    record: Section[TeamRecord | None]
    #: Every competition of the team's current campaign, one row each.
    records: Section[list[TeamRecord]] | None = None
    #: Everything stored, labelled as such.
    lifetime: Section[TeamRecord | None] | None = None
    recent: list[MatchSummary]
    upcoming: list[MatchSummary]
