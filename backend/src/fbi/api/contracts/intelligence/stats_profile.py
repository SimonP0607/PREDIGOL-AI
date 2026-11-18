"""C-13, the statistical profile of a team or a player (plan EA, piece EA-001): what they DID, measured and precomputed.

One answer carries one or two entities (``entities``): a profile has one; a comparison and a match's preview have two, each measured
against ITS OWN competition season. Every figure travels with its sample (``matches_with_data``), its percentile among the teams of the
same competition season (a player: among the players of his position with at least ``min_nineties``) and the league's reference. A figure
a competition does not record well enough (under the coverage threshold, EA-008) is ``sin_cobertura``; under the sample, it is
``muestra_insuficiente``: never a 0 standing for «not recorded».

Routes (all 404 while ``FBI_STATS_V2`` is off; the private ones answer the owner either way):

* public - ``GET /api/v1/teams/{team_id}/stats``, ``GET /api/v1/players/{player_id}/stats``, ``GET /api/v1/stats/compare/teams``,
  ``GET /api/v1/stats/compare/players``, ``GET /api/v1/matches/{fixture_id}/stats-preview``;
* private - ``GET /api/v1/admin/intelligence/teams/{team_id}/stats`` and ``.../players/{player_id}/stats``, adding the audit of the
  calculation (its run, its version, the coverage of every metric).

Nothing here is a forecast: the pulse, the intervals, the survival and the trends are history, and they say so. Formulas: ``fbi.stats``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    CODE_PATTERN,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    UtcDatetime,
    private,
)

StatsSubject = Literal["equipo", "jugador"]
StatsScope = Literal["u5", "u10", "u20", "season"]
StatsContext = Literal["all", "home", "away"]
Better = Literal["mas", "menos", "neutral"]
"""Which way is better for the team or the player: more, less, or neither (fouls, possession)."""
StatUnit = Literal["por_partido", "por_90", "porcentaje"]
PulseSubject = Literal["goles_a_favor", "goles_en_contra", "tarjetas"]
TrendFamily = Literal["resultado", "goles", "goles_1t", "corners", "tarjetas"]
TrendContext = Literal["all", "home", "away", "favorite"]
"""``favorite``: the matches in which the team was the favourite of the closing consensus (1X2, without margin)."""
RadarKey = Literal["ataque", "pegada", "volumen", "presencia", "defensa", "disciplina"]
PositionGroup = Literal["portero", "defensa", "medio", "delantero"]
EntityRole = Literal["perfil", "local", "visitante", "a", "b"]


class Ref(IntelligenceModel):
    id: int
    name: str = Field(min_length=1)


class CompetitionSeasonRef(IntelligenceModel):
    competition_season_id: int
    competition: Ref
    season: int
    country: str | Missing


class Quantiles(IntelligenceModel):
    """The distribution of a metric among the players of a position (or the teams of a league): to draw a point on it."""

    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    entities: int = Field(ge=1, description="How many players (teams) the quantiles rest on.")

    @model_validator(mode="after")
    def _ordered(self) -> Quantiles:
        if not self.p10 <= self.p25 <= self.p50 <= self.p75 <= self.p90:
            raise ValueError("quantiles must not decrease")
        return self


class StatFigure(IntelligenceModel):
    """One measured figure: a mean per match (a team), a rate per 90 (a player) or a proportion, with its sample and its percentile."""

    key: str = Field(pattern=CODE_PATTERN, description="goals_for, xg_against, shots_on_target_per90 ... (the web names it).")
    unit: StatUnit
    better: Better
    value: float | Missing
    matches_with_data: int = Field(ge=0)
    percentile: int | Missing = Field(description="0-100: the share of the league's teams (the position's players) below it.")
    league_value: float | Missing = Field(description="The league's mean per team (the position's median per player).")
    distribution: Quantiles | Missing


class Record(IntelligenceModel):
    matches: int = Field(ge=0)
    wins: int = Field(ge=0)
    draws: int = Field(ge=0)
    losses: int = Field(ge=0)
    goals_for: int = Field(ge=0)
    goals_against: int = Field(ge=0)
    points: int = Field(ge=0)

    @model_validator(mode="after")
    def _adds_up(self) -> Record:
        if self.wins + self.draws + self.losses != self.matches:
            raise ValueError("wins, draws and losses add up to the matches")
        if self.points != 3 * self.wins + self.draws:
            raise ValueError("points are three a win and one a draw")
        return self


class MatchPoint(IntelligenceModel):
    """One match of the series, oldest first: score, xG and the moving mean of the last five (Understat's line)."""

    fixture_id: int
    kickoff_at: UtcDatetime
    opponent: Ref
    home: bool
    goals_for: int = Field(ge=0)
    goals_against: int = Field(ge=0)
    xg_for: float | Missing
    xg_against: float | Missing
    xg_for_avg5: float | Missing
    xg_against_avg5: float | Missing


class HalfSplit(IntelligenceModel):
    goals_for_1h: float
    goals_against_1h: float
    goals_for_2h: float
    goals_against_2h: float
    matches_with_data: int = Field(ge=1)


class GameStates(IntelligenceModel):
    """``estados-v1``: the score minute by minute rebuilt from the goals, over the matches whose goals add up to the result."""

    minutes_leading: float = Field(ge=0, le=90)
    minutes_level: float = Field(ge=0, le=90)
    minutes_trailing: float = Field(ge=0, le=90)
    matches_led: int = Field(ge=0)
    points_ceded: int = Field(ge=0, description="Points let slip in the matches it led at some point.")
    matches_trailed: int = Field(ge=0)
    points_rescued: int = Field(ge=0, description="Points won in the matches it trailed at some point.")
    matches_with_data: int = Field(ge=1)


class PulseBin(IntelligenceModel):
    label: str = Field(min_length=1, description="«0-5», «40-45», «45+», «85-90», «90+».")
    start: int = Field(ge=0, le=90)
    rate: float = Field(ge=0, description="Smoothed events per match in the bin (the team).")
    league_rate: float = Field(ge=0)
    index: float | Missing = Field(description="100 x rate / league_rate: 100 is the league.")
    low: float | Missing = Field(description="The 10th percentile of the index over the bootstrap.")
    high: float | Missing = Field(description="The 90th percentile of the index over the bootstrap.")


class Pulse(IntelligenceModel):
    """``pulso-v1``: a Gaussian kernel (sigma minutes) over 5' bins, 45+ and 90+ their own masses, against the league = 100, with a
    bootstrap band over matches. History of goals (or cards): not the live momentum."""

    subject: PulseSubject
    sigma_minutes: float = Field(gt=0)
    bootstrap: int = Field(ge=0)
    matches: int = Field(ge=1)
    bins: list[PulseBin] = Field(min_length=1)


class GoalRef(IntelligenceModel):
    fixture_id: int
    minute: int = Field(ge=0)
    extra_minute: int | None = Field(default=None, ge=0)


class IntervalBin(IntelligenceModel):
    label: str = Field(min_length=1, description="«1-15» ... «76-90», «45+», «90+».")
    goals_for: int = Field(ge=0)
    goals_against: int = Field(ge=0)
    league_for: float = Field(ge=0, description="Goals a league team scores in the bin, per match.")
    league_against: float = Field(ge=0)
    goals_for_list: list[GoalRef]
    goals_against_list: list[GoalRef]


class GoalIntervals(IntelligenceModel):
    matches: int = Field(ge=1)
    bins: list[IntervalBin] = Field(min_length=1)


class SurvivalPoint(IntelligenceModel):
    label: str = Field(min_length=1)
    minute: int = Field(ge=0, le=90)
    survival: float = Field(ge=0, le=1, description="Kaplan-Meier: the share of matches still 0-0 after this minute.")


class Survival(IntelligenceModel):
    matches: int = Field(ge=1)
    points: list[SurvivalPoint] = Field(min_length=1)
    median_first_goal: str | Missing = Field(description="The label of the first bin where the survival falls to a half.")
    level_at_half: float | Missing = Field(description="The share of matches 0-0 at half-time.")
    league_points: list[SurvivalPoint]


class TrendRow(IntelligenceModel):
    """A frequency with its Wilson interval (z = 1.96) and the league's: the colour is the deviation, never a recommendation."""

    key: str = Field(pattern=CODE_PATTERN)
    family: TrendFamily
    rule_key: str | Missing = Field(description="The IA-070 settlement rule it is counted with (goals_ft@v1 ...); a frequency of "
                                                "the goal events (scored first) has none.")
    line: float | None
    hits: int = Field(ge=0)
    n: int = Field(ge=1)
    pct: int = Field(ge=0, le=100)
    wilson_low: int = Field(ge=0, le=100)
    wilson_high: int = Field(ge=0, le=100)
    league_pct: int | Missing
    deviation_pts: int | Missing
    fixture_ids: list[int]

    @model_validator(mode="after")
    def _consistent(self) -> TrendRow:
        if self.hits > self.n:
            raise ValueError("hits cannot exceed n")
        if not self.wilson_low <= self.pct <= self.wilson_high:
            raise ValueError("pct lies inside its Wilson interval")
        return self


class TrendColumn(IntelligenceModel):
    """One column of the market x context matrix (V2·7): the same rows, counted over the matches of one context."""

    context: TrendContext
    matches: int = Field(ge=0)
    rows: list[TrendRow]


class RadarAxis(IntelligenceModel):
    """Six fixed, non-redundant axes in percentile, oriented so that more is better (defensa = 100 - pct xG against ...)."""

    key: RadarKey
    percentile: int | Missing
    value: float | Missing


class TeamBody(IntelligenceModel):
    team: Ref
    record: Record
    figures: list[StatFigure]
    radar: list[RadarAxis]
    series: list[MatchPoint]
    halves: HalfSplit | Missing
    states: GameStates | Missing
    pulse_for: Pulse | Missing
    pulse_against: Pulse | Missing
    pulse_cards: Pulse | Missing
    intervals: GoalIntervals | Missing
    survival: Survival | Missing
    trends: ItemList[TrendRow]
    matrix: list[TrendColumn] | Missing = Field(description="The market x context matrix, carried by the documents of context "
                                                            "«all» (the others say sin_datos: they are one of its columns).")


class StripItem(IntelligenceModel):
    fixture_id: int
    kickoff_at: UtcDatetime
    opponent: Ref
    minutes: int = Field(ge=0)
    starter: bool
    values: list[StripValue]


class StripValue(IntelligenceModel):
    key: str = Field(pattern=CODE_PATTERN)
    value: int | Missing


class MinutesItem(IntelligenceModel):
    fixture_id: int
    minutes: int = Field(ge=0)
    starter: bool


class PlayerBody(IntelligenceModel):
    player: Ref
    team: Ref | Missing
    position: PositionGroup | Missing
    appearances: int = Field(ge=0)
    starts: int = Field(ge=0)
    minutes: int = Field(ge=0)
    nineties: float = Field(ge=0)
    min_nineties: float = Field(gt=0, description="The sample a percentile needs.")
    figures: list[StatFigure]
    last5: list[StripItem]
    recent_minutes: list[MinutesItem] = Field(description="His last ten appearances, oldest first.")


class ScatterPoint(IntelligenceModel):
    """A player of the same position (at least ``min_nineties``): shots per 90 against the share on target - V2·4's background."""

    player_id: int
    shots_per90: float = Field(ge=0)
    on_target_pct: float = Field(ge=0, le=100)


class StatsEntity(IntelligenceModel):
    role: EntityRole
    subject: StatsSubject
    competition: CompetitionSeasonRef
    scope: StatsScope
    context: StatsContext
    matches: int = Field(ge=0)
    calc_version: str = Field(min_length=1)
    computed_at: UtcDatetime
    available_scopes: list[StatsScope]
    available_competitions: list[CompetitionSeasonRef]
    team: TeamBody | Missing
    player: PlayerBody | Missing
    scatter: list[ScatterPoint] | Missing = Field(description="A player's position in his competition season (comparisons only).")

    @model_validator(mode="after")
    def _one_body(self) -> StatsEntity:
        if self.subject == "equipo" and not isinstance(self.player, Missing):
            raise ValueError("a team entity carries no player body")
        if self.subject == "jugador" and not isinstance(self.team, Missing):
            raise ValueError("a player entity carries no team body")
        return self


class MetricCoverage(IntelligenceModel):
    key: str = Field(pattern=CODE_PATTERN)
    share: float = Field(ge=0, le=1)
    publishable: bool


class StatsAudit(IntelligenceModel):
    run_id: int | Missing
    calc_version: str
    threshold: float = Field(ge=0, le=1)
    coverage: list[MetricCoverage]


class StatsEntityPrivate(StatsEntity):
    audit: StatsAudit = private(description="The calculation behind the figures: its run, version and the coverage of each metric.")


class StatsProfile(IntelligenceContract):
    CONTRACT_ID: ClassVar[str] = "C-13"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    entities: list[StatsEntity] = Field(min_length=1, max_length=2)


class StatsProfilePrivate(StatsProfile):
    entities: list[StatsEntityPrivate] = Field(min_length=1, max_length=2)  # type: ignore[assignment]


StripItem.model_rebuild()
