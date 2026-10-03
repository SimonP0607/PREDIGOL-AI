from __future__ import annotations

from datetime import date

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
    """Counted from recorded results only - a fixture without a score is not a draw."""

    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int


class TeamDetail(Contract):
    team: TeamSummary
    venue: VenueRef | None
    record: Section[TeamRecord | None]
    recent: list[MatchSummary]
    upcoming: list[MatchSummary]
