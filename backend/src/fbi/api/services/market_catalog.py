"""The structured markets of a match by category, each price the one IN FORCE (plan Partidos y Match Center, F4a).

``fbi.odds.quote_current`` says which prices are in force (the provider's last answer before kick-off, A -> B -> A included);
this module folds them into what the Mercados tab reads: the categories that have prices, and for the one asked for, each
market with its selections and lines, the best price, its bookmaker, since when, and every bookmaker. Markets the provider
repeats under two ids (307 and 339, corners double chance) read as one: per bookmaker, selection and line one price, the one of
the lower id. Nothing is deleted or rewritten; this is a reading.

Loaded when a category is opened, never in the match's 60-second poll; kept 60 s per process (``fbi.api.cache``). Same access as
``/matches/{id}/markets``: the product tier. Prices only - nothing here comes from a model, a pick or the shadow layer.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import cast

from fastapi import HTTPException

from fbi.api.cache import shared
from fbi.api.contracts.market_catalog import (
    CatalogCategory,
    MarketCatalog,
    MarketCatalogBook,
    MarketCatalogCategory,
    MarketCatalogMarket,
    MarketCatalogSelection,
)
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.repositories import Conn
from fbi.core.config import settings
from fbi.odds.book_catalog import read_book_in_force
from fbi.odds.quote_current import (
    CATALOG_FAMILIES,
    CurrentQuote,
    InForce,
    market_code,
    market_key,
    market_rank,
    read_in_force,
)

CACHE_SECONDS = 60

_SELECTION_ORDER = {s: i for i, s in enumerate(
    ("Home", "Draw", "Away", "1X", "12", "X2", "Over", "Under", "Yes", "No", "Odd", "Even"))}

_REASONS = {
    "withdrawn": "The provider's newest answer before kick-off came back empty: no price is in force.",
    "unread": "The provider's answers for this match are not structured yet.",
    "never_asked": "No pre-match price was asked for this match in the 4 days before kick-off.",
    "priced": "No price in force in the structured markets.",
}


def _key(q: CurrentQuote) -> str:
    return market_key(q.bet_id, q.period, q.subject)


def unify(quotes: Iterable[CurrentQuote]) -> list[CurrentQuote]:
    """One price per bookmaker, market, selection and line: where two provider ids price the same market (307 and 339), the
    lower id's price; within one id, the newest body's."""
    best: dict[tuple[int, str, str, Decimal], CurrentQuote] = {}
    for q in quotes:
        k = (q.bookmaker_id, _key(q), q.selection, q.line)
        held = best.get(k)
        if held is None or (q.bet_id, -q.captured_at.timestamp()) < (held.bet_id, -held.captured_at.timestamp()):
            best[k] = q
    return list(best.values())


def _pair_line(q: CurrentQuote) -> Decimal:
    """Sorting line: an Asian handicap's away row carries the negated home line, so the two rows of a pair sit together."""
    return -q.line if q.kind == "asian_handicap" and q.selection == "Away" else q.line


def _selection(rows: Sequence[CurrentQuote]) -> MarketCatalogSelection:
    ordered = sorted(rows, key=lambda q: (-q.odds, q.bookmaker, q.bookmaker_id))
    top = ordered[0]
    return MarketCatalogSelection(
        selection=top.selection, line=top.line, best_odds=top.odds, bookmaker_id=top.bookmaker_id,
        bookmaker=top.bookmaker, captured_at=top.since, bookmakers=len({q.bookmaker_id for q in ordered}),
        books=[MarketCatalogBook(bookmaker_id=q.bookmaker_id, bookmaker=q.bookmaker, odds=q.odds, captured_at=q.since,
                                 bet_id=q.bet_id) for q in ordered])


def _market(key: str, rows: Sequence[CurrentQuote]) -> MarketCatalogMarket:
    lead = min(rows, key=lambda q: q.bet_id)
    by_selection: dict[tuple[str, Decimal], list[CurrentQuote]] = defaultdict(list)
    for q in rows:
        by_selection[(q.selection, q.line)].append(q)
    groups = sorted(by_selection.values(), key=lambda g: (
        _pair_line(g[0]), _SELECTION_ORDER.get(g[0].selection, len(_SELECTION_ORDER)), g[0].selection))
    return MarketCatalogMarket(
        key=key, code=market_code(lead.bet_id), period=lead.period, subject=lead.subject, kind=lead.kind,
        has_line=lead.has_line, category=cast(CatalogCategory, lead.family),  # CATALOG_FAMILIES only (the SQL filter)
        bet_ids=sorted({q.bet_id for q in rows}), provider_name=lead.provider_name,
        market_key=next((q.market_key for q in rows if q.market_key), None),
        bookmakers=len({q.bookmaker_id for q in rows}), selections=[_selection(g) for g in groups])


def categories(quotes: Sequence[CurrentQuote]) -> list[MarketCatalogCategory]:
    """The categories with a price in force, in the product's order, with what each holds. ``quotes`` already unified."""
    out: list[MarketCatalogCategory] = []
    for family in CATALOG_FAMILIES:
        rows = [q for q in quotes if q.family == family]
        if rows:
            out.append(MarketCatalogCategory(
                key=cast(CatalogCategory, family),  # CATALOG_FAMILIES is CatalogCategory's list
                markets=len({_key(q) for q in rows}),
                selections=len({(_key(q), q.selection, q.line) for q in rows}),
                bookmakers=len({q.bookmaker_id for q in rows})))
    return out


def markets(quotes: Sequence[CurrentQuote], category: str) -> list[MarketCatalogMarket]:
    """The markets of one category, in the taxonomy's order. ``quotes`` already unified."""
    by_key: dict[str, list[CurrentQuote]] = defaultdict(list)
    for q in quotes:
        if q.family == category:
            by_key[_key(q)].append(q)
    ordered = sorted(by_key.items(), key=lambda kv: (min(market_rank(q.bet_id) for q in kv[1]), kv[0]))
    return [_market(k, rows) for k, rows in ordered]


def build(fixture_id: int, kickoff_at: datetime, in_force: InForce, quotes: Sequence[CurrentQuote],
          category: CatalogCategory | None) -> MarketCatalog:
    unified = unify(quotes)
    return MarketCatalog(
        fixture_id=fixture_id, kickoff_at=kickoff_at,
        state=in_force.state, checked_at=in_force.checked_at, newer_answer_pending=in_force.newer_pending,
        partial=in_force.partial, category=category, categories=categories(unified),
        markets=markets(unified, category) if category else [])


@shared(CACHE_SECONDS)
def match_market_catalog(conn: Conn, fixture_id: int, category: CatalogCategory | None = None) -> Envelope[MarketCatalog]:
    """GET /matches/{id}/markets/catalog: the categories with prices in force, and the markets of ``category``."""
    # With the book refreshes on, Cuotas shows the newer answer of the two tables (BE-011); this tab reads the book then, so the same
    # match shows the same price on both screens (BE-020). No row in the book for the match: the reading it always had.
    book = (read_book_in_force(conn, fixture_id) if settings.odds.book_refresh_enabled else None) or read_in_force(conn, fixture_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"fixture {fixture_id} not found")
    view = build(fixture_id, book.kickoff_at, book.in_force, book.quotes, category)
    if not view.categories:
        return unavailable(view, _REASONS[book.in_force.state], status=DataStatus.EMPTY)
    return ok(view)
