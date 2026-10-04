"""Where prices can come from: the interface a price source implements, and every source we
evaluated, with its access and cost as researched on 3-4 Oct 2026.

The pick engine reads ``market.odds_snapshots`` and never a provider, so a second price
source plugs in here - an ``OddsProvider`` plus a fixture identity map - without touching
picks, settlement or the backtest. Adding one is still an owner decision: every source below
that costs money or needs an account is marked so, and ``enabled_sources`` refuses to return
one that is not ACTIVE. Nothing in this module makes a request.

Full analysis: docs/research/ODDS_PROVIDER_GAP_ANALYSIS_2026.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fbi.providers.base import OddsParseLog, OddsQuote, RawResponse


@runtime_checkable
class OddsProvider(Protocol):
    """A live source of pre-match prices for fixtures we already know.

    ``provider_fixture_id`` is the API-Football id: a second source must first map its own
    event ids onto our fixtures (same teams, kick-off within two hours), store the mapping,
    and refuse a price it cannot map - a price on the wrong match is worse than none.
    Quotes carry their own capture instant and payload hash, exactly as API-Football's do."""

    name: str

    async def fetch_prematch_odds(
        self, *, provider_fixture_id: int, kickoff_at: datetime, parse_log: OddsParseLog | None = None,
    ) -> tuple[list[OddsQuote], list[RawResponse]]: ...


class Access(StrEnum):
    ACTIVE = "ACTIVE"
    """In use today."""
    FREE_NEEDS_OWNER = "FREE_NEEDS_OWNER"
    """No cost, but needs the owner to accept terms or open an account (we never do)."""
    PAYMENT_REQUIRED = "PAYMENT_REQUIRED"
    """Requires payment - not contracted."""
    CLOSED = "CLOSED"
    """Not available to us at any price."""
    REJECTED = "REJECTED"
    """Available, but excluded on terms or law."""


class Kind(StrEnum):
    LIVE_API = "LIVE_API"
    HISTORICAL_FILES = "HISTORICAL_FILES"


@dataclass(frozen=True, slots=True)
class OddsSourceProfile:
    key: str
    name: str
    kind: Kind
    access: Access
    bookmakers: str
    colombian_books: tuple[str, ...]
    closing_line: str
    cost: str
    decision: str
    sources: tuple[str, ...] = ()


ODDS_SOURCES: tuple[OddsSourceProfile, ...] = (
    OddsSourceProfile(
        "api_football", "API-Football (Ultra)", Kind.LIVE_API, Access.ACTIVE,
        "33 listed; 9 price our matches (1xBet, Marathonbet, Betfair, Bet365, Betano, BetVictor, Pinnacle, "
        "William Hill, SBO); 24 never seen, bwin among them",
        ("Betano (brand; the Colombian edition is not confirmed)",),
        "no closing feed; the last pre-match update is readable after kick-off for 7 days "
        "(market.final_prematch_odds)",
        "contracted plan, 75,000 requests/day, until 29 Oct 2026",
        "primary source; recover final pre-match prices for every played match",
        ("https://www.api-football.com/documentation-v3",)),
    OddsSourceProfile(
        "football_data_co_uk", "football-data.co.uk", Kind.HISTORICAL_FILES, Access.ACTIVE,
        "Bet365, bwin, Betfred, BetVictor, Paddy Power, Sky Bet, Betfair Exchange, market max/average "
        "(22 European divisions + 16 extra leagues)",
        (),
        "closing and pre-closing columns; Pinnacle columns unreliable after 23 Jul 2025 and absent in 2026/27 files",
        "free for private individuals; no automated bots/scrapers/AI for commercial or data-training products",
        "historical backtests only (already imported); no Colombian league; ask the owner before automating "
        "downloads",
        ("https://www.football-data.co.uk/data.php", "https://www.football-data.co.uk/notes.txt")),
    OddsSourceProfile(
        "the_odds_api", "The Odds API", Kind.LIVE_API, Access.FREE_NEEDS_OWNER,
        "100+ books; EU region includes Pinnacle (public-website delay), Betfair Exchange, Betsson, Marathon Bet, "
        "1xBet; UK region includes Betano UK",
        (),
        "historical snapshots on paid plans only",
        "free tier 500 credits/month (an account in the owner's name); paid from USD 30/month",
        "candidate for a free second opinion on European prices; no Colombian league or book - not pursued "
        "without the owner",
        ("https://the-odds-api.com/", "https://the-odds-api.com/sports-odds-data/bookmaker-apis.html")),
    OddsSourceProfile(
        "odds_api_io", "Odds-API.io", Kind.LIVE_API, Access.PAYMENT_REQUIRED,
        "361 active books incl. Betplay, Codere CO, RushBet CO, Betano (BR/MX/PE), bwin (DE/ES/FR/IT)",
        ("Betplay", "Codere", "Rushbet"),
        "historical closing-lines endpoint (paid)",
        "from GBP 49/month for 2 books; new free keys paused",
        "the only researched route to Colombian operator prices; requires payment - not contracted",
        ("https://odds-api.io/pricing", "https://api.odds-api.io/v3/bookmakers")),
    OddsSourceProfile(
        "opticodds", "OpticOdds", Kind.LIVE_API, Access.PAYMENT_REQUIRED,
        "169 books + 18 exchanges incl. Betano, bwin, Betsson, Betplay, RushBet, Codere; no Pinnacle",
        ("Betplay", "Rushbet", "Codere"),
        "historical odds endpoint",
        "custom quote (third-party estimate ~USD 5,000/month per sport, unverified)",
        "requires payment - not contracted",
        ("https://developer.opticodds.com/docs/sportsbooks.md", "https://opticodds.com/pricing")),
    OddsSourceProfile(
        "sportmonks", "SportMonks", Kind.LIVE_API, Access.PAYMENT_REQUIRED,
        "142 books (Pinnacle standard, Betano premium); no Colombian books found",
        (),
        "older seasons as a paid add-on",
        "EUR 29-249/month plus odds add-on from EUR 24/month",
        "requires payment - not contracted",
        ("https://www.sportmonks.com/football-api/plans-pricing/",)),
    OddsSourceProfile(
        "betsapi", "BetsAPI", Kind.LIVE_API, Access.PAYMENT_REQUIRED,
        "single-book feeds: Bet365, bwin, Betfair, SBOBET, 1xBet",
        (),
        "not stated",
        "USD 100-300/month",
        "requires payment - not contracted (the only researched paid route to bwin prices)",
        ("https://betsapi.com/mm/pricing_table",)),
    OddsSourceProfile(
        "betfair_exchange", "Betfair Exchange API", Kind.LIVE_API, Access.FREE_NEEDS_OWNER,
        "the exchange itself",
        (),
        "historical data from 2015 (free BASIC tier: 1-minute last traded price)",
        "delayed key free for development; live key GBP 499 one-off; needs a Betfair account, which may not be "
        "allowed from Colombia (unverified)",
        "not pursued: account and jurisdiction are the owner's question",
        ("https://support.developer.betfair.com/hc/en-us/articles/115003864531",)),
    OddsSourceProfile(
        "pinnacle_api", "Pinnacle API", Kind.LIVE_API, Access.CLOSED,
        "-", (), "-", "closed to the public since 23 Jul 2025", "unavailable",
        ("https://github.com/pinnacleapi/pinnacleapi-documentation",)),
    OddsSourceProfile(
        "operator_websites", "Colombian operator websites", Kind.LIVE_API, Access.REJECTED,
        "Wplay, Betplay, Yajuego, Codere, ...", ("all",), "-",
        "-",
        "never scraped: operator terms forbid bots and Ley 1273 de 2009 art. 269A penalises unauthorised access",
        ("https://www.rushbet.co/?page=eula", "http://www.secretariasenado.gov.co/senado/basedoc/ley_1273_2009.html")),
)


def enabled_sources() -> tuple[OddsSourceProfile, ...]:
    """The sources the platform may read: ACTIVE ones only. A paid or account-bound source
    becomes active by an owner decision recorded here, never by configuration alone."""
    return tuple(s for s in ODDS_SOURCES if s.access is Access.ACTIVE)
