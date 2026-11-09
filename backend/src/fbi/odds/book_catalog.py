"""The Match Center's «Mercados» read through the current-price book (plan Cuotas, phase 6: BE-020).

``fbi.api.services.market_catalog`` folds the prices IN FORCE of a match into categories and markets; those prices come from
``fbi.odds.quote_current`` (the provider's last answer before kick-off, as the ``tax-v2`` extractor read it). The Cuotas explorer
reads ``market.book_current`` (BE-010), which is built from the same rule but also counts the answers of the book refreshes
(``market.book_asks``, BE-011), bodies the extractor never reads. With the refreshes on, the book is the newer of the two by
design, so the same match could show two different prices on two screens.

This module lets the catalogue fold the book's rows instead: each row's summary (lines -> selections -> the odds of every
bookmaker) is turned back into the ``CurrentQuote`` the catalogue already takes, so nothing after it changes (unify, categories,
markets, the contract). It is used only while ``FBI_ODDS_BOOK_REFRESH`` is on and the book holds rows for the match; otherwise
the catalogue reads as it always did. ``since`` is the book's ``in_force_since``: like the extractor's, it belongs to the answer,
not to each price.

Only the types the catalogue structures are taken (the bets ``tax-v2`` extracts in ``CATALOG_FAMILIES``), with the family, period
and subject of ``tax-v2``, so a market has the same key on both screens.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.odds.quote_current import CATALOG_FAMILIES, CurrentBook, CurrentQuote, InForce
from fbi.odds.quote_taxonomy import BetSpec, extracted_specs

BOOK_ROWS_SQL = """
SELECT d.provider_bet_id AS bet_id, b.captured_at, b.in_force_since, b.checked_at, b.newer_pending, b.summary
  FROM market.book_current b JOIN market.market_definitions d ON d.id = b.definition_id
 WHERE b.fixture_id = %(f)s
 ORDER BY d.provider_bet_id
"""

BOOKMAKERS_SQL = """
SELECT id, provider_bookmaker_id, name FROM market.bookmakers WHERE provider_bookmaker_id = ANY(%(ids)s::int[])
"""

FIXTURE_SQL = "SELECT kickoff_at FROM core.fixtures WHERE id = %(f)s"

LINE_STEP = Decimal("0.01")
ODDS_STEP = Decimal("0.001")
"""The scales of ``market.odds_quotes`` (NUMERIC(6,2) and NUMERIC(9,3)): the book keeps floats, the catalogue serves what the
table holds, so both screens print the same digits."""


def _line(value: Any) -> Decimal:
    return Decimal(0).quantize(LINE_STEP) if value is None else Decimal(str(value)).quantize(LINE_STEP, ROUND_HALF_UP)


def _odds(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(ODDS_STEP, ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Bookmaker:
    """A bookmaker as the catalogue names it: our id (the one ``market.odds_quotes`` carries) and its name."""

    id: int
    name: str


def structured_specs() -> dict[int, BetSpec]:
    """The bets the catalogue structures: those ``tax-v2`` extracts in the catalogue's families."""
    return {s.bet_id: s for s in extracted_specs() if s.family in CATALOG_FAMILIES}


def provider_bookmakers(summary: Mapping[str, Any]) -> set[int]:
    """The provider ids of every bookmaker a summary holds a price of."""
    return {int(b) for g in summary.get("lines", ()) for s in g.get("sels", ()) for b in s.get("odds", {})}


def quotes_of(spec: BetSpec, summary: Mapping[str, Any], bookmakers: Mapping[int, Bookmaker], *, captured_at: datetime,
              since: datetime) -> list[CurrentQuote]:
    """The prices of one type as ``CurrentQuote``: one per bookmaker, selection and line. A bookmaker we do not know by id
    is left out (it cannot be named)."""
    out: list[CurrentQuote] = []
    for group in summary.get("lines", ()):
        for sel in group.get("sels", ()):
            line = sel.get("line", group.get("line"))
            for provider_id, odds in sel.get("odds", {}).items():
                book = bookmakers.get(int(provider_id))
                if book is None:
                    continue
                out.append(CurrentQuote(
                    bookmaker_id=book.id, bookmaker=book.name, bet_id=spec.bet_id, family=spec.family, period=spec.period,
                    subject=spec.subject, kind=spec.kind, has_line=spec.has_line, market_key=spec.market_key,
                    provider_name=spec.name, selection=str(sel["sel"]), line=_line(line),
                    odds=_odds(odds), captured_at=captured_at, since=since))
    return out


def quotes_of_rows(rows: Iterable[tuple[int, Mapping[str, Any], datetime, datetime]],
                   bookmakers: Mapping[int, Bookmaker]) -> list[CurrentQuote]:
    """Every price of the rows ``(bet_id, summary, captured_at, since)`` whose bet the catalogue structures."""
    specs = structured_specs()
    quotes: list[CurrentQuote] = []
    for bet_id, summary, captured_at, since in rows:
        spec = specs.get(bet_id)
        if spec is not None:
            quotes.extend(quotes_of(spec, summary, bookmakers, captured_at=captured_at, since=since))
    return quotes


def read_book_in_force(conn: psycopg.Connection[Any], fixture_id: int) -> CurrentBook | None:
    """The match's prices in force as the book holds them, for the catalogue. None when the match does not exist or the book has
    no row of a type the catalogue structures for it (not built yet, or nothing in force): the caller reads as it always did."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURE_SQL, {"f": fixture_id})
        fixture = cur.fetchone()
        if fixture is None:
            return None
        cur.execute(BOOK_ROWS_SQL, {"f": fixture_id})
        rows = [r for r in cur.fetchall() if int(r["bet_id"]) in structured_specs()]
        if not rows:
            return None
        ids = sorted({p for r in rows for p in provider_bookmakers(r["summary"])})
        cur.execute(BOOKMAKERS_SQL, {"ids": ids})
        bookmakers = {int(b["provider_bookmaker_id"]): Bookmaker(int(b["id"]), str(b["name"])) for b in cur.fetchall()}
    return build_book(fixture_id, fixture["kickoff_at"], rows, bookmakers)


def build_book(fixture_id: int, kickoff_at: datetime, rows: Sequence[Mapping[str, Any]],
               bookmakers: Mapping[int, Bookmaker]) -> CurrentBook:
    """The ``CurrentBook`` of the book's rows (``bet_id``, ``captured_at``, ``in_force_since``, ``checked_at``,
    ``newer_pending``, ``summary``). Pure."""
    quotes = quotes_of_rows(
        ((int(r["bet_id"]), r["summary"], r["captured_at"], r["in_force_since"] or r["captured_at"]) for r in rows), bookmakers)
    head = rows[0]
    return CurrentBook(
        fixture_id=fixture_id, kickoff_at=kickoff_at,
        in_force=InForce(state="priced", checked_at=head["checked_at"], newer_pending=any(bool(r["newer_pending"]) for r in rows)),
        quotes=tuple(quotes))
