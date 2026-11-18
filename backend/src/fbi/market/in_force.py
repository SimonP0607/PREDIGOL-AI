"""The prices in force of a match, read the same way by the Mercados tab (C-14, plan EA) and by Mi parlay (EA-501): one price per
house, market, selection and line (``unify``, the lower provider id where two ids are one market), and the implied probability of each
selection without the margin (``implied``: per house, its prices of one line normalised to their total - 2 for a double chance, 1
otherwise - then the mean over the houses that price the whole line). Read only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.odds.book_catalog import read_book_in_force
from fbi.odds.quote_current import CurrentBook, CurrentQuote, market_key, read_in_force


def key_of(q: CurrentQuote) -> str:
    return market_key(q.bet_id, q.period, q.subject)


def unify(quotes: Iterable[CurrentQuote]) -> list[CurrentQuote]:
    """One price per bookmaker, market, selection and line: where two provider ids price the same market (307 and 339), the
    lower id's price; within one id, the newest body's."""
    best: dict[tuple[int, str, str, Decimal], CurrentQuote] = {}
    for q in quotes:
        k = (q.bookmaker_id, key_of(q), q.selection, q.line)
        held = best.get(k)
        if held is None or (q.bet_id, -q.captured_at.timestamp()) < (held.bet_id, -held.captured_at.timestamp()):
            best[k] = q
    return list(best.values())


def book(conn: psycopg.Connection[Any], fixture_id: int) -> CurrentBook | None:
    """The match's prices in force: the book when its refreshes are on and it holds the match (the Cuotas page's reading), else the
    reading of the structured quotes."""
    return (read_book_in_force(conn, fixture_id) if settings.odds.book_refresh_enabled else None) or read_in_force(conn, fixture_id)


def group_key(q: CurrentQuote) -> Decimal:
    """The line a price belongs to among its house's prices: an Asian handicap's away row carries the negated home line."""
    return -q.line if q.kind == "asian_handicap" and q.selection == "Away" else q.line


def implied(quotes: Sequence[CurrentQuote]) -> dict[tuple[str, Decimal], tuple[float, int, datetime]]:
    """Per (selection, line) of ONE market: the mean over the houses of the house's normalised price, the houses and the newest
    price's time. A house that does not price every selection of a line that some house prices is left out of that line."""
    by_line: dict[Decimal, dict[int, dict[str, CurrentQuote]]] = defaultdict(lambda: defaultdict(dict))
    for q in quotes:
        by_line[group_key(q)][q.bookmaker_id][q.selection] = q
    out: dict[tuple[str, Decimal], tuple[float, int, datetime]] = {}
    for books in by_line.values():
        full = set().union(*(set(b) for b in books.values()))
        if len(full) < 2:
            continue
        sums: dict[str, float] = defaultdict(float)
        newest: dict[str, datetime] = {}
        lines: dict[str, Decimal] = {}
        n = 0
        for prices in books.values():
            if set(prices) != full:
                continue
            kind = next(iter(prices.values())).kind
            total = 2.0 if kind == "double_chance" else 1.0
            inv = {s: 1.0 / float(q.odds) for s, q in prices.items()}
            norm = sum(inv.values())
            if norm <= 0:
                continue
            n += 1
            for s, q in prices.items():
                sums[s] += total * inv[s] / norm
                newest[s] = max(newest.get(s, q.since), q.since)
                lines[s] = q.line
        if n == 0:
            continue
        for s in full:
            out[(s, lines[s])] = (min(1.0, sums[s] / n), n, newest[s])
    return out
