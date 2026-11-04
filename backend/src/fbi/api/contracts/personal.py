"""What a reader's own use orders and suggests (plan UX, B2; section 38): the markets they consult most first in a match's
«Mercados», and one league or team to follow, with its reason. Visible rules, never a model; never a pick, a probability, a
state or a price - those are the same for every reader."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract

MarketKey = Literal["1X2", "OU", "BTTS", "AH", "DC"]


class MarketViews(Contract):
    market: MarketKey
    views: int = Field(description="Times the reader consulted it in the window: opened its bookmakers or all its lines, "
                                   "or chose one of its prices.")


class MarketOrder(Contract):
    first: list[MarketKey] = Field(description="The reader's markets, most consulted first; the page puts the rest after "
                                               "them in the usual order. Empty: the usual order.")
    views: list[MarketViews] = Field(description="Why: each of the reader's markets and how many times they consulted it "
                                                 "(also while they keep the usual order).")
    common: bool = Field(description="The reader keeps the usual order (and can go back to theirs).")
    window_days: int
    min_views: int = Field(description="A market moves first once consulted this many times in the window.")


class Suggestion(Contract):
    kind: Literal["league", "team"]
    id: int
    name: str
    matches: int = Field(description="Different matches of it the reader opened in the window, outside what they follow.")
    days: int


class PersonalView(Contract):
    personalization: bool = Field(description="FBI_PERSONALIZATION: false gives every reader the common view - the usual "
                                              "order and no suggestion.")
    counted: bool = Field(description="Whether the reader's use is counted now (the product's analytics on and, where "
                                      "asked, their consent): without it, the usual order and no suggestion.")
    markets: MarketOrder
    suggestion: Suggestion | None = Field(description="One league or team the reader keeps opening and does not follow: "
                                                      "added only when they confirm it; dismissed, it never comes back.")


class SuggestionOut(BaseModel):
    """«No, gracias»: this league or team is never suggested again."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["league", "team"]
    id: int = Field(ge=1, le=2**62)


class MarketOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    common: bool = Field(description="True: the usual order; false: the reader's own again.")
