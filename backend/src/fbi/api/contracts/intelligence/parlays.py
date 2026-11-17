"""C-04, the parlays with their state (AD-J05, IA-132): the state of the set, its evaluation and how it is built.

Two projections of ONE answer, built by the server (``fbi.api.services.parlay_states``):

* PUBLIC - ``GET /api/v1/parlays/{kind}`` keeps its shape and gains an optional ``state`` field: this contract, only while
  ``FBI_MATCH_INTELLIGENCE`` is on and only for what a reader is shown (the product's parlay, ``parlay-v5`` built from the
  qualified picks; never the owner's preview, never ``parlay-v6``). With the switch off the field does not travel at all.
* PRIVATE - ``GET /api/v1/admin/intelligence/parlays?kind=&from=&to=`` (``require_admin``): the parlays ``parlay-v6`` kept in the
  shadow (AD-E06, ``intel.parlays_v6``) with their legs, the joint probability by simulation and its pessimistic end, the margin
  the books keep accumulated over the legs, the result read from the legs' settlements, the days without a parlay and why, the
  calibration of the joint with its sample - beside the product's parlay of today and the history of ``parlay-v5`` by state.

«Ninguno si nada cumple» is a STATE of the set (``status: "ninguno"`` with ``NINGUNO_CUMPLE``), never a padded parlay. The rule
of each parlay travels inside it (``rule``: the legs it may hold, how many of one match, how its joint is computed): the web
receives the thresholds, it never fixes them. No promise of profit: a parlay's expected value is the rule's own number, and the
seal of its joint is ``sin_calibrar`` (no calibrator exists for a joint).
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar, Final, Literal

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
from fbi.api.contracts.intelligence.vocab import AbstentionCode, SettlementResult

ParlayKindCode = Literal["daily", "multiday"]
ParlaySetStatus = Literal["armado", "en_juego", "liquidado", "ninguno"]
"""The state of the set: built and waiting for its first match, a match of it under way, every leg settled, or no parlay
because nothing met the rule."""
ParlaySetResult = Literal["pendiente", "ganado", "perdido", "nulo", "parcial_nulo"]
"""A parlay's result from its legs: any leg lost -> perdido; every leg won -> ganado; some void and the rest won -> parcial_nulo
(it pays the product of the others); all void -> nulo; otherwise pendiente."""
JointMethod = Literal["producto", "simulacion_copula"]
"""How the joint is computed: ``parlay-v5`` multiplies the legs' probabilities (distinct matches of distinct teams);
``parlay-v6`` simulates a Gaussian copula with ``corr-v2``'s dependence (a dependence never raises it)."""
V6NoneDetail = Literal["sin_candidatos", "un_solo_candidato", "ninguna_combinacion_cumple"]
"""Why ``parlay-v6`` built nothing (``fbi.tracking.parlay_v6.NoneReason``; a test holds the two equal)."""
ParlaySource = Literal["en_vivo", "intel.parlays_v6"]
"""Where a card was read: the product's parlay computed now (``parlay-v5``), or the shadow's kept row (``parlay-v6``)."""

RULES: Final[dict[str, dict[str, object]]] = {
    "parlay-v6": {"min_legs": 2, "max_legs": 3, "max_per_match": 2, "min_books": 3, "joint": "simulacion_copula"},
}
"""``parlay-v6``'s thresholds as data (``fbi.tracking.parlay_v6``: ``MIN_LEGS``, ``MAX_LEGS``, ``MAX_PER_MATCH``, ``MIN_BOOKS``;
``tests/unit/test_parlay_states_contract.py`` holds them equal to the code). Decision 6 of the owner (16-nov-2026): at most three
legs, none when nothing meets. ``parlay-v5``'s come from its engine with each answer (``required_legs``, ``max_legs``)."""
V6_MAX_LEGS: Final = 3


class ParlaySetRule(IntelligenceModel):
    """How the parlay is built: the rule's version and its thresholds."""

    version: str = Field(pattern=r"^parlay-v\d+(\.\d+)?$")
    min_legs: int = Field(ge=2)
    max_legs: int = Field(ge=2, description="The most legs the rule lets in (3 for parlay-v6, decision 6 of the owner).")
    max_per_match: int = Field(ge=1, description="Legs of one match at most (parlay-v5: one; parlay-v6: two, with their dependence).")
    joint: JointMethod
    none_when_nothing_meets: Literal[True] = Field(
        default=True, description="Always true: when nothing meets the rule the state is «ninguno», never a padded parlay.")

    @model_validator(mode="after")
    def _ordered(self) -> ParlaySetRule:
        if self.min_legs > self.max_legs:
            raise ValueError("a rule's min_legs is above its max_legs")
        if self.version.startswith("parlay-v6") and self.max_legs > V6_MAX_LEGS:
            raise ValueError(f"parlay-v6 holds at most {V6_MAX_LEGS} legs")
        return self


class ParlaySetLeg(IntelligenceModel):
    """One leg as its parlay took it, and its result (``settle-v4``)."""

    fixture_id: int = Field(ge=1)
    kickoff_at: UtcDatetime
    market: str = Field(pattern=r"^[A-Z0-9_]{1,24}$")
    selection: str = Field(min_length=1)
    line: float
    odds: float = Field(gt=1)
    result: SettlementResult


class ParlaySetLegPrivate(ParlaySetLeg):
    """The same leg with the numbers it was chosen on (owner only)."""

    ref: str = private(min_length=1, description="The chain of the cycle the leg was confirmed in (parlay-v6) or its pick (parlay-v5).")
    probability_pct: float | Missing = private(description="The probability it was judged on, in percent (one decimal).")
    probability_low_pct: float | Missing = private(description="Its pessimistic end, in percent (one decimal).")
    market_pct: float | Missing = private(description="The market's de-vigged probability, in percent (one decimal).")


class ParlaySetCard(IntelligenceModel):
    """One parlay (or one day without one) with the state of the set."""

    kind: ParlayKindCode
    status: ParlaySetStatus
    result: ParlaySetResult | Missing = Field(description="The set's result; absent (sin_datos) when there is no parlay.")
    none_reason: AbstentionCode | None = Field(description="NINGUNO_CUMPLE exactly when status is ninguno; null otherwise.")
    rule: ParlaySetRule
    window_from: UtcDatetime
    window_to: UtcDatetime
    built_at: UtcDatetime = Field(description="When the rule built it (or found nothing).")
    legs: ItemList[ParlaySetLeg]
    combined_odds: float | Missing
    joint: Probability | Missing = Field(description="P(every leg wins), sealed sin_calibrar: no calibrator exists for a joint.")
    fair_odds: float | Missing = Field(description="1 / the joint, rounded to two decimals by the server.")
    accumulated_margin_pct: float | Missing = Field(
        description="What the books keep on average over the legs (1 - combined odds x the market's joint), in percent: it grows with "
                    "every leg.")
    expected_value_pct: float | Missing = Field(description="The rule's own expected value per unit, in percent. Not a promise.")

    @model_validator(mode="after")
    def _state_fits(self) -> ParlaySetCard:
        none = self.status == "ninguno"
        if none != (self.none_reason is not None):
            raise ValueError("none_reason is given exactly when the status is ninguno")
        if self.none_reason is not None and self.none_reason != "NINGUNO_CUMPLE":
            raise ValueError("a parlay that is not built says NINGUNO_CUMPLE")
        if none and (self.legs.items or not isinstance(self.result, Missing)):
            raise ValueError("«ninguno» has no legs and no result")
        if not none:
            n = len(self.legs.items)
            if not self.rule.min_legs <= n <= self.rule.max_legs:
                raise ValueError(f"{n} legs outside the rule's {self.rule.min_legs}-{self.rule.max_legs}")
            if isinstance(self.result, Missing):
                raise ValueError("a built parlay carries its result (pendiente until it settles)")
            if (self.status == "liquidado") != (self.result != "pendiente"):
                raise ValueError(f"status {self.status} does not agree with result {self.result}")
        if self.window_from >= self.window_to:
            raise ValueError("a window ends after it starts")
        return self


class ParlaySetRefusal(IntelligenceModel):
    """How many selections of the window one rule of the leg left out (``fbi.tracking.parlay_v6.refusal``'s codes)."""

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    count: int = Field(ge=1)


class ParlaySetCardPrivate(ParlaySetCard):
    """The same parlay as the owner sees it: where it was read, whether a reader is shown it, why nothing met, and the joint's
    pessimistic end, Monte Carlo error and market twin."""

    legs: ItemList[ParlaySetLegPrivate]  # type: ignore[assignment]
    published: bool = private(description="True only for what a reader is shown (the product's parlay); parlay-v6 is never published.")
    source: ParlaySource = private(description="Where it was read.")
    stored_id: int | Missing = private(description="Its row of intel.parlays_v6.")
    day: date = private(description="Its product day (America/Bogota).")
    candidates: int | Missing = private(description="The selections that met the leg rule in its window.")
    none_detail: V6NoneDetail | Missing = private(description="Why parlay-v6 built nothing.")
    refused: list[ParlaySetRefusal] = private(description="Selections left out, by the rule they failed (counts only).")
    joint_low: Probability | Missing = private(description="The joint at the legs' pessimistic ends (what chose the legs).")
    joint_se: float | Missing = private(description="The Monte Carlo error of the joint.")
    product_of_legs: float | Missing = private(description="The legs' probabilities multiplied (the joint parlay-v5 would give).")
    market_joint_pct: float | Missing = private(description="The market's joint from the same draws, in percent.")
    expected_value_low_pct: float | Missing = private(description="The expected value at the pessimistic joint, in percent.")
    payout_factor: float | Missing = private(description="What a stake of 1 returned (0 when lost) once it settled.")

    def shown_in_public(self) -> bool:
        return self.published


class ParlaySetState(IntelligenceContract):
    """C-04, public projection: the product's parlay of a kind with the state of its set (only while FBI_MATCH_INTELLIGENCE is on)."""

    CONTRACT_ID: ClassVar[str] = "C-04"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    parlays: ItemList[ParlaySetCard]


class ParlaySetPeriod(IntelligenceModel):
    date_from: date
    date_to: date
    kind: ParlayKindCode | None


class ParlaySetCalibration(IntelligenceModel):
    """The joint against the results of parlay-v6's settled parlays (WON or LOST; one with a void leg is left out)."""

    settled: int = Field(ge=0)
    won: int = Field(ge=0)
    expected_wins: float | Missing = Field(description="The sum of their joints.")
    expected_wins_low: float | Missing
    brier: float | Missing
    needed: int = Field(ge=1, description="The calibration is not judged with fewer settled parlays.")


class ParlaySetV5Count(IntelligenceModel):
    """parlay-v5's kept history (``picks.parlays``), by kind, source and state: still read, never rewritten."""

    kind: ParlayKindCode
    source: Literal["qualified", "evaluation"]
    status: Literal["BUILDING", "READY", "ACTIVE", "WON", "LOST", "VOID", "PARTIAL_VOID"]
    parlays: int = Field(ge=1)


class ParlaySetStatePrivate(ParlaySetState):
    """C-04, private projection: the shadow's parlay-v6 over a period beside the product's parlay and parlay-v5's history."""

    parlays: ItemList[ParlaySetCardPrivate]  # type: ignore[assignment]
    period: ParlaySetPeriod = private(description="The product days read, both included.")
    calibration: ParlaySetCalibration | Missing = private(description="parlay-v6's joint against its results, with its sample.")
    v5_history: ItemList[ParlaySetV5Count] = private(description="parlay-v5's parlays of the period by state (picks.parlays).")
