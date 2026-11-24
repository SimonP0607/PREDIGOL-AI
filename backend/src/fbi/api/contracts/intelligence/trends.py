"""C-18, the builder «Por tendencias» (plan de correcciones UX/UI, AP-L02): the contract and its example ONLY. No route serves it and no
builder fills it: ``FBI_TREND_BUILDER`` stays off. It is written now so that the web can build against it; nothing here is a pick, and
nothing changes a pick, a probability or a model.

* ``candidates`` - selections of upcoming matches by trend: each one says its trend with its sample («7 de los últimos 10»: ``hits`` of
  ``sample``), the frequency and its Wilson 95 % interval, and the settlement rule that would settle it. Only markets with a settlement
  rule AND data in that league (corners, cards, shots, halves...): a market without either is never a candidate (``allowed_markets`` and,
  in the private projection, ``discarded`` with the reason).
* ``slip`` - the reader's combination: at most ``max_legs`` (3) legs and a combined price at most ``max_combined_odds``; the server refuses
  a fourth leg or a price above the cap (``within_limits``).
* ``label`` - always ``tendencia_no_pick``: «Análisis de tendencias · no es un pick oficial».

The value of the cap of the combined price is not fixed here (an owner's question): it travels as data in ``max_combined_odds``.
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

MAX_LEGS: Final = 3
LABEL_ES: Final = "Análisis de tendencias · no es un pick oficial"
LABEL_EN: Final = "Trend analysis · not an official pick"
DiscardReason = Literal["sin_regla_de_liquidacion", "sin_datos_en_la_liga", "muestra_insuficiente"]


class Frequency(IntelligenceModel):
    """How often the trend held: ``hits`` of the last ``sample`` matches, in percent, with its Wilson 95 % interval."""

    hits: int = Field(ge=0)
    sample: int = Field(ge=1)
    pct: float = Field(ge=0, le=100)
    low_pct: float = Field(ge=0, le=100)
    high_pct: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _coherent(self) -> Frequency:
        if self.hits > self.sample:
            raise ValueError(f"{self.hits} hits of {self.sample}")
        if abs(self.pct - round(100 * self.hits / self.sample, 1)) > 0.05:
            raise ValueError(f"pct {self.pct} is not {self.hits} of {self.sample}")
        if not self.low_pct <= self.pct <= self.high_pct:
            raise ValueError("the interval does not contain the frequency")
        return self


class TrendLeg(IntelligenceModel):
    """One selection by trend: its match, its market and its trend with the sample."""

    fixture_id: int = Field(ge=1)
    kickoff_at: UtcDatetime
    market: str = Field(pattern=r"^[A-Z0-9_]{1,24}$")
    selection: str = Field(min_length=1)
    line: float | Missing
    label_es: str = Field(min_length=1)
    label_en: str = Field(min_length=1)
    trend_es: str = Field(min_length=1, description="«7 de los últimos 10».")
    trend_en: str = Field(min_length=1, description="«7 of the last 10».")
    frequency: Frequency
    settlement_rule: str = Field(min_length=1, description="The rule that would settle it (settle-v4, corners_ft@v1...).")
    best_odds: float | Missing


class DiscardedLeg(IntelligenceModel):
    fixture_id: int = Field(ge=1)
    market: str = Field(pattern=r"^[A-Z0-9_]{1,24}$")
    reason: DiscardReason


class TrendSlip(IntelligenceModel):
    """The reader's combination of trend legs."""

    legs: list[TrendLeg] = Field(max_length=MAX_LEGS)
    combined_odds: float | Missing
    within_limits: bool

    @model_validator(mode="after")
    def _one_match_once(self) -> TrendSlip:
        keys = [(x.fixture_id, x.market) for x in self.legs]
        if len(keys) != len(set(keys)):
            raise ValueError("a market of a match enters a slip once")
        return self


class Trends(IntelligenceContract):
    """C-18, public projection."""

    CONTRACT_ID: ClassVar[str] = "C-18"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    label: Literal["tendencia_no_pick"] = "tendencia_no_pick"
    label_es: Literal["Análisis de tendencias · no es un pick oficial"] = LABEL_ES
    label_en: Literal["Trend analysis · not an official pick"] = LABEL_EN
    max_legs: Literal[3] = MAX_LEGS
    max_combined_odds: float = Field(gt=1, description="The cap of the combined price (a value the owner fixes).")
    allowed_markets: list[str] = Field(description="The markets with a settlement rule and data in the league of the candidates.")
    candidates: ItemList[TrendLeg]
    slip: TrendSlip | Missing

    @model_validator(mode="after")
    def _limits(self) -> Trends:
        markets = set(self.allowed_markets)
        for leg in self.candidates.items + ([] if isinstance(self.slip, Missing) else self.slip.legs):
            if leg.market not in markets:
                raise ValueError(f"{leg.market} is not an allowed market")
        if not isinstance(self.slip, Missing):
            over = not isinstance(self.slip.combined_odds, Missing) and self.slip.combined_odds > self.max_combined_odds
            if self.slip.within_limits == over:
                raise ValueError("within_limits must say whether the combined price is under the cap")
        return self


class TrendsPrivate(Trends):
    """C-18, private projection: what was left out and why."""

    discarded: ItemList[DiscardedLeg] = private(description="Selections that are never candidates: no rule, no data, or a small sample.")
    min_sample: int = private(ge=1, description="The fewest matches a trend is read on.")

