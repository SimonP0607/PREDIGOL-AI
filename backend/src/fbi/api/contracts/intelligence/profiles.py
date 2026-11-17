"""C-09, the profiles of a club, a national team, a player and a competition (AD-H07 ``IA-090``; availability AD-H05 ``IA-091``;
call-ups AD-H06 ``IA-092``).

Routes (additive: ``GET /teams/{id}``, ``/players/{id}`` and ``/competitions/{id}`` keep their shape):

* public, 404 while ``FBI_PROFILES`` is off - ``GET /api/v1/teams/{team_id}/profile`` (a club or a national team: one resource,
  ``kind`` says which), ``GET /api/v1/players/{player_id}/profile``, ``GET /api/v1/competitions/{competition_id}/profile``;
* private (``require_admin``, no switch) - the same under ``/api/v1/admin/intelligence/…/profile``, adding the section
  «Intelligence»: the selections in shadow of the team's matches, the external ids and what the player engine would add.

What a reader NEVER gets here: a forecast of the player engine, an estimated starter or start probability, a player market,
the identity review queue, and anything medical - of an absence only its state, basis, source and date.

Every rate per 90 carries its sample (matches and minutes) and its interval; below ``min_minutes`` it is
``muestra_insuficiente``; with nothing reported, ``sin_datos``: never a 0 standing for «not recorded». A block whose piece is
not delivered is listed in ``not_yet`` with that piece; it becomes a field of its own (a minor version) when it arrives.
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    UtcDatetime,
    private,
)
from fbi.api.contracts.intelligence.vocab import Availability, EvaluationStep, LifecycleState

ProfileKind = Literal["club", "national_team", "player", "competition"]
TeamKind = Literal["club", "national_team"]
CoachBasis = Literal["ultima_alineacion", "carrera_proveedor"]
"""``ultima_alineacion``: the coach of the team's newest match sheet (AD-H03); ``carrera_proveedor``: the one open career the
provider lists, when no sheet names anyone."""
MatchResult = Literal["W", "D", "L"]
AvailabilityBasis = Literal["oficial", "proveedor", "dos_origenes", "un_medio"]
"""Precedence, first wins: an official source, the provider's injury report, two outlets, one outlet. A rumour never counts."""
PositionGroup = Literal["goalkeeper", "defender", "midfielder", "forward"]
Per90Metric = Literal["goals", "assists", "shots", "shots_on_target", "fouls_committed", "yellow_cards", "saves"]
CallUpLevel = Literal["oficial", "proveedor"]
CallUpBasis = Literal["comunicado_oficial", "convocados_ultimo_partido", "plantilla_proveedor"]
OfficialCallUpState = Literal["ninguna_fuente_oficial_autorizada", "sin_comunicado_ingerido"]
HonourBasis = Literal["tabla_final_guardada"]
PendingBlock = Literal["stakes", "news", "honours_external", "start_probability", "engine_forecasts", "player_markets"]
"""Blocks the maquetas draw whose piece is not delivered: AD-B02, AD-G07, AD-H01 (public); AD-D04, AD-B08, AD-E01 (private)."""

PUBLIC_PENDING: Final[dict[str, str]] = {"stakes": "AD-B02", "news": "AD-G07", "honours_external": "AD-H01"}
PRIVATE_PENDING: Final[dict[str, str]] = {"start_probability": "AD-D04", "engine_forecasts": "AD-B08",
                                          "player_markets": "AD-E01"}


def _absent(value: object) -> bool:
    return value is None


class Pending(IntelligenceModel):
    """A block not computed yet, and the piece that will compute it."""

    block: PendingBlock
    missing: Missing


class EntityRef(IntelligenceModel):
    id: int
    name: str = Field(min_length=1)


class Crest(IntelligenceModel):
    """Decision n.º 9: a crest only to identify, beside the name; ``allowed`` false -> a monogram."""

    allowed: bool
    url: str | Missing
    use: Literal["junto_al_nombre"] = "junto_al_nombre"


class Photo(IntelligenceModel):
    """No photo of the provider (licence risk): always a monogram."""

    kind: Literal["monograma"] = "monograma"


class Venue(IntelligenceModel):
    id: int
    name: str = Field(min_length=1)
    city: str | Missing
    capacity: int | Missing
    altitude_m: float | Missing = Field(description="From the Wikidata coordinates and a DEM (AD-H04), or why not.")


class Coach(IntelligenceModel):
    name: str = Field(min_length=1)
    coach_id: int | Missing
    basis: CoachBasis
    as_of: UtcDatetime = Field(description="The day of the match the answer comes from (or the career's start), 00:00 UTC.")
    as_of_day_only: bool = True
    fixture_id: int | Missing


class TeamHeader(IntelligenceModel):
    id: int
    name: str = Field(min_length=1)
    short_name: str | Missing
    country: str | Missing
    kind: TeamKind
    senior: bool = Field(description="False for a youth or Olympic side (U-20, U-23...): a separate entity.")
    founded: int | Missing
    crest: Crest
    venue: Venue | Missing
    coach: Coach | Missing


class ProfileMatchRef(IntelligenceModel):
    fixture_id: int
    kickoff_at: UtcDatetime
    competition: EntityRef
    opponent: EntityRef
    home: bool


class FormItem(ProfileMatchRef):
    goals_for: int
    goals_against: int
    score: str = Field(description="The team's goals first: «2-0».")
    result: MatchResult


class Figure(IntelligenceModel):
    """A mean per match over the matches whose statistics report it - and how many those are."""

    per_match: float | Missing
    matches_with_data: int = Field(ge=0)


class SideRecord(IntelligenceModel):
    matches: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int


class SeasonStats(IntelligenceModel):
    """The team in one competition and season (its domestic league's current one; a national team: its latest)."""

    competition: EntityRef
    season: int
    record: SideRecord
    home: SideRecord
    away: SideRecord
    xg_for: Figure
    xg_against: Figure
    shots_for: Figure
    shots_on_target_for: Figure
    corners_for: Figure
    yellow_cards_for: Figure


class AvailabilityEntry(IntelligenceModel):
    """Only the state, its basis, the source's name and when PrediGol learned it: never a diagnosis or a date of return."""

    player_id: int | Missing
    name: str = Field(min_length=1)
    status: Availability
    basis: AvailabilityBasis
    source: str = Field(min_length=1)
    known_at: UtcDatetime
    fixture_id: int | Missing


class TeamAvailability(IntelligenceModel):
    fixture_id: int = Field(description="The match the report is about: the team's next one.")
    report_checked_at: UtcDatetime | Missing = Field(description="When the provider's report of the season was last asked for.")
    unavailable: ItemList[AvailabilityEntry] = Field(description="Who may miss it (duda, baja, sancionado), or sin_resultados.")


class SquadMember(IntelligenceModel):
    player_id: int | Missing
    name: str = Field(min_length=1)
    position: PositionGroup | Missing
    shirt_number: int | Missing
    age: int | Missing


class Squad(IntelligenceModel):
    source: Literal["plantilla_proveedor"] = "plantilla_proveedor"
    seen_at: UtcDatetime
    players: ItemList[SquadMember]


class CompetitionRecord(IntelligenceModel):
    competition: EntityRef
    season: int | Missing
    record: SideRecord
    rank: int | Missing
    points: int | Missing


class Honour(IntelligenceModel):
    competition: EntityRef
    season: int
    basis: HonourBasis


class Honours(IntelligenceModel):
    """Titles PrediGol can compute from what it stores (league seasons ended with the team first in the final table), apart from
    any external list (AD-H01, «según Wikidata»)."""

    computed: ItemList[Honour]
    since_season: int | Missing = Field(description="The first season stored: nothing before it is counted.")


class LeaderRow(IntelligenceModel):
    player_id: int | Missing
    name: str = Field(min_length=1)
    value: int


class CallUpPlayer(IntelligenceModel):
    player_id: int | Missing
    name: str = Field(min_length=1)
    club: EntityRef | Missing
    position: PositionGroup | Missing


class CallUp(IntelligenceModel):
    """The latest list of the national team. ``level`` is ``oficial`` only from a federation's communiqué read from a source the
    registry authorises; otherwise ``proveedor``, and ``official_state`` says why there is no official one."""

    level: CallUpLevel
    basis: CallUpBasis
    source: str = Field(min_length=1)
    published_at: UtcDatetime | Missing
    known_at: UtcDatetime
    fixture_id: int | Missing
    official_state: OfficialCallUpState | None = Field(default=None, exclude_if=_absent,
                                                       description="Why the list is not official (only when it is not).")
    permitted_official_sources: int = Field(ge=0, description="Official sources the registry lets PrediGol read for call-ups.")
    players: ItemList[CallUpPlayer]


class NationalTeamBlocks(IntelligenceModel):
    call_up: CallUp | Missing
    caps_leaders: ItemList[LeaderRow] = Field(description="Most matches in the senior side's matchday squads (appeared).")
    scorers: ItemList[LeaderRow] = Field(description="Most goals for the side in the stored statistics, in window_days.")
    window_days: int


class ShadowSelection(IntelligenceModel):
    """A selection of the cycle in shadow for one of the team's matches (private)."""

    fixture_id: int
    market_key: str
    selection: str
    line: float | Missing
    state: LifecycleState
    evaluation: EvaluationStep | Missing
    known_at: UtcDatetime


class ExternalId(IntelligenceModel):
    """An external id of the entity (AD-H01, private): its system, method and confidence."""

    system: str
    external_id: str
    method: str
    confidence: float | Missing
    state: str


class Identity(IntelligenceModel):
    ids: ItemList[ExternalId]
    open_reviews: int | Missing


class TeamProfile(IntelligenceModel):
    header: TeamHeader
    next_match: ProfileMatchRef | Missing
    form: ItemList[FormItem] = Field(description="The last five finished matches with a score, newest first.")
    season_stats: SeasonStats | Missing
    availability: TeamAvailability | Missing
    squad: Squad | Missing
    upcoming: ItemList[ProfileMatchRef]
    competitions: ItemList[CompetitionRecord] = Field(description="The current campaign, one row per competition.")
    honours: Honours
    national: NationalTeamBlocks | None = Field(default=None, exclude_if=_absent,
                                                description="Only for a national team.")

    @model_validator(mode="after")
    def _national_only(self) -> TeamProfile:
        if (self.national is not None) != (self.header.kind == "national_team"):
            raise ValueError("national is given exactly for a national team")
        return self


class TeamProfilePrivate(TeamProfile):
    intelligence: ItemList[ShadowSelection] = private(description="The selections in shadow of the team's matches (14 days "
                                                                  "back, 7 ahead), with their state in the cycle.")
    identity: Identity | Missing = private(description="External ids and open reviews (AD-H01).")


class PlayerHeader(IntelligenceModel):
    id: int
    name: str = Field(min_length=1)
    age: int | Missing
    nationality: str | Missing
    position: PositionGroup | Missing
    club: EntityRef | Missing
    national_team: EntityRef | Missing
    shirt_number: int | Missing
    photo: Photo


class PlayerAvailability(IntelligenceModel):
    status: Availability
    basis: AvailabilityBasis
    source: str = Field(min_length=1)
    known_at: UtcDatetime
    fixture_id: int


class PlayerMatchLine(IntelligenceModel):
    fixture_id: int
    kickoff_at: UtcDatetime
    competition: EntityRef
    team: EntityRef
    opponent: EntityRef
    minutes: int
    started: bool
    goals: int | Missing
    assists: int | Missing
    shots: int | Missing
    shots_on_target: int | Missing
    yellow_cards: int | Missing
    red_cards: int | Missing


class PlayerSeasonLine(IntelligenceModel):
    competition: EntityRef
    season: int
    team: EntityRef
    matches: int
    starts: int
    minutes: int
    goals: int | Missing
    assists: int | Missing


class Interval(IntelligenceModel):
    low: float = Field(ge=0)
    high: float = Field(ge=0)
    method: Literal["poisson_score_95"] = "poisson_score_95"


class Per90Rate(IntelligenceModel):
    metric: Per90Metric
    value: float | Missing
    interval: Interval | Missing
    count: int = Field(ge=0)
    matches: int = Field(ge=0, description="Appearances whose sheet reports the metric.")
    minutes_sample: int = Field(ge=0, description="Their minutes.")
    sample_ok: bool


class Per90(IntelligenceModel):
    min_minutes: int
    window_days: int
    items: list[Per90Rate]


class CareerSpell(IntelligenceModel):
    team: EntityRef | Missing
    team_name: str = Field(min_length=1)
    valid_from: UtcDatetime
    valid_to: UtcDatetime | Missing
    day_only: bool = True
    matches: int | Missing


class Caps(IntelligenceModel):
    team: EntityRef
    matches: int = Field(description="Matchday squads of the senior side in finished matches.")
    appeared: int
    starts: int
    minutes: int
    last_at: UtcDatetime


class ProviderTrophy(IntelligenceModel):
    league: str = Field(min_length=1)
    country: str | Missing
    season: str | Missing
    place: str | Missing


class PlayerProfile(IntelligenceModel):
    header: PlayerHeader
    availability: PlayerAvailability | Missing
    next_match: ProfileMatchRef | Missing
    form_last10: ItemList[PlayerMatchLine]
    season: ItemList[PlayerSeasonLine] = Field(description="Per competition, season and team, in window_days.")
    per90: Per90
    career: ItemList[CareerSpell]
    caps: Caps | Missing
    trophies: ItemList[ProviderTrophy] = Field(description="The provider's list (API-Football /trophies), as it says it.")


class PlayerProfilePrivate(PlayerProfile):
    identity: Identity | Missing = private(description="External ids and open reviews (AD-H01).")


class CompetitionHeader(IntelligenceModel):
    id: int
    name: str = Field(min_length=1)
    country: str | Missing
    type: str | Missing
    gender: str | Missing
    age_group: str | Missing
    tracked: bool
    logo: Crest
    rules_coded: bool = Field(description="Whether its regulation is coded (config/rules), which the scenarios need.")


class SeasonRef(IntelligenceModel):
    season: int
    start: UtcDatetime | Missing
    end: UtcDatetime | Missing
    current: bool


class ProfileTableRow(IntelligenceModel):
    rank: int
    team: EntityRef
    group: str | Missing
    played: int
    points: int
    goals_for: int
    goals_against: int


class Coverage(IntelligenceModel):
    finished_matches: int
    with_player_stats: int
    with_team_stats: int


class Fixture(IntelligenceModel):
    fixture_id: int
    kickoff_at: UtcDatetime
    home: EntityRef
    away: EntityRef


class CompetitionProfile(IntelligenceModel):
    header: CompetitionHeader
    season: SeasonRef | Missing
    standings: ItemList[ProfileTableRow]
    standings_at: UtcDatetime | Missing
    upcoming: ItemList[Fixture]
    scorers: ItemList[LeaderRow]
    coverage: Coverage | Missing


class CompetitionProfilePrivate(CompetitionProfile):
    identity: Identity | Missing = private(description="External ids and open reviews (AD-H01).")


class Profile(IntelligenceContract):
    """C-09, public projection: one of ``team``, ``player`` or ``competition``, as ``kind`` says."""

    CONTRACT_ID: ClassVar[str] = "C-09"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    kind: ProfileKind
    team: TeamProfile | None = Field(default=None, exclude_if=_absent)
    player: PlayerProfile | None = Field(default=None, exclude_if=_absent)
    competition: CompetitionProfile | None = Field(default=None, exclude_if=_absent)
    not_yet: list[Pending] = Field(description="Blocks the maquetas draw that are not computed yet, each with its piece.")

    @model_validator(mode="after")
    def _one_body(self) -> Profile:
        given = {"team": self.team is not None, "player": self.player is not None,
                 "competition": self.competition is not None}
        want = "team" if self.kind in ("club", "national_team") else self.kind
        if [k for k, v in given.items() if v] != [want]:
            raise ValueError(f"a {self.kind} profile carries {want} and nothing else")
        if self.team is not None and self.team.header.kind != self.kind:
            raise ValueError("kind and team.header.kind disagree")
        return self


class ProfilePrivate(Profile):
    """C-09, private projection (``require_admin``): the section «Intelligence» of each profile."""

    team: TeamProfilePrivate | None = Field(default=None, exclude_if=_absent)
    player: PlayerProfilePrivate | None = Field(default=None, exclude_if=_absent)
    competition: CompetitionProfilePrivate | None = Field(default=None, exclude_if=_absent)
    not_yet_private: list[Pending] = private(description="What the private section will add, each with its piece.")
