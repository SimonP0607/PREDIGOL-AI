"""Settings of the The Odds API connector. Every value has a safe default; the key has none: no key, no connection."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

FREE_PLAN_CREDITS = 500
"""Credits a month of the free plan (the provider's pricing page, read on 9 Nov 2026)."""


class TheOddsApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FBI_THEODDSAPI_", env_file=".env", extra="ignore")

    key: SecretStr | None = Field(default=None)
    """None until the owner opens the account (free, in his name). It is the ONLY thing that turns the connector on."""
    plan: Literal["free"] = "free"
    """Only the free plan exists for this code. A paid plan is a decision of the owner, written here when he takes it."""
    monthly_credit_budget: int = Field(default=int(FREE_PLAN_CREDITS * 0.9), ge=1, le=FREE_PLAN_CREDITS)
    """What the platform lets itself spend in a UTC month: 90 % of the plan, so a miscount never reaches the limit."""
    base_url: str = Field(default="https://api.the-odds-api.com")
    regions: str = Field(default="eu", pattern=r"^(us|us2|uk|eu|au)(,(us|us2|uk|eu|au))*$")
    reference_bookmaker: str = Field(default="pinnacle", min_length=1)
    timeout_seconds: float = Field(default=15.0, gt=0)

    @property
    def enabled(self) -> bool:
        return self.key is not None and bool(self.key.get_secret_value())

    def __repr__(self) -> str:
        return f"TheOddsApiSettings(enabled={self.enabled}, plan={self.plan!r}, regions={self.regions!r})"

    __str__ = __repr__
