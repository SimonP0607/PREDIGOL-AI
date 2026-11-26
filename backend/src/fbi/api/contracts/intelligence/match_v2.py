"""C-01 2.0.0, the match complete: delivery 2 of AD-J02 (IA-131), composed from what the plan's pieces already compute.

A NEW MAJOR VERSION BESIDE 1.x. ``match.py`` (1.1.0) keeps its two routes and its shape, frozen (``C-01@1`` in the snapshot of
contracts): nothing of it changes. 2.0.0 has its own two routes (``…/intelligence/v2``) and its own classes, named ``MatchV2…``
so that no schema of the OpenAPI document is renamed. It keeps every block of 1.x that a reader is already shown (the match,
the one figure per outcome, «Cómo llegan», the official line-up, the reader's chronicle, the published selections and the
citations, the private shadow of 1.x) and fills the blocks 1.x left absent:

* ``scenarios`` - what each side still plays for (``scenarios-v2``, AD-B02, IA-082): each objective with ``necesita``,
  ``depende_de``, ``decidido`` (proved or not) and its simulated probability, what each result of this match does, and the fact
  ``SIN_OBJETIVO_DEMOSTRADO`` only where the engine proved it;
* ``chronicle`` - the one chronicle (``chronicle-v4``, AD-F02, IA-104) by the eight sections of its content plan, each with its
  verified sentences or its abstention, and the update after the official line-up (``lineup-update-v1``, IA-116). «Las
  claves», «Riesgos», «Jugadores a seguir», «Lo nuevo» and «Qué falta» of 1.x are, in 2.0.0, sections of this chronicle
  (``que_puede_definir``, ``riesgos``, ``jugadores``, ``novedades``, ``que_falta``): the content plan is where they live;
* ``evaluations`` - E1-E4 with their versions (``eval-cycle-v1``, AD-D06, IA-105), each kept, none rewritten;
* ``markets`` - where each market shown stands in the catalogue (AD-E01, IA-070);
* ``availability`` - who may miss the match (AD-H05, IA-091): state, basis, source and date, nothing medical;
* ``new_since_yesterday`` - the citations PrediGol first read in the last 24 hours;
* ``pending_unknowns`` - «Qué falta por saber y cuándo», by code: the official line-up (and, privately, the evaluations to come).

THE PUBLIC PROJECTION carries a shadow block ONLY when the owner published it (``PUBLISHED_BLOCKS`` of the service: none today),
and only behind ``FBI_MATCH_INTELLIGENCE`` (off). Until then it says ``pendiente_derechos`` - which tells a reader nothing about
whether the block exists in the shadow. The PRIVATE projection (``require_admin``) adds, for each of those blocks, its shadow
value (``*_shadow``), and the owner's own: the C-07 sources of the analysis (IA-122), the C-05 alerts of the match (IA-107), the
C-02 state of every selection in the cycle (IA-114) and the players' forecasts (``player-engine-v2``, IA-129). Nothing
experimental, nothing medical, no third-party text reaches the public one.

The examples are in ``tests/fixtures/contracts/intelligence/C-01/v2``; the owner's guide is
``docs/owner/IA_131_CONTRATO_PARTIDO_V2.md``.
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.alerts import AlertItem
from fbi.api.contracts.intelligence.base import (
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    Probability,
    UtcDatetime,
    private,
)
from fbi.api.contracts.intelligence.match import (
    Brief,
    Citation,
    EvidenceRecord,
    MatchInfo,
    OfficialLineup,
    OutcomeFigure,
    OutcomeFigurePrivate,
    PacketRef,
    ReaderChronicle,
    Selection,
    SelectionPrivate,
    SideForm,
    SideStakes,
    SingleFigure,
    TeamRef,
)
from fbi.api.contracts.intelligence.profiles import AvailabilityEntry
from fbi.api.contracts.intelligence.sources import AnalysisSourcesPrivate
from fbi.api.contracts.intelligence.vocab import (
    CalibrationSeal,
    EvaluationStep,
    LifecycleState,
    MarketState,
)

SCENARIOS_ORIGIN: Final = "scenarios-v2"
"""``fbi.competitions.scenarios.VERSION`` (a test holds the two equal)."""

Side = Literal["home", "away"]
ScenarioState = Literal["conseguido", "descartado", "abierto"]
"""What the engine certified of an objective: achieved, ruled out, or still open (``fbi.competitions.scenarios.State``)."""
DependsKind = Literal["decidido", "de_si_mismo", "de_otros"]
"""Decided; open and in its own hands (some points secure it); open and depending on others."""
ResultWord = Literal["victoria", "empate", "derrota"]
ChronicleSectionCode = Literal["que_se_juega", "como_llega", "que_puede_definir", "estadisticas", "jugadores", "novedades",
                               "riesgos", "que_falta"]
"""The eight sections of the content plan (``fbi.chronicle.plan.SECTIONS``; a test holds the two equal)."""
ChronicleStatus = Literal["ok", "partial"]
WhyOrigin = Literal["decision", "chronicle", "update"]
EvaluationCause = Literal["ventana", "hecho_nuevo", "alineacion_oficial", "correccion_alineacion"]
EvaluationRunStatus = Literal["completa", "sin_candidatos", "fallida"]
Verdict = Literal["lectura", "confirmada", "sigue_igual", "modificada", "retirada", "pendiente", "descartada"]
"""What an evaluation made of a selection (``intel.eval_verdicts.verdict``)."""
PriceState = Literal["vigente", "antiguo", "sin_precio"]
PendingWhat = Literal["alineacion_oficial", "evaluacion_e1", "evaluacion_e3", "evaluacion_e4"]
PlayerStartBasis = Literal["confirmed_starter", "confirmed_bench", "not_in_lineup", "baja_confirmada", "minutos_recientes",
                           "con_hecho_titular"]

ABSTENTION_PATTERN: Final = r"^[A-Z][A-Z_]{2,40}$"
LINE_PATTERN: Final = r"^-?\d+\.\d{2}$"


# ── scenarios (AD-B02) ───────────────────────────────────────────────────────────────────────────────────────────────

class MatchV2Decided(IntelligenceModel):
    """Whether the objective is decided: only when PROVED (``demostrado``), never by a probability."""

    value: bool
    proved: bool
    reasons: list[str] = Field(description="Why it is not taken as decided although certified (zona_condicional...).")


class MatchV2Needs(IntelligenceModel):
    """What the side needs: its points now and at most, the matches it has left and the points that secure the objective."""

    points: int
    max_points: int
    matches_left: int = Field(ge=0)
    points_that_secure: int | Missing = Field(description="Points that secure it whatever the others do, or why there is no such "
                                                          "number (decided, or it depends on others).")


class MatchV2DependsOn(IntelligenceModel):
    kind: DependsKind
    rivals: list[int] = Field(description="The teams (core ids) it contests the objective with (8 at most).")


class MatchV2AfterResult(IntelligenceModel):
    """What one result of THIS match does to the objective: its certified state after it and its probability given it."""

    result: ResultWord
    state: ScenarioState
    probability: Probability | Missing


class MatchV2Objective(IntelligenceModel):
    """One objective of a side in one table (``objetivo``, ``necesita``, ``depende_de``, ``decidido``)."""

    table: str = Field(min_length=1, description="The table's key in the reading (fase_liga, grupo_a, anual...).")
    objective: str = Field(pattern=r"^[a-z][a-z_]*$", description="titulo, clasificacion, evitar_descenso...")
    places: list[int] = Field(description="The places of the zone (first and last).")
    conditional: bool = Field(description="A zone the regulation leaves conditional: never taken as decided.")
    state: ScenarioState
    decided: MatchV2Decided
    probability: Probability | Missing = Field(description="Its simulated probability (our goal model, sin_calibrar), or why "
                                                           "there is none.")
    needs: MatchV2Needs
    depends_on: MatchV2DependsOn
    after_result: ItemList[MatchV2AfterResult] = Field(description="What each result of this match does to it.")


class MatchV2SideScenario(IntelligenceModel):
    side: Side
    team: TeamRef
    no_objective_proved: bool = Field(description="True only when the engine PROVED SIN_OBJETIVO_DEMOSTRADO for the side.")
    no_objective_reasons: list[str] = Field(description="Why SIN_OBJETIVO_DEMOSTRADO is not proved (open objectives, gaps).")
    objectives: ItemList[MatchV2Objective]


class MatchV2Scenarios(IntelligenceModel):
    """«Qué se juega» as the scenarios engine read the competition season (its newest reading of the last 3 days)."""

    version: str = Field(pattern=r"^scenarios-v\d+$")
    computed_at: UtcDatetime
    rules_version: int | Missing = Field(description="The version of the coded regulation the reading used.")
    contradictions: int = Field(ge=0, description="Claims the simulation contradicted and the engine withdrew.")
    sides: list[MatchV2SideScenario] = Field(min_length=1)


# ── the one chronicle (AD-F02, IA-104/116) ───────────────────────────────────────────────────────────────────────────

class MatchV2ChronicleSection(IntelligenceModel):
    """One section of the content plan: the sentences the verifier let stand (ES and EN), or the section's abstention."""

    code: ChronicleSectionCode
    es: list[str]
    en: list[str]
    abstention: str | Missing = Field(description="The plan's code for a section with nothing to tell (SIN_RIESGOS, "
                                                  "NADA_PENDIENTE...), present exactly when it has no sentence.")

    @model_validator(mode="after")
    def _said_or_abstained(self) -> MatchV2ChronicleSection:
        if len(self.es) != len(self.en):
            raise ValueError("a section has as many sentences in Spanish as in English")
        if bool(self.es) == isinstance(self.abstention, str):
            raise ValueError("a section has sentences or an abstention, never both and never neither")
        if isinstance(self.abstention, str) and not self.abstention.replace("_", "").isupper():
            raise ValueError("an abstention is an upper-case code")
        return self


class MatchV2SupersededRef(IntelligenceModel):
    """A sentence of the chronicle the official line-up made outdated: never rewritten, corrected by the update at its hour."""

    section: ChronicleSectionCode
    index: int = Field(ge=0)


class MatchV2LineupUpdate(IntelligenceModel):
    """The paragraph added when the official line-up arrived (by template, no model: ``lineup-update-v1``)."""

    version: str = Field(pattern=r"^lineup-update-v\d+$")
    chronicle_id: int
    written_at: UtcDatetime
    es: list[str] = Field(min_length=1)
    en: list[str] = Field(min_length=1)
    superseded: list[MatchV2SupersededRef]


class MatchV2Chronicle(IntelligenceModel):
    """The one chronicle of the match, its newest verified version: written by the small model from the content plan only,
    checked sentence by sentence (a sentence without support is dropped, not the whole text)."""

    version: str = Field(pattern=r"^chronicle-v\d+$")
    chronicle_id: int
    written_at: UtcDatetime
    plan_at: UtcDatetime = Field(description="The moment of the facts the plan was made from.")
    plan_version: str = Field(pattern=r"^content-plan-v\d+$")
    verify_version: str = Field(pattern=r"^chronicle-verify-v\d+$")
    figure_version: str | Missing
    status: ChronicleStatus = Field(description="ok: every planned sentence stood; partial: some were dropped.")
    sections: list[MatchV2ChronicleSection] = Field(min_length=1)
    lineup_update: MatchV2LineupUpdate | Missing = Field(description="The update after the official line-up, or when it is "
                                                                     "expected.")


class MatchV2WhyPhrase(IntelligenceModel):
    es: str = Field(min_length=1)
    en: str = Field(min_length=1)
    origin: WhyOrigin = Field(description="Where the phrase comes from: the decision's record, the chronicle or the update.")


class MatchV2SelectionWhy(IntelligenceModel):
    """The why of a selection after E3 (``selection-why-v1``): every phrase with its origin."""

    market_key: str = Field(min_length=1)
    selection: str = Field(min_length=1)
    line: str = Field(min_length=1)
    verdict: Verdict
    state: LifecycleState
    reason: str
    phrases: list[MatchV2WhyPhrase] = Field(min_length=1)


class MatchV2ChroniclePrivate(MatchV2Chronicle):
    """The chronicle as the owner sees it: also the why of each selection E3 judged, and the attempts' record."""

    selection_whys: list[MatchV2SelectionWhy] = private(description="The why of each selection after the line-up (shadow).")
    attempts: int = private(ge=1, description="Rows of the match in ai.chronicles up to the answer's moment.")


# ── the evaluations E1-E4 (AD-D06, IA-105) ───────────────────────────────────────────────────────────────────────────

class MatchV2Evaluation(IntelligenceModel):
    """One evaluation of the match: its step, its version (each one adds one; none is rewritten), why it ran and when."""

    evaluation: EvaluationStep
    evaluation_version: int = Field(ge=1)
    cause: EvaluationCause
    known_at: UtcDatetime
    status: EvaluationRunStatus


class MatchV2Verdict(IntelligenceModel):
    """What one evaluation made of one selection (decided by code), with the figure and price it judged."""

    market_key: str = Field(min_length=1)
    selection: str = Field(min_length=1)
    line: str = Field(pattern=LINE_PATTERN)
    verdict: Verdict
    state: LifecycleState
    reason: str = Field(min_length=1)
    probability: Probability | Missing = Field(description="decision-v2's figure at this evaluation, with its seal.")
    odds: float | Missing
    price_state: PriceState | Missing


class MatchV2EvaluationPrivate(MatchV2Evaluation):
    decided: bool = private(description="Whether decision-v2 decided again at this evaluation.")
    latency_ms: int | Missing = private(description="From the trigger to the end (E3: from the line-up's arrival).")
    error: str | Missing = private(description="The code of a failed evaluation.")
    verdicts: ItemList[MatchV2Verdict] = private(description="What it made of each selection.")


# ── the market catalogue, availability, what is new, what is pending ────────────────────────────────────────────────

class MatchV2MarketStatus(IntelligenceModel):
    """Where a market shown in the answer stands (``market-states-v1``, AD-E01)."""

    market_key: str = Field(min_length=1)
    state: MarketState
    reason: str = Field(min_length=1)


class MatchV2MarketStatusPrivate(MatchV2MarketStatus):
    readers_see: bool = private(description="False for a market only the shadow shows (an unpublished selection's, a single "
                                            "figure's).")

    def shown_in_public(self) -> bool:
        return self.readers_see


class MatchV2SideAvailability(IntelligenceModel):
    """Who of a side may miss the match: state, basis, source and date (``availability-v1``) - nothing medical."""

    side: Side
    team: TeamRef
    report_checked_at: UtcDatetime | Missing = Field(description="When the provider's report of the season was last asked for.")
    unavailable: ItemList[AvailabilityEntry]


class MatchV2NewFact(IntelligenceModel):
    """A citation of this answer PrediGol first read in the last 24 hours (``n`` is its number in ``citations``)."""

    n: int = Field(ge=1)
    known_at: UtcDatetime


class MatchV2Pending(IntelligenceModel):
    """Something not known yet and when it is expected."""

    what: PendingWhat
    expected_at: UtcDatetime


class MatchV2PendingPrivate(MatchV2Pending):
    readers_see: bool = private(description="False for a step of the evaluation cycle (shadow).")

    def shown_in_public(self) -> bool:
        return self.readers_see


# ── the selections and the players (private additions) ─────────────────────────────────────────────────────────────

class MatchV2SelectionPrivate(SelectionPrivate):
    """A selection of 1.x and, from C-02 (IA-114), its state and reason in the cycle, its decision and its market's state."""

    lifecycle_reason: str | Missing = private(description="The reason of its state, in the cycle's closed list.")
    decision_id: int | Missing = private(description="The decision of intel.decisions: its C-02 is "
                                                     "/api/v1/admin/intelligence/decisions/{decision_id}.")
    market_state: MarketState | Missing = private(description="Where its market stands in the catalogue (AD-E01).")


class MatchV2PlayerForecast(IntelligenceModel):
    """One player's line of the shadow player engine (``player-engine-v2``): the probability of going over the line, its seal and
    what it rests on. No price, no pick."""

    team: TeamRef
    provider_player_id: int = Field(ge=1)
    name: str | Missing
    family: str = Field(min_length=1)
    line: float
    pct_over: float = Field(ge=0, le=100, description="P(count > line) in percent, one decimal, rounded by the server.")
    calibration: CalibrationSeal
    p_start_pct: float = Field(ge=0, le=100)
    expected_minutes: float = Field(ge=0)
    start_basis: PlayerStartBasis
    lineup_confirmed: bool
    evaluation: Literal["E1", "E4"]
    known_at: UtcDatetime
    version: str = Field(pattern=r"^player-engine-v\d+$")


# ── the contract ─────────────────────────────────────────────────────────────────────────────────────────────────────

class MatchIntelligenceV2(IntelligenceContract):
    """C-01 2.0.0, public projection (``GET /api/v1/matches/{fixture_id}/intelligence/v2``, behind ``FBI_MATCH_INTELLIGENCE``)."""

    CONTRACT_ID: ClassVar[str] = "C-01"
    CONTRACT_VERSION: ClassVar[str] = "2.1.0"

    match: MatchInfo
    probabilities: ItemList[OutcomeFigure] = Field(description="One figure per outcome: what a reader is shown (forecast-v1).")
    markets: ItemList[MatchV2MarketStatus] = Field(description="Where each market shown stands in the catalogue.")
    context: ItemList[SideStakes] = Field(description="What each side plays for as the packet read it (stakes-v5).")
    form: ItemList[SideForm] = Field(description="«Cómo llegan».")
    official_lineup: OfficialLineup | Missing
    availability: ItemList[MatchV2SideAvailability] = Field(description="Who may miss the match (FBI_PROFILES, as C-09).")
    reader_chronicle: ReaderChronicle | Missing = Field(description="The chronicle a reader is shown today (user-narrative-v3).")
    selections: ItemList[Selection]
    citations: ItemList[Citation]
    new_since_yesterday: ItemList[MatchV2NewFact] = Field(description="«Lo nuevo desde ayer»: citations first read in 24 h.")
    pending_unknowns: ItemList[MatchV2Pending] = Field(description="«Qué falta por saber y cuándo».")
    scenarios: MatchV2Scenarios | Missing = Field(description="«Qué se juega» (scenarios-v2), once the owner publishes it.")
    chronicle: MatchV2Chronicle | Missing = Field(description="The one chronicle (chronicle-v4), once the owner publishes it.")
    evaluations: ItemList[MatchV2Evaluation] | Missing = Field(description="E1-E4 with their versions, once published.")

    @model_validator(mode="after")
    def _one_figure_per_outcome(self) -> MatchIntelligenceV2:
        keys = [(p.market, p.line, p.outcome) for p in self.probabilities.items]
        if len(keys) != len(set(keys)):
            raise ValueError("one figure per outcome")
        figures = [p.probability for p in self.probabilities.items]
        for s in self.selections.items:
            if isinstance(s.probability, Probability) and s.probability not in figures:
                raise ValueError(f"{s.market} {s.selection} {s.line}: a selection carries the outcome's one figure")
        numbers = {c.n for c in self.citations.items}
        if any(f.n not in numbers for f in self.new_since_yesterday.items):
            raise ValueError("what is new is a citation of the answer")
        return self


class MatchIntelligenceV2Private(MatchIntelligenceV2):
    """C-01 2.0.0, private projection (``GET /api/v1/admin/intelligence/matches/{fixture_id}/intelligence/v2``,
    require_admin): the public one and the shadow of every block."""

    probabilities: ItemList[OutcomeFigurePrivate]  # type: ignore[assignment]  # the private variant of each item
    markets: ItemList[MatchV2MarketStatusPrivate]  # type: ignore[assignment]
    selections: ItemList[MatchV2SelectionPrivate]  # type: ignore[assignment]
    pending_unknowns: ItemList[MatchV2PendingPrivate]  # type: ignore[assignment]
    scenarios_shadow: MatchV2Scenarios | Missing = private(description="The engine's newest reading, published or not.")
    chronicle_shadow: MatchV2ChroniclePrivate | Missing = private(description="The newest verified chronicle, published or not.")
    evaluations_shadow: ItemList[MatchV2EvaluationPrivate] | Missing = private(
        description="Every evaluation E1-E4 of the match with its verdicts, oldest first.")
    sources: AnalysisSourcesPrivate | Missing = private(description="C-07, the sources of the analysis (IA-122), embedded.")
    alerts: ItemList[AlertItem] | Missing = private(description="C-05, the owner's alerts of this match (IA-107), newest first.")
    player_forecasts: ItemList[MatchV2PlayerForecast] | Missing = private(
        description="player-engine-v2 (IA-129), the newest evaluation's lines, in the shadow.")
    single_figure: ItemList[SingleFigure] = private(description="The single figure (forecast-v2, AD-B05), as in 1.1.0.")
    packet: PacketRef | Missing = private(description="The match packet the context and the form were read from.")
    brief: Brief | Missing = private(description="The AI's latest brief, unverified words included.")
    chronicle_preview: ReaderChronicle | Missing = private(
        description="The reader's chronicle (user-narrative-v3) whether or not readers are shown it.")
    evidence: ItemList[EvidenceRecord] = private(description="The web items of the match, newest first (60 at most).")
