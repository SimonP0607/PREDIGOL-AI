from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ON = frozenset({"1", "on", "true", "yes"})


class OddsCaptureSettings(BaseSettings):
    """Capture cadence.

    Derived from the provider's own documented behaviour, not from taste:
      * ``/odds``      is documented as refreshed **every 3 hours** and keeps a **7-day** history.
        That period is a guide, not a guarantee. This file used to say that below 180 minutes
        the same row comes back and only burns quota; production MEASURED otherwise (plan
        Cuotas, 8 Nov 2026, 14 days, 1,578 matches): the provider's last pre-match update came
        a median 103 minutes before kick-off, and in 84 % of the matches AFTER our T-180
        capture. So an ask inside the last three hours does find newer prices.
        The model windows below and their validator are deliberately left as they are: the
        models, the picks and the shadow layer keep reading the same six captures. The newer
        prices reach only the explorer's book, through its own refreshes (``FBI_ODDS_BOOK_REFRESH``,
        ``fbi.odds.book_refresh``), which write nothing those readers see.
      * ``/odds/live`` serves fixtures that are IN PLAY, and keeps no history. MEASURED
        2026-10-01: one unfiltered call returned 11 fixtures, every one of them running
        (elapsed 6 to 93 minutes, status "Second Half"), with in-play markets such as
        "Last Corner". Not one fixture before kick-off. A second unfiltered sample agreed.

        The claim this file used to make - that it publishes between T-15 and T-5 - is
        wrong, and the near-close design rested on it: a window at T-12 asks for a price
        the endpoint has no reason to hold. Two fixtures probed at T-14 and again at T-9
        returned ``results: 0, errors: []`` each time.

        So the closing price, in the sense of the last price before kick-off, is NOT
        available from /odds/live. For the models, the latest pre-match price is the 180
        minute window; /odds itself keeps moving after it (see above), which only the
        explorer's book refreshes read. In-play odds ARE available and are a different
        product: live markets, after the whistle.
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
    odds_book: str = Field(default="0")
    """``FBI_ODDS_BOOK``: whether the worker builds the current-price book (``market.book_current``, plan Cuotas BE-010).
    OFF by default: anything but 1/on/true/yes is off, so a typo can never stop the worker or switch the book on. The book
    asks the provider nothing and writes nothing the models, the picks or the parlay read; the worker needs a restart to
    read it."""

    odds_book_refresh: str = Field(default="0")
    """``FBI_ODDS_BOOK_REFRESH``: whether the worker asks ``/odds`` again for the book between the model windows (plan Cuotas,
    BE-011: ``fbi.odds.book_refresh``). OFF by default, read like ``FBI_ODDS_BOOK``, and it runs only while the book is on too:
    a refresh nobody builds a book from would only spend quota. What it asks goes to RAW and ``market.book_asks``, never to
    anything the models, the picks or the parlay read; the worker needs a restart to read it."""
    odds_book_daily_budget: int = Field(default=8000, ge=0)
    """``FBI_ODDS_BOOK_DAILY_BUDGET``: the most requests the book refreshes may spend in a UTC day. They are counted in the
    shared daily quota (``raw.provider_quota``) like every request, and this budget comes on top of it."""
    odds_book_reserve: int = Field(default=6000, ge=0)
    """``FBI_ODDS_BOOK_RESERVE``: the refreshes stop when fewer requests than this - plus the next 24 h of capture windows - are
    left today, in our budget or in what the provider says remains: they are cut before any other job (the in-play follow stops
    at 3,000, the history and the reference feeds at the next 24 h of windows)."""

    @property
    def book_enabled(self) -> bool:
        return self.odds_book.strip().lower() in ON

    @property
    def book_refresh_enabled(self) -> bool:
        """The book refreshes run: ``FBI_ODDS_BOOK_REFRESH`` AND ``FBI_ODDS_BOOK`` on. The freshness rule
        (``fbi.odds.freshness``) expects their points only then."""
        return self.book_enabled and self.odds_book_refresh.strip().lower() in ON

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
