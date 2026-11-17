"""C-03, the private tracking of the selections in the shadow (AD-J04, IA-115).

``GET /api/v1/admin/intelligence/tracking?state=&family=&competition=&from=&to=&cursor=&limit=`` (``require_admin``; no public projection,
``PRIVATE_ONLY``):

* ``counts_by_state`` - the ten states of the cycle (AD-D02), every one present, zero included, over the matches of the period: the
  state machine's own count (``fbi.lifecycle.reader.tracking``);
* ``families`` - per layer and family, the sample the validation board (AD-K02) counts against the sample it needs, the candidates it
  had, the verdict and the mean CLV of the selections it would take;
* ``items`` - the selections of the period, newest move first, with their state, the figure and price of their decision, their
  evaluation step, their result and their CLV (AD-K01), filtered and paged by the server.

Nothing here decides or switches anything; a verdict activates nothing.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    CODE_PATTERN,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    Probability,
    UtcDatetime,
)
from fbi.api.contracts.intelligence.vocab import (
    EvaluationStep,
    LifecycleState,
    PublicState,
    SettlementResult,
    ValidationVerdict,
)

Family = Literal["core", "corners", "cards", "goals_halves"]


class TrackingFixture(IntelligenceModel):
    id: int = Field(ge=1)
    kickoff_at: UtcDatetime
    competition_id: int


class TrackingSelection(IntelligenceModel):
    market: str = Field(pattern=r"^[A-Z0-9_]{1,24}$")
    selection: str = Field(min_length=1)
    line: float
    family: Family
    layer: str = Field(pattern=r"^decision-[a-z0-9.-]{1,30}$")


class TrackingItem(IntelligenceModel):
    """One selection as the cycle holds it, with what its decision and its evaluation say."""

    fixture: TrackingFixture
    selection: TrackingSelection
    state: LifecycleState
    reason: str = Field(pattern=CODE_PATTERN)
    known_at: UtcDatetime
    detected_at: UtcDatetime
    moves: int = Field(ge=1)
    public_state: PublicState | None = Field(description="Null for every chain the shadow wrote: only the owner's authorisation makes "
                                                         "a selection public.")
    probability: Probability | Missing
    price_taken: float | Missing
    evaluation: EvaluationStep | Missing
    outcome: SettlementResult
    clv_pct: float | Missing
    verdict: str | Missing = Field(description="The verdict quality x result of the evaluation after the match (AD-K01).")


class FamilyCounter(IntelligenceModel):
    """The board's count for one layer and family (AD-K02)."""

    layer: str = Field(pattern=r"^decision-[a-z0-9.-]{1,30}$")
    family: Family
    candidates: int = Field(ge=0, description="Every settled selection evaluated in the period.")
    sample: int = Field(ge=0, description="The ones the layer would take that carry a full result, the market's figure and a close.")
    needed: int = Field(ge=1)
    verdict: ValidationVerdict
    clv_pct: float | Missing

    @model_validator(mode="after")
    def _sample_decides(self) -> FamilyCounter:
        if (self.verdict == "INSUFICIENTE") != (self.sample < self.needed):
            raise ValueError(f"{self.verdict} does not agree with a sample of {self.sample} of {self.needed}")
        return self


class StateCounts(IntelligenceModel):
    """How many selections are in each of the ten states of the cycle (AD-D02), zero included."""

    detectado: int = Field(ge=0)
    en_investigacion: int = Field(ge=0)
    en_evaluacion: int = Field(ge=0)
    pendiente_alineaciones: int = Field(ge=0)
    confirmada_sombra: int = Field(ge=0)
    retirada: int = Field(ge=0)
    descartada: int = Field(ge=0)
    en_juego: int = Field(ge=0)
    liquidada: int = Field(ge=0)
    evaluada: int = Field(ge=0)


class Period(IntelligenceModel):
    """The Bogotá days of kick-off the answer covers, both included."""

    date_from: date
    date_to: date
    total: int = Field(ge=0, description="Selections that meet the filters (every page).")


class Filters(IntelligenceModel):
    state: LifecycleState | None
    family: Family | None
    competition: int | None
    limit: int = Field(ge=1, le=200)


class BoardRef(IntelligenceModel):
    """Which board counted the families: its version, its protocol and whether the owner signed it."""

    version: str = Field(pattern=r"^board-v\d+$")
    protocol: str
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    signed_by_owner: bool
    bonferroni_m: int = Field(ge=0)


class Tracking(IntelligenceContract):
    """C-03 (private only)."""

    CONTRACT_ID: ClassVar[str] = "C-03"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    PRIVATE_ONLY: ClassVar[bool] = True

    machine_version: str = Field(pattern=r"^lifecycle-v\d+$")
    writer: str = Field(min_length=3)
    filters: Filters
    counts_by_state: StateCounts | Missing = Field(description="The ten states, zero included; or why there is no count.")
    families: ItemList[FamilyCounter]
    board: BoardRef | Missing
    items: ItemList[TrackingItem]
    period: Period
    next_cursor: int | None = Field(description="The cursor of the next page; null on the last one.")
