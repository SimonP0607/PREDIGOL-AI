"""C-16, availability (plan PM, section 4; PM-02-05): what PrediGol has for each competition, season, datum and market, and the seven
states of every block and market of a match - so that a page paints a block only where the matrix says there is something to paint.

* ``GET /api/v1/availability/competitions`` - the directory: each tracked competition with its summary (``A``, ``B``, ``C``, ``D``,
  ``MI``; ``B*`` / ``C*`` when graded without odds) and its seven families, from its latest graded season. Only the directory reads the
  summary: no page decides with it.
* ``GET /api/v1/availability/competitions/{competition_id}`` - the same competition with its seasons and every cell: level, sample,
  share, provisional, why and when it was measured.
* ``GET /api/v1/matches/{fixture_id}/availability`` - the blocks and markets of the match with their seven states and the reason
  (``fbi.coverage.resolve``): exists, coverage, price in force, probability computed, calibrated and authorised, settleable, and what
  Mi parlay, Picks and Cuotas do with it.
* ``GET /api/v1/admin/availability/matrix`` and ``GET /api/v1/admin/availability/changes`` - the private projection: the whole matrix
  with what each recalculation measured, the changes of level and the shadow comparison's discrepancies (PM-02-06).

Every route answers 404 while ``FBI_AVAILABILITY`` is off (the default). The levels are ``coverage-levels-v1`` (``fbi.coverage.levels``).

1.1.0 (PM-02-07): a cup season carries the data cells of each of its phases (``phases``) and a match says which phase graded its blocks
(``phase``), while ``FBI_AVAILABILITY_PHASES`` is on; off, ``phases`` is empty and ``phase`` is ``todas``.

1.2.0 (PM-09-05, UX-179): each competition carries its editorial priority (``priority``, P0 to P4, from
``config/coverage/prioridad_editorial.yaml``, annex A): where PrediGol puts more attention, not how much data there is. The directory
(lámina I08) marks P0 and P1 as «Destacada»; no page decides with it.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field

from fbi.api.contracts.intelligence.base import (
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    UtcDatetime,
    private,
)
from fbi.api.contracts.intelligence.vocab import MarketState

Level = Literal["A", "B", "C", "D", "MI"]
EditorialPriority = Literal["P0", "P1", "P2", "P3", "P4"]
"""Annex A's editorial priority (``fbi.coverage.depth.priorities``)."""
"""``coverage-levels-v1``: A completa, B intermedia, C básica, D limitada, MI muestra insuficiente."""
CellReason = Literal["ninguno", "heredado", "muestra_insuficiente", "menos_de_3_casas", "menos_de_5_casas", "no_entregado",
                     "sin_ventana", "sin_medir"]
"""Why a cell has the level it has: ``heredado`` (the season before, short of sample now: provisional), ``sin_ventana`` (no finished
match in the odds window), ``sin_medir`` (the nightly batch has not graded it), ``ninguno`` when the level needs no explanation."""
MarketReason = Literal["ninguno", "sin_regla", "sin_cobertura", "muestra_insuficiente", "heredado", "menos_de_3_casas",
                       "menos_de_5_casas", "no_entregado", "sin_ventana"]
Module = Literal["mi_parlay", "picks", "cuotas"]
ModuleReason = Literal["ok", "invalid_selection", "quarter_line", "started", "market_not_priced", "outlier_price", "error_interno",
                       "MERCADO_NO_EVALUABLE", "SIN_PROBABILIDAD", "menos_de_3_casas", "sin_precio"]
"""Mi parlay's codes are the ones ``validate_parlay`` answers a leg with; Picks' are abstention codes; Cuotas' say why no price shows."""
Scope = Literal["directorio", "competicion", "partido", "matriz", "cambios"]
Family = Literal["base", "team_stats", "xg", "player_stats", "referee", "main_odds", "stat_odds"]
CupPhase = Literal["previa", "liga_o_grupos", "eliminatoria"]
"""A cup's phases (PM-02-07): qualifying rounds and the knock-out rounds before the league or group stage; that stage; the knock-out
rounds after it."""
MatchPhase = Literal["todas", "previa", "liga_o_grupos", "eliminatoria"]


class FamilyLevel(IntelligenceModel):
    family: Family
    level: Level


class LevelCell(IntelligenceModel):
    """One datum or market of one competition season and phase."""

    key: str = Field(min_length=1, description="The datum (events, corners ...) or the market (1X2, corners ...).")
    level: Level
    n: int = Field(ge=0, description="Finished matches graded (of the odds window, for a market).")
    with_data: int = Field(ge=0, description="Of them, with the datum for both teams (priced, for a market).")
    pct: float | Missing = Field(description="with_data over n, in percent with one decimal.")
    provisional: bool
    reason: CellReason
    measured_at: UtcDatetime


class LevelCellPrivate(LevelCell):
    measured_level: Level = private(description="What the last recalculation measured (rule 4: a level goes down on the second miss).")
    missed: bool = private(description="The last recalculation measured less than the published level and kept it.")
    pooled_seasons: int = private(ge=1, description="Editions pooled (rule 3: a one-match competition pools its last five).")
    declared: Literal["si", "no", "sin_bandera"] = private(description="What the provider declares (rule 5: only its «no» is used).")


class MarketCell(LevelCell):
    median_books: float | Missing = Field(description="Median of houses over the priced matches of the window.")
    settle_pct: float | Missing = Field(description="Finished matches of the season whose stored result settles the market, in percent.")


class MarketCellPrivate(MarketCell):
    measured_level: Level = private(description="What the last recalculation measured.")
    missed: bool = private(description="The last recalculation measured less than the published level and kept it.")
    pooled_seasons: int = private(ge=1, description="Editions pooled.")
    declared: Literal["si", "no", "sin_bandera"] = private(description="What the provider declares about odds.")
    catalogue_state: MarketState | Missing = private(description="The catalogue's state of the market's main bet, as last measured.")


class PhaseAvailability(IntelligenceModel):
    """The data cells of one phase of a cup season (the markets stay on ``todas``)."""

    phase: CupPhase
    data: list[LevelCell]


class PhaseAvailabilityPrivate(PhaseAvailability):
    data: list[LevelCellPrivate]  # type: ignore[assignment]


class SeasonAvailability(IntelligenceModel):
    competition_season_id: int = Field(ge=1)
    season: int
    phase: str = Field(min_length=1, description="todas: the season whole (its phases, if any, are in ``phases``).")
    summary: Level
    summary_label: str = Field(min_length=1, description="The summary as the directory writes it: B* / C* without odds.")
    families: list[FamilyLevel]
    data: list[LevelCell]
    markets: list[MarketCell]
    phases: list[PhaseAvailability] = Field(default_factory=list, description=(
        "A cup season's phases with matches (1.1.0, PM-02-07): empty for a league, a cup in one phase, or while "
        "FBI_AVAILABILITY_PHASES is off."))


class SeasonAvailabilityPrivate(SeasonAvailability):
    data: list[LevelCellPrivate]  # type: ignore[assignment]
    markets: list[MarketCellPrivate]  # type: ignore[assignment]
    phases: list[PhaseAvailabilityPrivate] = Field(default_factory=list)  # type: ignore[assignment]


class CompetitionAvailability(IntelligenceModel):
    competition_id: int = Field(ge=1)
    name: str = Field(min_length=1)
    country: str | Missing
    tier: int | Missing = Field(description="PrediGol's priority of the competition (core.competitions.tier).")
    priority: EditorialPriority | Missing = Field(description=(
        "1.2.0: the editorial priority of annex A (P0 Colombia, P1 international, P2 priority countries, P3 the rest followed, P4 the "
        "English pyramid 5-7); sin_datos for a competition the file does not list."))
    summary: Level
    summary_label: str = Field(min_length=1)
    families: list[FamilyLevel]
    seasons: list[SeasonAvailability] = Field(description="Only on the competition's own route and the private matrix; empty in "
                                                          "the directory.")


class CompetitionAvailabilityPrivate(CompetitionAvailability):
    seasons: list[SeasonAvailabilityPrivate]  # type: ignore[assignment]


class BlockAvailability(IntelligenceModel):
    key: str = Field(min_length=1, description="events, lineups, team_stats, shots_on_target, fouls, xg, player_stats, referee.")
    exists: bool
    level: Level | Missing
    n: int = Field(ge=0)
    provisional: bool
    reason: CellReason


class ModuleVerdict(IntelligenceModel):
    module: Module
    ok: bool
    reason: ModuleReason


class SelectionVerdict(IntelligenceModel):
    selection: str = Field(min_length=1)
    line: float
    books: int = Field(ge=0)
    mi_parlay: list[ModuleReason] = Field(description="Mi parlay's refusals of this selection as one leg; empty when it takes it.")


class MarketAvailability(IntelligenceModel):
    key: str = Field(min_length=1, description="The leg's market key: 1X2 ... or code.period.subject.")
    matrix_market: str | Missing
    exists: bool
    coverage_ok: bool | Missing
    level: Level | Missing
    price_in_force: bool
    prob_computed: bool
    prob_authorised: bool
    settleable: bool
    reason: MarketReason
    modules: list[ModuleVerdict] = Field(min_length=3, max_length=3)


class MarketAvailabilityPrivate(MarketAvailability):
    catalogue_state: MarketState | Missing = private(description="The catalogue's state of the bet (IA-070), as the API reads it.")
    selections: list[SelectionVerdict] = private(description="Every selection and line priced now, with Mi parlay's verdict.")


class MatchAvailability(IntelligenceModel):
    fixture_id: int = Field(ge=1)
    kickoff_at: UtcDatetime
    competition_season_id: int | Missing
    phase: MatchPhase = Field(default="todas", description=(
        "The phase whose cells graded the blocks (1.1.0, PM-02-07): the cup match's own phase while FBI_AVAILABILITY_PHASES is on and "
        "the phase was measured; todas otherwise."))
    blocks: list[BlockAvailability]
    markets: list[MarketAvailability]
    notes: list[Literal["muestra_insuficiente"]]


class MatchAvailabilityPrivate(MatchAvailability):
    markets: list[MarketAvailabilityPrivate]  # type: ignore[assignment]


class LevelChange(IntelligenceModel):
    competition_season_id: int = Field(ge=1)
    phase: str
    kind: Literal["datum", "market"]
    key: str = Field(min_length=1)
    old_level: Level | Missing
    new_level: Level
    reason: Literal["primera_medida", "sube", "baja", "incumple_una_vez"]
    n: int | Missing
    changed_at: UtcDatetime


class Discrepancy(IntelligenceModel):
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    fixture_id: int = Field(ge=1)
    module: str = Field(min_length=1)
    key: str = Field(min_length=1)
    shown: bool = Field(description="What the module shows today.")
    matrix: bool = Field(description="What the matrix would say.")
    reason: str = Field(min_length=1)
    observed_at: UtcDatetime


class Availability(IntelligenceContract):
    CONTRACT_ID: ClassVar[str] = "C-16"
    CONTRACT_VERSION: ClassVar[str] = "1.2.0"

    rules_version: str = Field(pattern=r"^[a-z][a-z0-9-]{1,40}-v[0-9]+$")
    scope: Scope
    competitions: list[CompetitionAvailability]
    match: MatchAvailability | Missing


class AvailabilityPrivate(Availability):
    competitions: list[CompetitionAvailabilityPrivate]  # type: ignore[assignment]
    match: MatchAvailabilityPrivate | Missing
    changes: ItemList[LevelChange] = private(description="The changes of level of the last seven days (the matrix and changes routes).")
    discrepancies: ItemList[Discrepancy] = private(description="The shadow comparison's discrepancies of the last seven days (PM-02-06).")
