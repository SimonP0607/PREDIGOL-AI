"""HTTP client of The Odds API: one call, its credits counted before and after, and the key never in a log line.

The provider takes the key ONLY as the ``apiKey`` query parameter, so the URL is a secret here: no URL is ever logged, and a transport
error is re-raised without the exception that carries it. A call costs ``markets x regions`` credits (the provider's guide); an answer
with no events costs nothing (``x-requests-last`` says 0). The client keeps the month's spending in a ``CreditStore`` and refuses the call
that would pass the budget; it also refuses when the provider's own ``x-requests-remaining`` is below the cost of the call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog

from fbi.core.clock import now
from fbi.core.errors import ConfigError, ProviderError, QuotaExhaustedError, RateLimitError
from fbi.providers.the_odds_api.parse import H2H, SharpEvent, parse_events
from fbi.providers.the_odds_api.settings import TheOddsApiSettings

log = structlog.get_logger(__name__)

SPORT_KEY = re.compile(r"^soccer_[a-z0-9_]+$")


class CreditStore(Protocol):
    """Where the credits spent in a UTC month are kept. The default forgets them with the process; a persistent store (one row per month) is
    what a scheduled job would pass in, and is left to the job that wires this connector (nothing does yet)."""

    def spent(self, month: str) -> int: ...

    def add(self, month: str, credits: int) -> None: ...


class MemoryCreditStore:
    def __init__(self) -> None:
        self._by_month: dict[str, int] = {}

    def spent(self, month: str) -> int:
        return self._by_month.get(month, 0)

    def add(self, month: str, credits: int) -> None:
        self._by_month[month] = self._by_month.get(month, 0) + credits


@dataclass(frozen=True, slots=True)
class OddsAnswer:
    events: list[SharpEvent]
    credits_charged: int
    """What the provider says this call cost (``x-requests-last``); the planned cost when it does not say."""
    remaining: int | None
    used: int | None


def _int(headers: httpx.Headers, name: str) -> int | None:
    try:
        return int(headers[name])
    except (KeyError, ValueError):
        return None


class TheOddsApiClient:
    def __init__(self, settings: TheOddsApiSettings, *, store: CreditStore | None = None, http: httpx.AsyncClient | None = None) -> None:
        if not settings.enabled:
            raise ConfigError("The Odds API is not configured: FBI_THEODDSAPI_KEY is empty, so no request is ever made")
        self._settings = settings
        self._store = store if store is not None else MemoryCreditStore()
        self._http = http if http is not None else httpx.AsyncClient(base_url=settings.base_url, timeout=settings.timeout_seconds)
        self._owns_http = http is None
        self._remaining: int | None = None

    @property
    def cost_of_a_call(self) -> int:
        """One market (``h2h``) times the number of regions asked for."""
        return len(self._settings.regions.split(","))

    def _month(self) -> str:
        return now().strftime("%Y-%m")

    def credits_left_in_budget(self) -> int:
        return max(0, self._settings.monthly_credit_budget - self._store.spent(self._month()))

    async def fetch_h2h(self, sport_key: str) -> OddsAnswer:
        if not SPORT_KEY.match(sport_key):
            raise ProviderError(f"not a football sport key: {sport_key!r}")
        cost = self.cost_of_a_call
        if cost > self.credits_left_in_budget():
            raise QuotaExhaustedError(f"The Odds API: the month's budget of {self._settings.monthly_credit_budget} credits would be passed")
        if self._remaining is not None and self._remaining < cost:
            raise QuotaExhaustedError("The Odds API: the provider reports fewer credits left than this call costs")
        assert self._settings.key is not None  # `enabled` was checked at construction
        params = {"apiKey": self._settings.key.get_secret_value(), "regions": self._settings.regions, "markets": H2H,
                  "oddsFormat": "decimal", "dateFormat": "iso"}
        try:
            response = await self._http.get(f"/v4/sports/{sport_key}/odds/", params=params)
        except httpx.HTTPError as exc:
            # Not `raise ... from exc`: the exception's text holds the URL, and the URL holds the key.
            raise ProviderError(f"The Odds API: transport error ({type(exc).__name__})") from None
        if response.status_code == 429:
            raise RateLimitError("The Odds API: rate limited (429)")
        if response.status_code in (401, 403):
            raise ProviderError(f"The Odds API: the key was refused ({response.status_code})")
        if response.status_code != 200:
            raise ProviderError(f"The Odds API: HTTP {response.status_code}")
        charged = _int(response.headers, "x-requests-last")
        charged = cost if charged is None else charged
        self._store.add(self._month(), charged)
        self._remaining = _int(response.headers, "x-requests-remaining")
        try:
            body = response.json()
        except ValueError:
            raise ProviderError("The Odds API: the answer is not JSON") from None
        events = parse_events(body, sport_key=sport_key)
        log.info("the_odds_api.fetched", sport=sport_key, events=len(events), credits=charged, remaining=self._remaining)
        return OddsAnswer(events, charged, self._remaining, _int(response.headers, "x-requests-used"))

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()
