"""The explorer's markets: the visible types of ``tax-v3`` grouped by market and period (plan Cuotas, BE-011).

A type of ``fbi.odds.book_taxonomy`` has a stable key ``<domain>.<market>.<period>[.<home|away>]``. The explorer names a MARKET by
that key without its period (``corners.total``, ``goals.total.home``, ``player.anytime_scorer.away``) and offers its periods
beside it, so ``market=corners.total&period=1H`` is the type 77. A type of a minute interval keeps its whole key
(``result.1x2.m0_10``, period ``INTERVAL``): the five intervals are five markets, never one with an ambiguous period.

A market is listed under the family of its types: the 1X2 of the whole match is in ``result``, those of the halves in
``goals_half`` - the same key in two families, each with its own periods. Two provider ids of one market (307 and 339) are one
market; a match that has both is read from the lower id. Metadata only: nothing here reads a price.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache

from fbi.odds.book_taxonomy import PERIODS, BookSpec, book_specs

FAMILY_ORDER: tuple[str, ...] = (
    "result", "goals", "goals_half", "corners", "cards", "shots", "players", "saves", "offsides", "tackles", "special",
    "timing", "advance", "other_sport",
)
"""The order the explorer lists the families in (a family not listed comes after, by name)."""

PLAYER_SELECTION = "Player"
"""The selection code of a player's own price in a player market: the player's name travels apart (``player``)."""


def market_key(spec: BookSpec) -> str:
    """The explorer's key of the market a type prices: its ``tax-v3`` key without the period (an interval keeps it)."""
    parts = spec.key.split(".")
    if spec.period == "INTERVAL":
        return spec.key
    if len(parts) < 3 or parts[2] != spec.period.lower():
        raise ValueError(f"bet {spec.bet_id}: key {spec.key!r} does not name its period {spec.period} third")
    return ".".join(parts[:2] + parts[3:])


@dataclass(frozen=True, slots=True)
class Market:
    """One market of one family: its types by period (aliases together, the lowest id first)."""

    key: str
    family: str
    periods: tuple[str, ...]
    specs: tuple[BookSpec, ...]

    @property
    def lead(self) -> BookSpec:
        return self.specs[0]

    @property
    def kind(self) -> str:
        return self.lead.reader

    @property
    def subject(self) -> str:
        return self.lead.subject

    @property
    def has_line(self) -> bool:
        return any(s.has_line for s in self.specs)

    @property
    def fair(self) -> bool:
        return any(s.fair for s in self.specs)

    @property
    def parlay(self) -> bool:
        return any(s.parlay for s in self.specs)

    def specs_of(self, period: str) -> tuple[BookSpec, ...]:
        return tuple(s for s in self.specs if s.period == period)


@dataclass(frozen=True, slots=True)
class MarketIndex:
    markets: tuple[Market, ...]
    by_bet: dict[int, Market]
    by_key_period: dict[tuple[str, str], Market]
    rank: dict[tuple[str, str], int]
    """(family, key) -> where the market comes in its family: the taxonomy's own order."""

    def find(self, key: str, period: str) -> Market | None:
        return self.by_key_period.get((key, period))

    def periods_of(self, key: str) -> tuple[str, ...]:
        """Every period the taxonomy has for a market key, in the product's order."""
        found = {p for m in self.markets if m.key == key for p in m.periods}
        return tuple(p for p in PERIODS if p in found)


def family_rank(family: str) -> tuple[int, str]:
    return (FAMILY_ORDER.index(family), "") if family in FAMILY_ORDER else (len(FAMILY_ORDER), family)


def build_index(specs: Sequence[BookSpec]) -> MarketIndex:
    grouped: dict[tuple[str, str], list[BookSpec]] = defaultdict(list)
    order: dict[tuple[str, str], int] = {}
    for position, spec in enumerate(specs):
        if not spec.visible:
            continue
        group = (spec.family, market_key(spec))
        grouped[group].append(spec)
        order.setdefault(group, position)
    markets: list[Market] = []
    for (family, key), members in grouped.items():
        members.sort(key=lambda s: (PERIODS.index(s.period), s.bet_id))
        periods = tuple(p for p in PERIODS if any(s.period == p for s in members))
        markets.append(Market(key=key, family=family, periods=periods, specs=tuple(members)))
    markets.sort(key=lambda m: (family_rank(m.family), order[(m.family, m.key)]))
    by_key_period: dict[tuple[str, str], Market] = {}
    for market in markets:
        for period in market.periods:
            if (market.key, period) in by_key_period:
                raise ValueError(f"market {market.key} {period} is in two families")
            by_key_period[(market.key, period)] = market
    return MarketIndex(markets=tuple(markets), by_bet={s.bet_id: m for m in markets for s in m.specs},
                       by_key_period=by_key_period,
                       rank={(m.family, m.key): i for i, m in enumerate(markets)})


@lru_cache(maxsize=1)
def index() -> MarketIndex:
    """The markets of ``tax-v3`` as the explorer lists them."""
    return build_index(book_specs())
