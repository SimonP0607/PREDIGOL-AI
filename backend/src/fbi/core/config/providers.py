from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Limites publicados por API-Football (documentacion v3, verificada 2026-09).
PLAN_LIMITS: dict[str, tuple[int, int]] = {
    # plan: (requests/min, requests/day)
    "free": (10, 100),
    "pro": (300, 7_500),
    "ultra": (450, 75_000),
    "mega": (900, 150_000),
    "custom": (1200, 1_500_000),
}


class ApiFootballSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FBI_APIFOOTBALL_", env_file=".env", extra="ignore"
    )

    key: str = Field(...)
    base_url: str = Field(default="https://v3.football.api-sports.io")
    plan: str = Field(default="pro")
    daily_budget: int = Field(default=3_000, ge=1)
    max_concurrency: int = Field(default=4, ge=1, le=16)
    timeout_seconds: float = Field(default=20.0, gt=0)
    max_retries: int = Field(default=3, ge=0, le=8)
    circuit_failure_threshold: int = Field(default=5, ge=1)
    circuit_reset_seconds: float = Field(default=60.0, gt=0)

    @field_validator("plan")
    @classmethod
    def _known_plan(cls, v: str) -> str:
        if v not in PLAN_LIMITS:
            raise ValueError(f"unknown plan {v!r}; expected one of {sorted(PLAN_LIMITS)}")
        return v

    @property
    def per_minute_limit(self) -> int:
        return PLAN_LIMITS[self.plan][0]

    @property
    def per_day_limit(self) -> int:
        return PLAN_LIMITS[self.plan][1]

    @property
    def masked_key(self) -> str:
        return f"...{self.key[-4:]}" if len(self.key) >= 4 else "***"

    def __repr__(self) -> str:
        return f"ApiFootballSettings(key='{self.masked_key}', plan='{self.plan}')"

    __str__ = __repr__
