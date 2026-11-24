"""C-02, the selection's contract (AD-J03, IA-114): why, against, what it depends on, how it settles, its versions, the sources it
used, its market's validation, its state in the cycle and its price with the price's age.

Two projections of ONE answer, built by the server (``fbi.api.services.selection_intelligence``):

* PUBLIC - ``GET /api/v1/picks/{pick_id}/explanation`` keeps its shape and gains an optional ``intelligence`` field: this contract,
  only while ``FBI_MATCH_INTELLIGENCE`` is on AND the selection is public (``public_state``: the owner authorised it - published, in
  play or settled). A selection under evaluation never reaches it; with the switch off the field does not travel at all.
* PRIVATE - ``GET /api/v1/admin/intelligence/decisions/{decision_id}`` keeps every key it had and gains ``intelligence``: this
  contract's private projection (``require_admin``), with the decision layer's word, the cycle's state and reason, the model's own
  figure ``sin_calibrar``, the market's validation from the board (AD-K02) and the evaluation after the match (AD-K01).

Every number comes from what was stored; nothing is recomputed here but the rounding of a percentage (``Probability.of``). No price range,
no promise of profit: the expected value is the decision's own, with the interval its probability gave.

1.1.0 (C-02 1.1, plan de correcciones UX/UI, AP-K05, AP-K06) - two optional fields for readers, absent from an answer of 1.0.0:
``reader_reason`` - the reason of the selection in the reader's two languages (``text_es``, ``text_en``), and ``highlight`` - the fact
or figure that explains it most, with its ``source`` and ``as_of``. Written by the server from what the decision stored, never by a
model: no model's name, no raw probability (0.473 - only whole percentages and odds), no rumour (only confirmed or probable facts, or
the decision's own figures). The guard is in the models themselves (``reader_text_problems``): a text that breaks it does not validate.
"""

from __future__ import annotations

import re
from typing import ClassVar, Final, Literal

from pydantic import Field, field_validator, model_validator

from fbi.api.contracts.intelligence.base import (
    CODE_PATTERN,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    MarketValidation,
    Missing,
    Probability,
    Source,
    UtcDatetime,
    _absent,
    private,
)
from fbi.api.contracts.intelligence.vocab import (
    LifecycleState,
    MarketState,
    PublicState,
    SettlementResult,
)

PriceState = Literal["vigente", "antiguo", "sin_precio"]
"""The state of a price (``fbi.decision.price_age.PRICE_STATES``; a test holds the two equal)."""

PRICE_RULES: Final[dict[str, dict[str, object]]] = {
    "price-age-v1": {"limits_min": (180,), "final_min": 30,
                     "final_checkpoints": ("T-15m", "T-60m", "T-90m", "lineups")},
    "price-age-v2": {"limits_min": (195, 75, 45), "final_min": None, "final_checkpoints": ()},
}
"""The two rules of the price's age as data (``fbi.decision.price_age.V1`` / ``V2``; ``tests/unit/test_selection_contract.py`` holds
them equal to the code): decision-v1 judges with v1 - 3 h, and 30 min at its final checkpoints -, decision-v2.1 with v2 - 195, 75 and
45 min by horizon. The web receives the thresholds; it never fixes them."""


class SelectionRef(IntelligenceModel):
    """Which selection: its match, market, side and line, and how it reads in Spanish (a template of the code, never a model's text)."""

    fixture_id: int = Field(ge=1)
    market: str = Field(pattern=r"^[A-Z0-9_]{1,24}$")
    selection: str = Field(min_length=1)
    line: float
    family: Literal["core", "corners", "cards", "goals_halves"]
    label_es: str | Missing


class Reason(IntelligenceModel):
    """One line of «Por qué» or «En contra»: a code and its template over the stored numbers."""

    code: str = Field(pattern=CODE_PATTERN)
    text_es: str = Field(min_length=1)
    cites: list[int] = Field(default_factory=list, description="Ids of the sources (``sources``) this line leans on.")


class Dependency(IntelligenceModel):
    """One line of «De qué depende»."""

    code: str = Field(pattern=CODE_PATTERN)
    text_es: str = Field(min_length=1)


class SettlementRuleView(IntelligenceModel):
    """«Cómo se liquida»: the rule that settles the market and what it counts."""

    rule: str = Field(min_length=1)
    text_es: str = Field(min_length=1)


class Band(IntelligenceModel):
    """A range in percentage points (the expected value's can be negative)."""

    low: float
    high: float

    @model_validator(mode="after")
    def _ordered(self) -> Band:
        if self.low > self.high:
            raise ValueError("a band's low is above its high")
        return self


class ExpectedValue(IntelligenceModel):
    """The decision's expected value at its price, in percent, with the range its probability's interval gives."""

    pct: float
    interval_pct: Band | Missing


class PriceView(IntelligenceModel):
    """The price the decision read and its age when it decided, judged by the rule of its layer."""

    best_odds: float = Field(gt=1)
    books: int | Missing
    seen_at: UtcDatetime | Missing
    age_minutes: float | Missing
    price_state: PriceState | Missing
    price_rule: Literal["price-age-v1", "price-age-v2"]
    thresholds_min: list[int] = Field(description="The rule's limits in minutes, nearest kick-off last (45/75/195 for v2).")


class Version(IntelligenceModel):
    """One version of the selection (each decision of its layer, oldest first; none is rewritten)."""

    at: UtcDatetime
    checkpoint: str = Field(min_length=1)
    state: str = Field(min_length=1, description="The layer's own word (decision-v1: RECHAZADO ... PICK_PREMIUM).")
    probability_pct: float = Field(ge=0, le=100)
    best_odds: float | Missing
    change_es: str = Field(min_length=1)


class SourceUsed(IntelligenceModel):
    """A source the decision cited: what kind of fact, where it was read and when PrediGol knew it. No third-party text."""

    id: int
    kind: str = Field(min_length=1)
    source: Source
    known_at: UtcDatetime


class MarketStatusRef(IntelligenceModel):
    """Where the market stands (AD-E01)."""

    market_key: str = Field(min_length=1)
    state: MarketState
    reason: str = Field(pattern=CODE_PATTERN)


class EvaluationSummary(IntelligenceModel):
    """The evaluation after the match (AD-K01, ``eval-sel-v1``)."""

    version: str = Field(pattern=r"^eval-sel-v\d+$")
    result: SettlementResult
    clv_pct: float | Missing
    verdict: Literal["MERECIDO", "SUERTE", "VARIANZA", "ERROR", "NULO", "SIN_DATOS"]
    evidence_held: int = Field(ge=0)
    evidence_contradicted: int = Field(ge=0)
    evidence_unevaluable: int = Field(ge=0)
    lineup_changed: bool | Missing
    notice_es: Literal["Un acierto no valida el mercado."] = "Un acierto no valida el mercado."


RAW_PROBABILITY: Final = re.compile(r"(?<![\d,.])0[.,]\d{2,}(?!\s*%)")
"""A probability written as a fraction (0.473, 0,47): a reader is only ever shown whole percentages and odds."""
MODEL_WORDS: Final = re.compile(r"(?i)\b(dixon|coles|poisson|elo|hgb|xgboost|lightgbm|logit|bivariate|shin|"
                                r"(decision|forecast|scenarios|parlay|ai-gate|player-engine)-v\d+(\.\d+)?|sin_calibrar)\b")
"""The names of the models, methods and versions behind a figure: they stay in the private projection and the console."""
RUMOUR_WORDS: Final = re.compile(r"(?i)\b(rumor|rumores|rumour|rumours|se rumorea|rumoured|rumored|según rumores)\b")


def reader_text_problems(text: str) -> list[str]:
    """Why a reader's text of C-02 1.1 cannot be served (empty: it can)."""
    found = []
    if RAW_PROBABILITY.search(text):
        found.append("a raw probability")
    if MODEL_WORDS.search(text):
        found.append("the name of a model or method")
    if RUMOUR_WORDS.search(text):
        found.append("a rumour")
    return found


class ReaderText(IntelligenceModel):
    """A text for readers in their two languages (C-02 1.1)."""

    text_es: str = Field(min_length=1, max_length=400)
    text_en: str = Field(min_length=1, max_length=400)

    @field_validator("text_es", "text_en")
    @classmethod
    def _for_readers(cls, value: str) -> str:
        if problems := reader_text_problems(value):
            raise ValueError(f"not a reader's text: {', '.join(problems)}")
        return value


class Highlight(ReaderText):
    """The fact or figure that explains the selection most (C-02 1.1, AP-K06), with where it was read and as of when."""

    source: Source
    as_of: UtcDatetime


class SelectionIntelligence(IntelligenceContract):
    """C-02, public projection: a selection the owner published (or in play, or settled)."""

    CONTRACT_ID: ClassVar[str] = "C-02"
    CONTRACT_VERSION: ClassVar[str] = "1.1.0"

    selection: SelectionRef
    public_state: PublicState
    probability: Probability | Missing = Field(description="The figure the decision judged, with its seal.")
    fair_odds: float | Missing = Field(description="1 / the probability, rounded to two decimals by the server.")
    expected_value: ExpectedValue | Missing
    price: PriceView | Missing
    reasons_for: ItemList[Reason] = Field(description="«Por qué».")
    reasons_against: ItemList[Reason] = Field(description="«En contra».")
    depends_on: ItemList[Dependency] = Field(description="«De qué depende».")
    settlement_rule: SettlementRuleView | Missing = Field(description="«Cómo se liquida».")
    versions: ItemList[Version]
    sources: ItemList[SourceUsed]
    market_status: MarketStatusRef | Missing
    reader_reason: ReaderText | Missing | None = Field(
        default=None, exclude_if=_absent,
        description="1.1.0: the reason in the reader's two languages; absent from an answer of 1.0.0, sin_datos when the decision "
                    "stored nothing to say it with.")
    highlight: Highlight | Missing | None = Field(
        default=None, exclude_if=_absent,
        description="1.1.0: the fact or figure that explains the selection most, with its source and as_of; absent from 1.0.0.")


class SelectionIntelligencePrivate(SelectionIntelligence):
    """C-02, private projection: the public one and what only the owner sees, for any selection of the decision layers."""

    public_state: PublicState | None = Field(  # type: ignore[assignment]
        description="publicada / en_juego / liquidada once the owner authorised it; null: private.")
    decision_id: int = private(description="The decision of ``intel.decisions`` this answer is about.")
    layer: str = private(description="decision-v1 or decision-fam-v1.")
    decision_state: str = private(description="The layer's own word for this decision.")
    lifecycle_state: LifecycleState | Missing = private(description="The state in the cycle (AD-D02).")
    lifecycle_reason: str | Missing = private(description="Its reason in the cycle's closed list.")
    raw_probability: Probability | Missing = private(description="The model's own number, sin_calibrar.")
    lineup_dependency: Missing = private(description="Players and points of the line-up it depends on (AD-D03).")
    validation: MarketValidation | Missing = private(description="Its market's verdict on the board (AD-K02) with its sample.")
    validation_cell: str | Missing = private(description="The board's cell: layer|family|market.")
    evaluation: EvaluationSummary | Missing = private(description="The evaluation after the match (AD-K01).")

