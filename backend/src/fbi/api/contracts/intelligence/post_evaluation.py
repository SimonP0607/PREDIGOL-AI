"""C-08, the evaluation after the match (AD-J07, IA-133): per selection, the six questions of Doc 1 §Aprendizaje.

``GET /api/v1/admin/intelligence/evaluations/{fixture_id}`` (``require_admin``; no public projection, ``PRIVATE_ONLY``). It reads the
ONE evaluation of every settled selection of the match (AD-K01, ``eval-sel-v1``, ``intel.selection_evaluations``) and answers, for each:

1. ``anticipated`` - what we anticipated: the probability judged with its seal, the market's at the same moment, the price and the
   decision's state;
2. ``happened`` - what happened: the result of the settlement of record and, for a full result, log loss and Brier of both;
3. ``price`` - whether it was a good price: the value against the close (``clv-v1``), its quality and the verdict quality x result;
4. ``evidence`` - which facts it cited were held, contradicted or could not be judged;
5. ``lineup`` - whether the official line-up changed anything, and how the estimate of the starters did;
6. ``scenario`` - whether the scenario came true: absent with its reason until the scenario engine keeps a reading by selection
   (AD-B02).

Beside them, the accumulated calibration of each cell of the match's selections on the validation board (AD-K02, the last 30 days) with
its sample against the sample it needs, and the fixed notice «Un acierto no valida el mercado.». Nothing here is presented as
validated: a market's verdict is the board's, with its sample, and below it the verdict is INSUFICIENTE.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    CODE_PATTERN,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    MarketValidation,
    Missing,
    Probability,
    UtcDatetime,
)
from fbi.api.contracts.intelligence.match import MatchInfo
from fbi.api.contracts.intelligence.tracking import BoardRef
from fbi.api.contracts.intelligence.vocab import LifecycleState, SettlementResult, ValidationVerdict

Notice = Literal["Un acierto no valida el mercado."]
NOTICE: Notice = "Un acierto no valida el mercado."
PriceQuality = Literal["GOOD", "NEUTRAL", "BAD", "UNKNOWN"]
"""``clv-v1``'s quality of the price: above +1 %, below -1 %, in between, or no close."""
PostVerdict = Literal["MERECIDO", "SUERTE", "VARIANZA", "ERROR", "NULO", "SIN_DATOS"]
"""Quality x result (``fbi.evaluation.selection.verdict_of``): a win with a BAD price is SUERTE, never value."""
FactStatus = Literal["sostenido", "contradicho", "no_evaluable"]
Parity = Literal["igual", "difiere", "sin_referencia"]
Family = Literal["core", "corners", "cards", "goals_halves"]


class PostMatchAnticipated(IntelligenceModel):
    """1 · What we anticipated: the decision that stood (its last word at least 10 minutes before kick-off)."""

    probability: Probability = Field(description="The probability judged, with its seal (calibrada or sin_calibrar).")
    market_pct: float | Missing = Field(description="The market's de-vigged probability at the same moment, in percent.")
    odds: float | Missing
    expected_value_pct: float | Missing = Field(description="odds x probability - 1 at that moment, in percent.")
    decision_state: str = Field(min_length=1, description="The layer's own word.")
    checkpoint: str = Field(min_length=1)
    decided_at: UtcDatetime
    cycle_state: LifecycleState | Missing = Field(description="Where the standing decision left it in the cycle (lifecycle-map-v1).")
    cycle_reason: str | Missing
    taken: bool = Field(description="The layer would take it (confirmed in the shadow): the population the board judges.")


class PostMatchScores(IntelligenceModel):
    log_loss: float = Field(ge=0)
    brier: float = Field(ge=0, le=1)
    market_log_loss: float | Missing
    market_brier: float | Missing


class PostMatchHappened(IntelligenceModel):
    """2 · What happened."""

    result: SettlementResult
    settled_by: str = Field(min_length=1, description="intel.decision_outcomes, or settle-v4 on the regulation score.")
    settled_at: UtcDatetime
    hit: bool | None = Field(description="True a full win, false a full loss; null for what a probability of a full win cannot be "
                                         "scored against (a half, a push, a void).")
    scores: PostMatchScores | Missing = Field(description="Only for a full result.")


class PostMatchPrice(IntelligenceModel):
    """3 · Whether it was a good price."""

    clv_pct: float | Missing = Field(description="clv-v1: odds x the closing fair probability - 1, in percent.")
    close_pct: float | Missing = Field(description="The closing fair probability, in percent.")
    close_minutes_to_ko: int | Missing
    quality: PriceQuality
    verdict: PostVerdict


class PostMatchFact(IntelligenceModel):
    """One fact the decision cited and how it stood (``eval-evidence-v1``): its kind and claim as codes, never a third party's words."""

    id: int
    kind: str = Field(min_length=1)
    claim: str | Missing
    status: FactStatus
    why: str = Field(pattern=CODE_PATTERN)


class PostMatchEvidence(IntelligenceModel):
    """4 · Which evidence held and which failed."""

    rules: str = Field(pattern=r"^eval-evidence-v\d+$")
    held: int = Field(ge=0)
    contradicted: int = Field(ge=0)
    unevaluable: int = Field(ge=0)
    facts: ItemList[PostMatchFact]


class PostMatchEstimate(IntelligenceModel):
    hits: int = Field(ge=0, description="Estimated starters who started (AD-D04).")
    of: int = Field(ge=0)
    share_pct: float | Missing


class PostMatchLineup(IntelligenceModel):
    """5 · Whether the official line-up changed anything (``eval-lineup-v1``)."""

    rules: str = Field(pattern=r"^eval-lineup-v\d+$")
    changed: bool | Missing = Field(description="The decision before the official line-up against the one that stood.")
    why: str = Field(pattern=CODE_PATTERN, description="comparada, or why it could not be compared.")
    official_at: UtcDatetime | Missing
    probability_change_pp: float | Missing
    state_before: str | Missing
    estimate: PostMatchEstimate | Missing


class PostMatchScenario(IntelligenceModel):
    """6 · Whether the scenario came true (the scenario engine, AD-B02, keeps no reading by selection yet)."""

    scenario: str = Field(pattern=CODE_PATTERN)
    fulfilled: bool
    engine: str = Field(min_length=1)


class PostMatchSelection(IntelligenceModel):
    """One selection of the match and its six answers."""

    layer: str = Field(pattern=r"^decision-[a-z0-9.-]{1,30}$")
    decision_source: Literal["intel.decisions", "intel.decisions_v2"]
    decision_id: int
    family: Family
    market: str = Field(pattern=r"^[A-Z0-9_]{1,40}$")
    selection: str = Field(min_length=1)
    line: float
    anticipated: PostMatchAnticipated
    happened: PostMatchHappened
    price: PostMatchPrice
    evidence: PostMatchEvidence
    lineup: PostMatchLineup
    scenario: PostMatchScenario | Missing
    validation: MarketValidation | Missing = Field(description="Its market's verdict on the board (AD-K02) with its sample.")
    validation_cell: str = Field(description="layer|family|market.")
    parity: Parity = Field(description="Against intel.decision_outcomes: the result and clv-v1 re-derived.")
    evaluated_at: UtcDatetime
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    notice_es: Notice = NOTICE


class PostMatchBin(IntelligenceModel):
    pred_pct: float = Field(ge=0, le=100)
    observed_pct: float = Field(ge=0, le=100)
    n: int = Field(ge=1)


class PostMatchCalibration(IntelligenceModel):
    """The accumulated calibration of one cell of the board (the selections its layer would take, last 30 days)."""

    cell: str = Field(description="layer|family|market (* for the family as a whole).")
    sample: int = Field(ge=0, description="Selections with a full result, the market's figure and a close.")
    needed: int = Field(ge=1)
    ece: float | Missing
    ece_max: float
    bins: list[PostMatchBin]
    clv_mean_pct: float | Missing
    verdict: ValidationVerdict

    @model_validator(mode="after")
    def _sample_decides(self) -> PostMatchCalibration:
        if (self.verdict == "INSUFICIENTE") != (self.sample < self.needed):
            raise ValueError(f"{self.verdict} does not agree with a sample of {self.sample} of {self.needed}")
        return self


class PostMatchEvaluation(IntelligenceContract):
    """C-08 (private only)."""

    CONTRACT_ID: ClassVar[str] = "C-08"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    PRIVATE_ONLY: ClassVar[bool] = True

    match: MatchInfo
    version: str = Field(pattern=r"^eval-sel-v\d+$")
    selections: ItemList[PostMatchSelection]
    calibration: ItemList[PostMatchCalibration] = Field(description="The cells of the match's selections, accumulated.")
    board: BoardRef | Missing
    notice_es: Notice = NOTICE
