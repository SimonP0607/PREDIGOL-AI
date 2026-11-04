"""Postpartido (plan UX, B4): what a finished match did to what the reader saved and to PrediGol's published picks.

The knowledge of the match (``fbi.api.contracts.knowledge``: the result, the statistics, the story of the score, the market from its opening
to its close) is its own answer and does not change. This one adds the two things a reader asks once the match is over: how what I saved
ended, and why each pick PrediGol published won, lost, was returned or voided. The why is the match's own facts - a man sent off, a penalty,
an early goal, the chances each side made - as the post-mortem found them (pm-v6, ``fbi.intel.postmortem``), given as codes and figures that the
web words with its own templates. What the post-mortem JUDGES - its verdict, the class of a loss, the price against the close, what the AI's
review decided - stays the owner's and has no field here.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.records import UserPick

CauseCode = Literal["red_card", "penalty_scored", "penalty_missed", "early_goal", "early_substitution", "cards_above_referee",
                    "cards_below_referee", "xg_supported", "xg_against"]
"""The facts of a match the post-mortem looks for (``fbi.intel.postmortem.causes_of``): what a pre-match model could not see."""
CauseEffect = Literal["for", "against", "neutral"]
PickResult = Literal["pending", "win", "loss", "push", "void", "half_win", "half_loss"]


class PostmatchCause(Contract):
    """One fact of the match behind a pick's result, as figures: the web says it in the reader's language."""

    code: CauseCode
    effect: CauseEffect = Field(description="Whether the fact played for the selection, against it, or neither.")
    minute: int | None = Field(default=None, description="When it happened (a card, a penalty, the first goal).")
    side: Literal["home", "away"] | None = Field(default=None, description="The team it was about.")
    n: int | None = Field(default=None, description="early_substitution: how many changes before minute 30.")
    cards: int | None = Field(default=None, description="cards_*: the cards of the match.")
    referee_avg: float | None = Field(default=None, description="cards_*: the referee's average cards per match.")
    xg_home: float | None = Field(default=None, description="xg_*: the home side's expected goals.")
    xg_away: float | None = None
    score: str | None = Field(default=None, description="xg_*: the score the expected goals are set against.")


class PostmatchPick(Contract):
    """A pick PrediGol published for the match, how it ended and why (the owner's preview adds the shadow ones, as EVALUATION)."""

    pick_id: int
    market_key: str
    selection: str
    line: Decimal
    status: Literal["shadow", "qualified", "published"] = Field(description="What it was before kick-off.")
    result: PickResult | None = Field(description="The settlement; null until the match has one.")
    p_model: Decimal = Field(description="PrediGol's probability when it was published.")
    p_close: Decimal | None = Field(description="The market's fair probability at its close (null: no close was kept).")
    analysed: bool = Field(description="The post-mortem has looked at it and its result is the settlement's (written the "
                                       "night after the match; a result corrected since waits for a new one).")
    analysed_at: datetime | None = None
    causes: list[PostmatchCause] = Field(default_factory=list, description=(
        "The facts of the match behind the result, the most telling first; empty when nothing out of the ordinary happened or "
        "before the post-mortem."))


class PostMatch(Contract):
    version: str
    fixture_id: int
    kickoff_at: datetime
    finished: bool = Field(description="The match is over (a match waiting for its result says false, and nothing is settled).")
    saved: list[UserPick] = Field(description="What this reader saved on the match, with its result and units once settled.")
    published: list[PostmatchPick] = Field(description="PrediGol's published picks of the match, how each ended and why.")
