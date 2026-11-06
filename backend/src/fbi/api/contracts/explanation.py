"""«¿Por qué PrediGol eligió este pick?» (plan UX, B3; section 28 of the plan): one pick in five folding layers - the conclusion,
the context and data, the market, the risks and how picks are decided. Every line is a template over these values or a fact of
the match's structured reading (A9) - or the validated narrative of that same reading (A11) - never prose written here."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract, StatusReason, UserStatus
from fbi.api.contracts.reading import ReadingFact, ReadingNarrative
from fbi.api.contracts.records import MatchRef


class ExplanationMarket(Contract):
    """Layer 3: PrediGol's probability against the market's, the price it was published at and the best price now."""

    p_model: Decimal = Field(description="PrediGol's probability of the selection (calibrated), conditional on the bet being "
                                         "settled. The web words «falla aproximadamente n de cada 10 veces» from it.")
    p_low: Decimal | None = Field(description="The low end of the model's interval (its doubt), when it gave one.")
    p_high: Decimal | None = None
    p_market: Decimal | None = Field(description="The market's probability without its margin (Shin): now, or when the pick "
                                                 "was taken once its match started. None without a market price.")
    published_odds: Decimal = Field(description="The price it was published at: the day's set's frozen price for a pick of "
                                                "the day, the price the pick was taken at otherwise.")
    published_bookmaker: str | None
    published_at: datetime
    odds_now: Decimal | None = Field(description="The best price available now; None once the match started or without a "
                                                 "current price.")
    bookmaker_now: str | None
    price_at: datetime | None = Field(description="When the best price now was captured.")
    value_now: bool | None = Field(description="Whether it passes the value rule at the best price now; None once the match "
                                               "started.")


class ExplanationDay(Contract):
    """The pick in PrediGol's set of the day: it passed every step of «Cómo se decide», and this is how it stood then."""

    day: date
    rank: int
    stage: Literal["T-24h", "T-12h", "T-6h", "T-3h"]
    selected_at: datetime
    odds: Decimal = Field(description="The price frozen when it entered the set.")
    bookmaker: str | None
    user_status: UserStatus = Field(description="Its state when it entered the set (fbi/picks/user_status.py).")
    status_reason: StatusReason
    context_pending: bool


class ExplanationReview(Contract):
    """Only while the AI's review is applied to picks: what that review said of this selection."""

    decision: Literal["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"]
    positives: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class PickExplanation(Contract):
    pick_id: int
    version: str = Field(description="The rules that chose what each layer says: pick-explanation-v1.")
    match: MatchRef
    market_key: str
    selection: str
    line: Decimal
    started: bool = Field(description="Its match kicked off: the numbers are the ones it was taken with, never re-priced.")
    user_status: UserStatus = Field(description="Its state now (fbi/picks/user_status.py): at the best price now and, while the "
                                                "AI's review is applied, with the review's newest decision; once the match "
                                                "started, as it was taken.")
    status_reason: StatusReason
    context_pending: bool
    day: ExplanationDay | None = Field(description="Set when it is one of PrediGol's picks of the day.")
    reading_shown: bool = Field(description="False while readers do not see the structured reading (FBI_READING_USERS=0): "
                                            "layers 2 and 4 then have only the pick's own lines.")
    reading_complete: bool = Field(description="False: PrediGol has not gathered this match's context yet.")
    reading_at: datetime | None = Field(description="The moment of the data the context and the risks come from.")
    context: list[ReadingFact] = Field(description="Layer 2: the facts of the reading's context and data, each with its "
                                                   "reference, in the reading's order.")
    narrative: ReadingNarrative | None = Field(description=(
        "The validated chronicle of that same match (A11, UX-025): its lead, a paragraph for each side, the head-to-head "
        "and the risks. The web shows it instead of the facts when a reader may see it. Null otherwise."))
    market: ExplanationMarket
    risks: list[ReadingFact] = Field(description="Layer 4, besides the pick's own lines: the reading's risks (never empty "
                                                 "while the reading is shown).")
    review: ExplanationReview | None = Field(description="Only while the AI's review is applied: its decision and claims on "
                                                         "this selection.")
