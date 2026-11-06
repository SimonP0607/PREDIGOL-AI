"""A reader's favourite leagues, teams, players and markets, the welcome and the hints (plan UX, A13 and 3.1): what the page
reads and sends. The favourites order and filter what a reader is shown; they never change a pick, a probability, a state
or a price."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.personal import MarketKey
from fbi.api.contracts.product import CompetitionBadge, TeamBadge

WelcomeStep = Literal["football", "about"]
Hint = Literal["picks", "match", "parlay", "my_picks"]


class PlayerBadge(Contract):
    id: int = Field(description="core.players id (the one the line-ups and the player's page carry).")
    name: str
    position: str | None
    team: str | None = Field(description="The club or national team of the player's latest line-up in a league PrediGol "
                                         "follows, to tell two players of one name apart; None when unknown.")


class FavoritesView(Contract):
    leagues: list[CompetitionBadge] = Field(description="The leagues the reader follows, in the order chosen.")
    teams: list[TeamBadge]
    players: list[PlayerBadge] = Field(description="The players the reader follows, in the order chosen (3.1).")
    markets: list[MarketKey] = Field(description="The markets the reader follows, in the order chosen (3.1).")
    suggested: bool = Field(description="True while the reader has chosen none: these are the ones suggested for Colombia, "
                                        "labelled as suggested.")
    max_leagues: int
    max_teams: int
    max_players: int
    max_markets: int
    personalization: bool = Field(description="FBI_PERSONALIZATION: false gives every reader the common view (Home "
                                              "without «Hoy en tus ligas»).")


class FavoritesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leagues: list[int] = Field(default_factory=list, max_length=50)
    teams: list[int] = Field(default_factory=list, max_length=50)
    players: list[int] | None = Field(default=None, max_length=50, description="Left out: the players the reader follows "
                                      "stay (a page from before 3.1 never clears them); [] clears them.")
    markets: list[MarketKey] | None = Field(default=None, max_length=10, description="Left out: the markets the reader "
                                            "follows stay; [] clears them.")


class FavoriteOptions(Contract):
    leagues: list[CompetitionBadge] = Field(description="Every league PrediGol follows, by country and name.")
    teams: list[TeamBadge] = Field(description="Teams of those leagues whose name matches the search (two letters or more; "
                                               "without accents or case), at most 20.")
    players: list[PlayerBadge] = Field(default_factory=list, description="Players who appeared in a line-up of those "
                                       "leagues whose name matches the search (three letters or more; without accents or "
                                       "case), at most 20.")


class OnboardingState(Contract):
    welcome_due: bool
    welcome_steps: list[WelcomeStep] = Field(description="football: the favourites; about: «Qué es PrediGol» - only for a "
                                                         "new account (an existing one sees the favourites alone).")
    onboarded_at: datetime | None
    hints_seen: list[str]


class HintIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hint: Hint
