from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from fbi.core.config.providers import PLAN_LIMITS
from fbi.providers.lanes import LaneMode, lane_mode


class ProviderPlanSettings(BaseSettings):
    """The plan and our budget - WITHOUT the key.

    The product API reports quota and budget but never calls the provider, so
    it has no reason to hold the credential. Reading these two values through
    ApiFootballSettings would make the key a required variable of a process
    that must not need it.
    """

    model_config = SettingsConfigDict(env_prefix="FBI_APIFOOTBALL_", env_file=".env", extra="ignore")

    plan: str = Field(default="pro")
    daily_budget: int = Field(default=3_000, ge=1)
    lanes: str = Field(default="off")
    """``FBI_APIFOOTBALL_LANES`` (plan PM, PM-04-01): off (default: the behaviour before the lanes) | measure | enforce."""
    lane_ceilings: str = Field(default="")
    """``FBI_APIFOOTBALL_LANE_CEILINGS``: ``lane=N`` pairs over the table of ``fbi.providers.lanes`` (empty = the table)."""

    @field_validator("plan")
    @classmethod
    def _known_plan(cls, v: str) -> str:
        if v not in PLAN_LIMITS:
            raise ValueError(f"unknown plan {v!r}; expected one of {sorted(PLAN_LIMITS)}")
        return v

    @property
    def lanes_mode(self) -> LaneMode:
        """The lanes switch, read leniently: a word it does not know is ``off``, never a worker that does not start."""
        return lane_mode(self.lanes)

    @property
    def per_day_limit(self) -> int:
        return PLAN_LIMITS[self.plan][1]

    @property
    def effective_budget(self) -> int:
        """Our cap, never reported above what the plan allows."""
        return min(self.daily_budget, self.per_day_limit)
