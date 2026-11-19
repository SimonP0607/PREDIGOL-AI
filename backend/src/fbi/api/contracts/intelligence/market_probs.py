"""C-14, the probabilities by market of a match (plan EA, pieces EA-002 and EA-201): the three marks, never mixed without a label.

For every market of the match with a price in force (the same markets, keys and selections as ``/matches/{id}/markets/catalog``) and
every selection and line:

* ``model`` ▮ - PrediGol's probability, sealed (``Probability``). The public projection carries it ONLY for a market the catalogue
  (IA-070) holds ``evaluable`` and from the published forecast (``forecast-v1``); every other market says why not (owner's decision
  D-EA-2, 18-nov-2026). The private projection adds ``model_shadow``: the figure of the model still in calibration, labelled.
* ``implied`` │ - the consensus without margin of the houses whose price is in force (proportional per house, mean over houses), with
  how many houses and since when.
* ``history`` ● - how often the selection would have won in the last ``window`` matches of the home side at home and of the away side
  away (a market of one side: that side's only), counted with the settlement rule of IA-070, with its Wilson interval.

``parlay`` says whether Mi parlay accepts the selection and, if not, why. The per-team trends matrix travels with C-13 (the same
documents). Routes: ``GET /api/v1/matches/{fixture_id}/market-probs`` (404 while ``FBI_MARKET_PROBS`` is off) and its private
``GET /api/v1/admin/intelligence/matches/{fixture_id}/market-probs``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    Probability,
    UtcDatetime,
    private,
)
from fbi.api.contracts.intelligence.stats_profile import Ref
from fbi.api.contracts.intelligence.vocab import MarketState

ParlayReason = Literal["ok", "interruptor_apagado", "sin_regla", "no_ofrecer", "menos_de_3_casas", "linea_de_cuarto",
                       "empezado", "sin_cobertura"]
"""Why Mi parlay would not take a selection; ``ok`` when it would."""
HistoryWindow = Literal["u10_contexto"]


class Implied(IntelligenceModel):
    value: float = Field(ge=0, le=1)
    pct: int = Field(ge=0, le=100)
    books: int = Field(ge=1)
    as_of: UtcDatetime = Field(description="The newest price among the houses it averages.")
    method: Literal["proporcional_media_casas"] = "proporcional_media_casas"


class HistoryMark(IntelligenceModel):
    hits: int = Field(ge=0)
    n: int = Field(ge=1)
    pct: int = Field(ge=0, le=100)
    wilson_low: int = Field(ge=0, le=100)
    wilson_high: int = Field(ge=0, le=100)
    window: HistoryWindow
    rule_key: str = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> HistoryMark:
        if self.hits > self.n or not self.wilson_low <= self.pct <= self.wilson_high:
            raise ValueError("hits within n and pct inside its Wilson interval")
        return self


class ParlayFlag(IntelligenceModel):
    allowed: bool
    reason: ParlayReason

    @model_validator(mode="after")
    def _agree(self) -> ParlayFlag:
        if self.allowed != (self.reason == "ok"):
            raise ValueError("a selection is allowed exactly when its reason is ok")
        return self


class DistBin(IntelligenceModel):
    """One count of a total (``k``; the last one is «k or more»), its probability under the model."""

    k: int = Field(ge=0)
    or_more: bool
    p: float = Field(ge=0, le=1)


class SelectionMarks(IntelligenceModel):
    selection: str = Field(min_length=1)
    line: float
    best_odds: float = Field(gt=1)
    bookmaker: str = Field(min_length=1)
    model: Probability | Missing
    implied: Implied | Missing
    history: HistoryMark | Missing
    parlay: ParlayFlag


class SelectionMarksPrivate(SelectionMarks):
    model_shadow: Probability | Missing = private(description="The figure of the model still in calibration (family-v1 ...), "
                                                              "for the owner's evaluation only.")


class MarketMarks(IntelligenceModel):
    key: str = Field(min_length=1, description="The market's stable key in the catalogue of prices: code.period.subject.")
    unit: str = Field(min_length=1, description="The catalogue's key (IA-070): 1X2, OU, CORNERS_OU, bet_<id>.")
    category: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    period: str
    subject: str
    state: MarketState
    state_reason: str = Field(min_length=1)
    rule_key: str | Missing
    model_origin: str | Missing = Field(description="What would compute the model's figure: forecast-v1, family-v1 ...")
    distribution: list[DistBin] | Missing = Field(description="The model's distribution of the total, when it gives one and the "
                                                              "figure is published.")
    selections: list[SelectionMarks] = Field(min_length=1)

    @model_validator(mode="after")
    def _model_only_when_evaluable(self) -> MarketMarks:
        if self.state != "evaluable" and any(not isinstance(s.model, Missing) for s in self.selections):
            raise ValueError(f"{self.unit} is {self.state}: no model figure reaches a reader")
        return self


class MarketMarksPrivate(MarketMarks):
    selections: list[SelectionMarksPrivate] = Field(min_length=1)  # type: ignore[assignment]
    distribution_shadow: list[DistBin] | Missing = private(description="The distribution of the model in calibration.")


class MarketProbs(IntelligenceContract):
    CONTRACT_ID: ClassVar[str] = "C-14"
    CONTRACT_VERSION: ClassVar[str] = "1.1.0"

    fixture_id: int
    kickoff_at: UtcDatetime
    home: Ref
    away: Ref
    catalog_version: str = Field(min_length=1)
    markets: ItemList[MarketMarks]


class MarketProbsPrivate(MarketProbs):
    markets: ItemList[MarketMarksPrivate]  # type: ignore[assignment]
