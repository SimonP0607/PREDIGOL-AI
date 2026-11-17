"""C-01, the match: the contract the «Intelligence» tab and the full analysis of a match read (AD-J02, IA-066).

Delivery 1 (wave 1): the complete shape, filled ONLY with what PrediGol already computes, and every block that does not
exist yet as absent with its reason and the piece that will compute it. Nothing here is new arithmetic:

* ``probabilities`` - the one figure per outcome that a reader already sees in the Match Center: the forecast
  (``forecast-v1``, written by the common probability view ``fbi.forecasting.market_view``), with its seal (``calibrada``
  only where a champion calibrator was applied with a fresh price, else ``sin_calibrar``). The private projection adds the
  model's own number (``raw_probability``, always ``sin_calibrar``), the model, why it is uncalibrated and the fair odds.
* ``context`` - the stakes of each side as the match packet read them (``stakes-v5``); ``form`` - «Cómo llegan».
* ``official_lineup`` - the provider's official line-up, or when it is expected.
* ``reader_chronicle`` - the chronicle a reader is shown today (``user-narrative-v3``, checked in the worker), only while
  the owner shows it; the one chronicle of AD-F02 (``chronicle``) is absent until it exists.
* ``selections`` - the public projection lists only what a reader is shown as a pick (the ``qualified`` daily set); the
  private one lists every selection with the decision layer's state (``decision-v1``, in the shadow) and its numbers.
* ``citations`` - the outside facts of the match exactly as its news show them to a reader, each with its four dates; the
  private projection adds every stored item of evidence.

Absent with their reason (``no_entregado``): scenarios (AD-B02), the one chronicle (AD-F02), the evaluations E1-E4
(AD-D06), «Lo nuevo desde ayer» (AD-C07), «Qué falta por saber» (AD-D05), the keys and the risks (AD-F01), the players to
watch (AD-H07), and each outcome's price with its age (AD-B06). A figure's evaluation step is absent until AD-D06.
The example of every case is in ``tests/fixtures/contracts/intelligence/C-01``; the owner's guide is
``docs/owner/IA_066_CONTRATO_PARTIDO.md``.
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    DatedFact,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    Probability,
    Source,
    UtcDatetime,
    private,
)
from fbi.api.contracts.intelligence.vocab import (
    ConfirmationLevel,
    FactRelation,
    LifecycleState,
    PublicState,
    StoryWarning,
)

FORECAST_ORIGIN: Final = "forecast-v1"
DECISION_ORIGIN: Final = "decision-v1"

MatchPhase = Literal["previo", "en_juego", "terminado", "aplazado", "cancelado", "otro"]
"""Where the match stands, from the provider's status: before kick-off, in play, over, postponed, cancelled, other."""

Side = Literal["home", "away"]
ForecastMarketKey = Literal["1X2", "OU", "BTTS"]
"""The markets the one figure covers today (``fbi.forecasting.market_view.MARKETS``); the rest wait for AD-B04/AD-B05."""
OutcomeCode = Literal["home", "draw", "away", "over", "under", "yes", "no"]
ForecastBasis = Literal["champion", "no_champion", "needs_price", "not_applicable"]
"""Why a figure is or is not calibrated (``market_view.BASIS_*``): a champion applied, no champion for the market, a
champion that needs a fresh price and had none, or nothing to apply."""

Zone = Literal["title", "europe", "relegation", "promotion", "playoff", "other", "none"]
"""A zone of the table (``fbi.ai.context.zone_kind``, ``stakes-v5``); ``none``: the side sits in no zone."""
Pressure = Literal["title", "europe", "relegation", "promotion", "playoff", "mid_table", "settled", "unknown", "other"]
"""What a side plays for (``fbi.ai.context.stakes``): an inference from its zone or the nearest reachable boundary."""

DecisionState = Literal["RECHAZADO", "INVESTIGACION", "CAUTELA", "APROBADO", "PICK_DEL_DIA", "CANDIDATO_PARLAY",
                        "PICK_PREMIUM"]
"""The decision layer's state of a selection (``decision-v1``, in the shadow). Private: never a reader's word."""

ChronicleKey = Literal["summary", "home", "away", "h2h", "risks"]


# ── the match ────────────────────────────────────────────────────────────────────────────────────────────────────────

class TeamRef(IntelligenceModel):
    id: int
    name: str = Field(min_length=1)


class CompetitionRef(IntelligenceModel):
    id: int
    name: str = Field(min_length=1)
    country: str | Missing


class MatchInfo(IntelligenceModel):
    """The match as the provider gives it."""

    id: int
    home: TeamRef
    away: TeamRef
    competition: CompetitionRef
    kickoff_at: UtcDatetime
    round: str | Missing = Field(description="The provider's round («Regular Season - 12»), or why there is none.")
    venue: str | Missing = Field(description="The stadium's name as the provider gives it (AD-H04 will identify it).")
    status: str = Field(min_length=1, description="The provider's short status (NS, 1H, FT…), as it comes.")
    phase: MatchPhase


# ── one figure per outcome ───────────────────────────────────────────────────────────────────────────────────────────

class OutcomeFigure(IntelligenceModel):
    """One outcome of a market and its one figure: the one the Match Center shows, with its seal."""

    market: ForecastMarketKey
    line: float = Field(description="0 for 1X2 and BTTS, 2.5 for total goals.")
    outcome: OutcomeCode
    probability: Probability
    price: Missing = Field(description="The best price with its age and books: AD-B06 (absent in delivery 1).")


class OutcomeFigurePrivate(OutcomeFigure):
    """The same outcome as the owner sees it: the model's own number, which model, why it is (un)calibrated, the fair
    odds, and whether a reader sees the figure (``FBI_FORECAST_USERS``)."""

    raw_probability: Probability = private(description="The model's own number, always sealed sin_calibrar.")
    model: str = private(description="The model the market's figure came from.")
    basis: ForecastBasis = private(description="Why it is calibrated or not.")
    fair_odds: float = private(ge=1, description="1 / probability, rounded to two decimals.")
    readers_see: bool = private(description="False while the owner keeps the forecast from readers.")

    def shown_in_public(self) -> bool:
        return self.readers_see


# ── context and form («Cómo llegan») ─────────────────────────────────────────────────────────────────────────────────

class ZoneGap(IntelligenceModel):
    zone: Zone
    points: int = Field(description="Points to that zone's boundary.")


class SideStakes(IntelligenceModel):
    """What a side plays for, as the packet read its table (``stakes-v5``)."""

    side: Side
    team: TeamRef
    rank: int = Field(ge=1)
    zone: Zone
    pressure: Pressure
    above: ZoneGap | Missing = Field(description="The nearest better zone and the points to it, or why there is none.")
    below: ZoneGap | Missing = Field(description="The nearest worse zone and the points above it, or why there is none.")
    remaining: int | Missing = Field(description="Matches left in the table.")
    settled: bool | Missing = Field(description="No boundary is reachable either way any more.")
    rule: str = Field(pattern=r"^stakes-v\d+$", description="The rule that read the table.")
    known_at: UtcDatetime = Field(description="When the packet that holds it was built.")


class SideForm(IntelligenceModel):
    """How a side arrives: its last results, as the packet holds them."""

    side: Side
    team: TeamRef
    matches: int = Field(ge=1)
    sequence: str = Field(pattern=r"^[WDL]{1,10}$", description="Oldest to newest: W win, D draw, L loss.")
    points_per_game: float | Missing
    goals_for_per_game: float | Missing
    goals_against_per_game: float | Missing
    known_at: UtcDatetime


class SideLineup(IntelligenceModel):
    formation: str | Missing
    coach: str | Missing


class OfficialLineup(IntelligenceModel):
    """The provider's official line-up of both sides."""

    home: SideLineup
    away: SideLineup
    known_at: UtcDatetime = Field(description="When PrediGol last read it from the provider.")


# ── the chronicle a reader is shown today ────────────────────────────────────────────────────────────────────────────

class ChronicleSection(IntelligenceModel):
    key: ChronicleKey
    sentences: list[str] = Field(min_length=1)


class ReaderChronicle(IntelligenceModel):
    """The chronicle of the match as a reader reads it today (``user-narrative-v3``): written in the worker, checked
    there sentence by sentence against the facts, and shown only while it tells the story the data tell now."""

    version: str = Field(min_length=1)
    written_at: UtcDatetime
    data_at: UtcDatetime = Field(description="The moment of the data it was written from.")
    es: list[ChronicleSection]
    en: list[ChronicleSection]
    sources: list[str] = Field(description="The outlets of the news it tells.")


class Brief(IntelligenceModel):
    """The AI's latest brief of the match (``ai.match_briefs``): its own words, which no reader sees."""

    created_at: UtcDatetime
    pass_name: str = Field(min_length=1)
    version: str
    engine: str
    model: str | Missing
    status: str
    summary: str | Missing
    escalate: bool
    reasons: list[str]
    uncertainty: str | Missing
    data_quality: str | Missing


class PacketRef(IntelligenceModel):
    id: int
    version: str
    as_of: UtcDatetime
    missing: list[str] = Field(description="The blocks the packet could not check.")


# ── selections ───────────────────────────────────────────────────────────────────────────────────────────────────────

class Selection(IntelligenceModel):
    """A selection as a reader sees it: only what PrediGol shows as a pick, with its public state and the match's one
    figure of that outcome (the same object as in ``probabilities``)."""

    market: str = Field(pattern=r"^[A-Z0-9_]{1,12}$")
    selection: str = Field(min_length=1)
    line: float
    public_state: PublicState
    probability: Probability | Missing = Field(description="The outcome's one figure, or why there is none (the one "
                                                           "figure covers every market from AD-B05).")


class SelectionPrivate(Selection):
    """The same selection as the owner sees it: every selection of the decision layer (in the shadow) and of the day's
    sets, with its state and its numbers. ``public_state`` is null for what never reaches a reader."""

    public_state: PublicState | None = Field(  # type: ignore[assignment]
        description="publicada / en_juego / liquidada for a published pick; null: private.")
    published: bool = private(description="In the qualified daily set: the only set a reader is shown.")
    in_evaluation_set: bool = private(description="In the owner's evaluation set (shadow picks).")
    lifecycle_state: LifecycleState | Missing = private(description="The state in the cycle (AD-D02).")
    decision_state: DecisionState | Missing = private(description="The decision layer's state (decision-v1).")
    decision_probability: Probability | Missing = private(description="The decision layer's own figure.")
    decision_raw_probability: Probability | Missing = private(description="Its model's number, sin_calibrar.")
    odds: float | Missing = private(description="The price the decision read.")
    expected_value: float | Missing = private(description="Its expected value with the calibrated figure.")
    decided_at: UtcDatetime | Missing = private(description="When the decision was made.")
    reasons: list[str] = private(description="The decision's reasons, as codes.")

    @model_validator(mode="after")
    def _public_only_if_published(self) -> SelectionPrivate:
        if (self.public_state is not None) != self.published:
            raise ValueError("a selection has a public state exactly when it is published")
        return self

    def shown_in_public(self) -> bool:
        return self.public_state is not None


# ── citations ────────────────────────────────────────────────────────────────────────────────────────────────────────

class Citation(DatedFact):
    """An outside fact of the match as its news show it to a reader: PrediGol's own one-line summary, its level, its
    source and its four dates (``known_at``: when PrediGol first read it)."""

    n: int = Field(ge=1, description="The citation's number in this answer.")
    kind: str = Field(min_length=1)
    text: str = Field(min_length=1)
    confirmation: ConfirmationLevel | Missing = Field(description="Its level; absent for a contradiction or an "
                                                                  "outdated item until AD-C07.")
    warnings: list[StoryWarning]
    relation: FactRelation | Missing = Field(description="How it bears on the analysis (AD-G08).")
    source: Source


class EvidenceRecord(IntelligenceModel):
    """One web item of the match as PrediGol keeps it (``ai.evidence``, as the match's news read it): the owner's record,
    whatever its status or language - the extraction's own words included."""

    id: int
    kind: str
    status: str
    story_key: str
    claim: str
    source_name: str
    source_tier: str
    source_url: str | Missing
    published_at: UtcDatetime | Missing
    known_at: UtcDatetime
    last_seen_at: UtcDatetime | Missing


# ── the contract ─────────────────────────────────────────────────────────────────────────────────────────────────────

class MatchIntelligence(IntelligenceContract):
    """C-01, public projection (``GET /api/v1/matches/{fixture_id}/intelligence``, behind ``FBI_MATCH_INTELLIGENCE``)."""

    CONTRACT_ID: ClassVar[str] = "C-01"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    match: MatchInfo
    probabilities: ItemList[OutcomeFigure] = Field(description="One figure per outcome: the one the decision reads.")
    context: ItemList[SideStakes] = Field(description="What each side plays for (stakes-v5).")
    form: ItemList[SideForm] = Field(description="«Cómo llegan».")
    official_lineup: OfficialLineup | Missing
    reader_chronicle: ReaderChronicle | Missing = Field(description="The chronicle a reader is shown today.")
    selections: ItemList[Selection]
    citations: ItemList[Citation]
    scenarios: Missing = Field(description="«Qué se juega» as typed scenarios (AD-B02).")
    chronicle: Missing = Field(description="The one chronicle (AD-F02).")
    evaluations: Missing = Field(description="E1-E4 with their versions (AD-D06).")
    new_since_yesterday: Missing = Field(description="«Lo nuevo desde ayer» (AD-C07).")
    pending_unknowns: Missing = Field(description="«Qué falta por saber y cuándo» (AD-D05).")
    keys: Missing = Field(description="«Las claves» (AD-F01).")
    risks: Missing = Field(description="«Riesgos» (AD-F01).")
    players_to_watch: Missing = Field(description="«Jugadores a seguir» (AD-H07).")

    @model_validator(mode="after")
    def _one_figure_per_outcome(self) -> MatchIntelligence:
        keys = [(p.market, p.line, p.outcome) for p in self.probabilities.items]
        if len(keys) != len(set(keys)):
            raise ValueError("one figure per outcome")
        figures = {(p.market, p.line, p.outcome): p.probability for p in self.probabilities.items}
        for s in self.selections.items:
            if isinstance(s.probability, Probability) and s.probability not in figures.values():
                raise ValueError(f"{s.market} {s.selection} {s.line}: a selection carries the outcome's one figure")
        return self


class MatchIntelligencePrivate(MatchIntelligence):
    """C-01, private projection (``GET /api/v1/admin/intelligence/matches/{fixture_id}/intelligence``, require_admin):
    the public one and what only the owner sees."""

    probabilities: ItemList[OutcomeFigurePrivate]  # type: ignore[assignment]  # the private variant of each item
    selections: ItemList[SelectionPrivate]  # type: ignore[assignment]
    packet: PacketRef | Missing = private(description="The match packet the context and the form were read from.")
    brief: Brief | Missing = private(description="The AI's latest brief, unverified words included.")
    chronicle_preview: ReaderChronicle | Missing = private(
        description="The chronicle of this story whether or not readers are shown it (FBI_USER_NARRATIVE).")
    evidence: ItemList[EvidenceRecord] = private(description="The web items of the match, newest first (60 at most).")
