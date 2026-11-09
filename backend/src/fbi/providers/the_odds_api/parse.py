"""The answer of ``GET /v4/sports/{sport}/odds`` for the ``h2h`` market of football, as typed values.

Pure functions, no network. A price that does not parse, an event without the three outcomes of a football 1X2 or a book that lists a
price at or below 1 is dropped and counted; it is never repaired (a price on the wrong outcome is worse than none).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fbi.core.errors import InvalidOddsError, ProviderPayloadError
from fbi.domain.market_probability import DevigMethod, FairProbability, devig
from fbi.domain.odds import DecimalOdds

H2H = "h2h"
DRAW = "Draw"


@dataclass(frozen=True, slots=True)
class BookPrice:
    """One bookmaker's 1X2 for one event, in the event's own team names."""

    bookmaker: str
    last_update: datetime | None
    home: DecimalOdds
    draw: DecimalOdds
    away: DecimalOdds


@dataclass(frozen=True, slots=True)
class SharpEvent:
    event_id: str
    sport_key: str
    commence_at: datetime
    home_team: str
    away_team: str
    prices: tuple[BookPrice, ...] = ()
    dropped: tuple[str, ...] = field(default=())
    """Why a book of this event was left out, one short line each (kept so the loss is visible, never silent)."""

    def price_of(self, bookmaker: str) -> BookPrice | None:
        return next((p for p in self.prices if p.bookmaker == bookmaker), None)


def _instant(text: object) -> datetime | None:
    if not isinstance(text, str) or not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _odds(value: object) -> DecimalOdds | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return DecimalOdds(Decimal(str(value)))
    except (InvalidOperation, InvalidOddsError):
        return None


def _book_price(book: Mapping[str, Any], home: str, away: str) -> tuple[BookPrice | None, str | None]:
    key = str(book.get("key", ""))
    markets = book.get("markets")
    market = next((m for m in markets if isinstance(m, Mapping) and m.get("key") == H2H), None) if isinstance(markets, list) else None
    if market is None:
        return None, f"{key}: no h2h market"
    outcomes = market.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 3:
        return None, f"{key}: h2h without exactly three outcomes"
    by_name: dict[str, DecimalOdds | None] = {}
    for outcome in outcomes:
        if not isinstance(outcome, Mapping):
            return None, f"{key}: malformed outcome"
        name = str(outcome.get("name", ""))
        if name in by_name:
            return None, f"{key}: outcome {name!r} twice"
        by_name[name] = _odds(outcome.get("price"))
    if set(by_name) != {home, away, DRAW} or any(v is None for v in by_name.values()):
        return None, f"{key}: outcomes are not home, away and Draw with a valid price"
    h, d, a = by_name[home], by_name[DRAW], by_name[away]
    assert h is not None and d is not None and a is not None  # narrowed by the check above
    return BookPrice(key, _instant(market.get("last_update")), h, d, a), None


def parse_events(body: object, *, sport_key: str | None = None) -> list[SharpEvent]:
    """The events of one odds answer. Anything that is not a list of events is a provider error, not an empty answer."""
    if not isinstance(body, list):
        raise ProviderPayloadError("The Odds API: the odds answer is not a list of events")
    events: list[SharpEvent] = []
    for raw in body:
        if not isinstance(raw, Mapping):
            continue
        commence = _instant(raw.get("commence_time"))
        home, away, event_id = raw.get("home_team"), raw.get("away_team"), raw.get("id")
        if commence is None or not isinstance(home, str) or not isinstance(away, str) or not isinstance(event_id, str):
            continue
        prices: list[BookPrice] = []
        dropped: list[str] = []
        for book in raw.get("bookmakers") or []:
            if not isinstance(book, Mapping):
                continue
            price, why = _book_price(book, home, away)
            if price is not None:
                prices.append(price)
            elif why is not None:
                dropped.append(why)
        events.append(SharpEvent(event_id, str(raw.get("sport_key") or sport_key or ""), commence, home, away, tuple(prices), tuple(dropped)))
    return events


def reference_fair(event: SharpEvent, bookmaker: str, method: DevigMethod = DevigMethod.SHIN) -> dict[str, FairProbability] | None:
    """The reference book's 1X2 without its margin, keyed ``home`` / ``draw`` / ``away``; None when that book does not list the event."""
    price = event.price_of(bookmaker)
    if price is None:
        return None
    return devig({"home": price.home, "draw": price.draw, "away": price.away}, method)
