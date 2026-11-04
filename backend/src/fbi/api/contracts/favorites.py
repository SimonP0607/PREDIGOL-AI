"""A reader's favourite leagues and teams, the welcome and the hints (plan UX, A13): what the page reads and sends. The
favourites order and filter what a reader is shown; they never change a pick, a probability, a state or a price."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.product import CompetitionBadge, TeamBadge

WelcomeStep = Literal["football", "about"]
Hint = Literal["picks", "match", "parlay", "my_picks"]


class FavoritesView(Contract):
    leagues: list[CompetitionBadge] = Field(description="The leagues the reader follows, in the order chosen.")
    teams: list[TeamBadge]
    suggested: bool = Field(description="True while the reader has chosen none: these are the ones suggested for Colombia, "
                                        "labelled as suggested.")
    max_leagues: int
    max_teams: int
    personalization: bool = Field(description="FBI_PERSONALIZATION: false gives every reader the common view (Home "
                                              "without «Hoy en tus ligas»).")


class FavoritesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leagues: list[int] = Field(default_factory=list, max_length=50)
    teams: list[int] = Field(default_factory=list, max_length=50)


class FavoriteOptions(Contract):
    leagues: list[CompetitionBadge] = Field(description="Every league PrediGol follows, by country and name.")
    teams: list[TeamBadge] = Field(description="Teams of those leagues whose name matches the search (two letters or more; "
                                               "without accents or case), at most 20.")


class OnboardingState(Contract):
    welcome_due: bool
    welcome_steps: list[WelcomeStep] = Field(description="football: the favourites; about: «Qué es PrediGol» - only for a "
                                                         "new account (an existing one sees the favourites alone).")
    onboarded_at: datetime | None
    hints_seen: list[str]


class HintIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hint: Hint
