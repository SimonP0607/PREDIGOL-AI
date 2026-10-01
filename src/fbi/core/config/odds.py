from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class OddsCaptureSettings(BaseSettings):
    """Capture cadence.

    Derived from the provider's own documented behaviour, not from taste:
      * ``/odds``      is refreshed **every 3 hours** and keeps a **7-day** history.
        Polling it more often than every 180 minutes returns the same row and burns quota.
      * ``/odds/live`` serves fixtures that are IN PLAY, and keeps no history. MEASURED
        2026-10-01: one unfiltered call returned 11 fixtures, every one of them running
        (elapsed 6 to 93 minutes, status "Second Half"), with in-play markets such as
        "Last Corner". Not one fixture before kick-off. A second unfiltered sample agreed.

        The claim this file used to make - that it publishes between T-15 and T-5 - is
        wrong, and the near-close design rested on it: a window at T-12 asks for a price
        the endpoint has no reason to hold. Two fixtures probed at T-14 and again at T-9
        returned ``results: 0, errors: []`` each time.

        So the closing price, in the sense of the last price before kick-off, is NOT
        available from this provider. The latest obtainable pre-match price is the 180
        minute window, because /odds refreshes every three hours. In-play odds ARE
        available and are a different product: live markets, after the whistle.
    """

    model_config = SettingsConfigDict(env_prefix="FBI_", env_file=".env", extra="ignore")

    odds_prematch_windows: str = Field(default="4320,2880,1440,720,360,180")
    odds_nearclose_window: int = Field(default=12, ge=5, le=15)
    odds_capture_near_close: bool = Field(default=False)
    """Whether to plan a near-close capture before kick-off. OFF, from measurement.

    /odds/live was measured to serve only fixtures in play (see the class docstring), so a
    task planned at T-12 spends one request and returns results: 0 - every time, for every
    fixture that reaches kick-off. The capture path itself works and is kept; what is
    switched off is asking for a price the provider does not have yet.

    Turning this on makes sense only once ``odds_nearclose_window`` is re-grounded on a
    window where the endpoint actually holds prices, which for in-play odds means after
    kick-off rather than before it - a different feature, and a decision about what the
    platform is for rather than a cadence setting."""
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
