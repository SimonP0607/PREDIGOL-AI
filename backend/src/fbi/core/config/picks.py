from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

INTELLIGENCE = "intelligence"
LEGACY = "legacy"


class PicksSourceSettings(BaseSettings):
    """Where the Picks page takes its decision from (plan PICKS, F3, decision 1: one source, PrediGol Intelligence)."""

    model_config = SettingsConfigDict(env_prefix="FBI_", env_file=".env", extra="ignore")

    picks_source: str = Field(default=LEGACY)
    """``FBI_PICKS_SOURCE``: ``intelligence`` makes the Picks board read the newest ``decision-v1`` row of each selection - its
    calibrated probability, EV and edge and its state - instead of the pick engine's own raw numbers. OFF by default: anything
    but ``intelligence`` is the legacy path, so a typo can never switch it on. It can only take a card AWAY from a reader (a
    reader is shown a pick when the legacy rules AND Intelligence both say RECOMMENDED); it changes no decision, model, threshold
    or settlement, and the owner's preview shows every card either way. Read at each request, like ``FBI_AI_MODE``."""

    @property
    def from_intelligence(self) -> bool:
        return self.picks_source.strip().lower() == INTELLIGENCE
