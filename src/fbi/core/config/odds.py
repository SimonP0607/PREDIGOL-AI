from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OddsCaptureSettings(BaseSettings):
    """Capture cadence.

    Derived from the provider's own documented behaviour, not from taste:
      * ``/odds``      is refreshed **every 3 hours** and keeps a **7-day** history.
        Polling it more often than every 180 minutes returns the same row and burns quota.
      * ``/odds/live`` publishes a fixture between T-15 and T-5 minutes and keeps no history.
        It is the only way to observe a price close to kick-off.
    """

    model_config = SettingsConfigDict(env_prefix="FBI_", env_file=".env", extra="ignore")

    odds_prematch_windows: str = Field(default="4320,2880,1440,720,360,180")
    odds_nearclose_window: int = Field(default=12, ge=5, le=15)
    odds_window_tolerance: int = Field(default=45, ge=1)
    odds_markets: str = Field(default="")  # empty = capture every market the provider returns

    @field_validator("odds_prematch_windows")
    @classmethod
    def _spaced_enough(cls, v: str) -> str:
        mins = sorted({int(x) for x in v.split(",") if x.strip()}, reverse=True)
        if not mins:
            raise ValueError("at least one prematch window is required")
        if min(mins) < 180:
            raise ValueError(
                "a prematch window below 180 minutes is pointless: /odds refreshes every 3 hours. "
                "Use the near-close window (/odds/live) instead."
            )
        return v

    @property
    def prematch_windows(self) -> list[int]:
        return sorted({int(x) for x in self.odds_prematch_windows.split(",") if x.strip()}, reverse=True)

    @property
    def market_filter(self) -> set[str]:
        return {m.strip() for m in self.odds_markets.split(",") if m.strip()}
