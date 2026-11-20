"""The tables of a competition season that the provider does not give - an annual or accumulated table, an average over several
seasons and the places they give - as a reader's page reads them (plan PM, PM-09-04; BE-082). Computed by
``fbi.competitions.season_tables`` (BE-075, PM-09-01) from the results and the competition's rules file; nothing here is estimated.

``GET /api/v1/competitions/{competition_id}/season-tables?season=`` answers 404 while ``FBI_COMPETITION_TABLES`` is off (the default,
until the owner signs the cotejo of the regulation, DOC-008, and the publication, DM-14). ``empty`` when the competition has no rules
file with season tables (today only the Primera A of Colombia has one).

What travels for the calculator «¿Qué pasa si…?» (PM-09-03): the points the rules give a win, a draw and a loss, each table's
tie-breakers in their order, the matches still to be decided that each table counts and, for an average, the points and matches
each club carries and the seasons its window counts. The calculator adds a chosen result to these figures; it never invents a score
and never estimates who wins (no probability travels here).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.intelligence.base import UtcDatetime

CONTRACT: Literal["season-tables"] = "season-tables"
CONTRACT_VERSION: Literal["1.0.0"] = "1.0.0"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class SeasonTeam(_Model):
    team_id: int | None = Field(description="PrediGol's team id (null when the club is not in core.teams).")
    provider_team_id: int = Field(ge=1)
    name: str = Field(min_length=1)
    logo_url: str | None = None


class SeasonRecord(_Model):
    season: int
    played: int = Field(ge=0)
    points: int = Field(ge=0)


class TieScope(_Model):
    """A club's figures on the results the tie-breakers of an average are read on (art. 33: Fase I of the current season)."""

    points: int
    goal_difference: int
    goals_for: int
    wins: int


class SeasonTableRow(_Model):
    position: int = Field(ge=1)
    team: SeasonTeam
    played: int = Field(ge=0)
    points: int
    wins: int | None = Field(default=None, description="An accumulated table only.")
    draws: int | None = None
    losses: int | None = None
    goals_for: int | None = None
    goals_against: int | None = None
    goal_difference: int | None = None
    average: str | None = Field(default=None, description="An average only: the exact quotient, «points/played».")
    average_3: str | None = Field(default=None, description="The average rounded half up to three decimals (a display).")
    average_3_cut: str | None = Field(default=None, description="The average cut to three decimals, as the published tables show it.")
    seasons: list[SeasonRecord] = Field(default_factory=list, description="An average only: the matches and points of each season "
                                                                          "it counts for the club.")
    window: list[int] = Field(default_factory=list, description="An average only: the seasons the club's average counts (a club "
                                                                "promoted lately counts fewer).")
    tie_scope: TieScope | None = None
    shared_with: list[int] = Field(default_factory=list, description="Provider team ids level with this one on every criterion the "
                                                                     "results can decide (a play-off or lots would settle it).")
    decided_by: str | None = Field(default=None, description="The criterion that separated this club from the next one.")
    open_on: str | None = Field(default=None, description="The criterion a tie is still open on (play-off, lots).")


ZoneState = Literal["definitivo", "provisional", "condicional", "empate_abierto"]
PlaceState = Literal["calculado", "provisional", "pendiente", "no_calculado"]


class SeasonZone(_Model):
    kind: str = Field(min_length=1, description="continental, relegation ...")
    target: str | None
    positions: list[int]
    teams: list[int] = Field(description="Provider team ids in the zone today.")
    state: ZoneState
    note: str | None = None


class SeasonPlace(_Model):
    competition: str = Field(min_length=1)
    article: str | None
    slot: str = Field(min_length=1)
    source: Literal["champion", "cup_winner", "table_rank"]
    of: str | None = Field(default=None, description="The tournament or cup whose winner takes the slot.")
    team: SeasonTeam | None
    position: int | None = Field(default=None, description="The club's position in the table, for a place by rank.")
    state: PlaceState
    reason: str | None = None


class SeasonTable(_Model):
    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["aggregate", "average"]
    complete: bool = Field(description="Every match of every phase the table counts is decided.")
    pending_matches: int = Field(ge=0)
    unverified_decisions: int = Field(ge=0, description="Results changed off the pitch counted and not yet verified by the owner.")
    tiebreakers: list[str] = Field(description="The criteria after points (after the average, for an average), in their order.")
    counts: list[str] = Field(description="The phases the table counts (``tournament.phase`` patterns of the rules file).")
    rows: list[SeasonTableRow]
    zones: list[SeasonZone]
    places: list[SeasonPlace]
    rounding: dict[str, Literal["igual", "cambia_una_zona"]] = Field(
        default_factory=dict, description="An average only: whether rounding to two or three decimals would change who is in a zone.")
    note: str | None = None


class RemainingMatch(_Model):
    """A match of the season still to be decided that at least one of the tables counts: what the calculator lets a reader set."""

    fixture_id: int | None = Field(description="PrediGol's fixture id (null when it is not in core.fixtures).")
    provider_fixture_id: int = Field(ge=1)
    round: str | None
    kickoff_at: UtcDatetime | None
    home: SeasonTeam
    away: SeasonTeam
    tables: list[str] = Field(min_length=1, description="The keys of the tables this match counts in.")


class PointsRule(_Model):
    win: int
    draw: int
    loss: int


class Champion(_Model):
    tournament: str = Field(min_length=1)
    team: SeasonTeam | None
    state: Literal["calculado", "pendiente"]


class SeasonTables(_Model):
    contract: Literal["season-tables"] = CONTRACT
    contract_version: Literal["1.0.0"] = CONTRACT_VERSION
    computed_by: str = Field(min_length=1, description="The version of the computation (season-tables-v1).")
    competition_id: int = Field(ge=1)
    league_id: int = Field(ge=1, description="The provider's league id.")
    season: int
    rules_version: int = Field(ge=1)
    rules_file: str = Field(min_length=1)
    rules_sha256: str = Field(min_length=64, max_length=64)
    points: PointsRule
    tables: list[SeasonTable]
    champions: list[Champion]
    remaining: list[RemainingMatch]
    unverified_decisions: int = Field(ge=0)
    computed_at: UtcDatetime
