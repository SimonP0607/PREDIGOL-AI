"""The automatic parlay builder's answer (REVIEW PREDIGOL, point 15): the parlay PrediGol builds for the user's filters
with the rule of its own parlays, each leg with the numbers that justify it - or no parlay, and why.

Nothing is stored: the user decides whether to save it (``POST /me/parlays``, the same check as any parlay of theirs).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.product import CompetitionBadge, Source, TeamBadge
from fbi.api.contracts.records import ItemAi

BuildReason = Literal["no_candidates", "risk_cap", "not_reviewed", "no_match", "too_few_legs", "total_odds_cap",
                      "no_growth"]


class BuilderLeg(Contract):
    pick_id: int
    fixture_id: int
    kickoff_at: datetime
    competition: CompetitionBadge
    home: TeamBadge
    away: TeamBadge
    market_key: str
    selection: str
    line: Decimal
    odds: Decimal = Field(description="The best price available now.")
    bookmaker: str | None
    price_at: datetime
    n_bookmakers: int = Field(description="Books quoting the selection now (a leg needs three or more).")
    p_model: Decimal = Field(description="PrediGol's probability, conditional on the bet settling.")
    p_low: Decimal = Field(description="The pessimistic end of the model's interval: what the legs are chosen by.")
    p_high: Decimal | None
    p_market: Decimal = Field(description="The market's de-vigged consensus.")
    fair_odds: Decimal = Field(description="1 / p_market.")
    edge: Decimal = Field(description="p_model - p_market.")
    price_edge: Decimal = Field(description="odds x p_market - 1: how far the price is above (or below) the fair one.")
    ev: Decimal = Field(description="Expected value per unit at the current price.")
    growth: Decimal = Field(description="Expected log growth of a 1% stake on this leg alone, at p_low.")
    ai: ItemAi | None = Field(default=None, description="The AI's newest review: the decision only where the "
                                                        "reader may see it (the owner's preview, or enforced).")


class BuilderFunnel(Contract):
    passing: int = Field(description="Selections of the window through the value gate at the current price.")
    risk: int = Field(description="Of those, through the risk stage (no price above max_odds).")
    reviewed: int = Field(description="Of those, through PrediGol Intelligence (reviewed; its vetoes only when "
                                      "enforced).")
    matching: int = Field(description="Matching the filters.")
    combinable: int = Field(description="Also three books or more, an interval no wider than 40 points, no quarter "
                                        "line.")
    matches: int = Field(description="Distinct matches among the combinable ones.")
    max_odds: Decimal | None = Field(default=None, description="The risk stage's cap on a selection's price.")


class BuilderFilters(Contract):
    hours: int
    min_legs: int
    max_legs: int
    markets: list[str]
    competition_ids: list[int]
    min_odds: Decimal | None
    max_odds: Decimal | None
    max_total_odds: Decimal | None


class BuilderOption(Contract):
    competition: CompetitionBadge
    selections: int = Field(description="Selections of that competition that passed the rules in the window.")


class BuiltParlay(Contract):
    status: Literal["ok", "no_valid_parlay"]
    reason: BuildReason | None
    source: Source
    rule_version: str = Field(description="The builder's version on top of the parlays' own rule.")
    parlay_rule: str
    filters: BuilderFilters
    legs: list[BuilderLeg]
    combined_odds: Decimal | None
    p_all_low: Decimal | None = Field(description="Every leg wins, at the pessimistic probabilities, corrected for "
                                                  "significant negative dependence.")
    p_all_market: Decimal | None = Field(description="Every leg wins by the market's fair probabilities.")
    expected_log_growth: Decimal | None = Field(description="Of a 1% stake on the whole parlay, at p_low.")
    risk: Literal["moderate", "high", "very_high"] | None
    correlated_pairs: int
    funnel: BuilderFunnel
    competitions: list[BuilderOption] = Field(description="Competitions with selections that passed the rules in "
                                                          "the window: what the filter can offer.")
    markets: list[str] = Field(description="Markets with selections that passed the rules in the window.")
    prices_as_of: datetime | None = Field(description="The oldest price among the legs.")
    generated_at: datetime
