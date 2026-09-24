"""The live market consensus: de-vigged probabilities across the books WE captured.

One consensus per captured payload - the set of books the provider returned
in one response, at one instant. Each bookmaker's book is de-vigged on its
own (a book that is incomplete for the market is left out rather than
guessed, and so is a book with no margin - usually a stale or broken quote),
then the fair probabilities are averaged across bookmakers. The spread across
bookmakers is kept as ``dispersion``; the best price is kept with the
bookmaker that offered it, among the books that passed.

Only markets whose outcomes are known to be exclusive AND whose selections
pair unambiguously: 1X2, Over/Under per line, BTTS. Asian handicap is left
out on purpose until real payloads confirm how the provider signs the two
sides of a line - pairing "Home -1" with the wrong "Away" line would produce
a confident, wrong probability.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import psycopg
from psycopg.rows import tuple_row

from fbi.core.errors import InvalidOddsError
from fbi.domain.market_probability import DevigMethod, devig
from fbi.domain.odds import DecimalOdds

EXCLUSIVE: dict[str, tuple[str, ...]] = {
    "1X2": ("Home", "Draw", "Away"),
    "OU": ("Over", "Under"),
    "BTTS": ("Yes", "No"),
}
METHODS = (DevigMethod.SHIN, DevigMethod.PROPORTIONAL, DevigMethod.POWER)


@dataclass(frozen=True, slots=True)
class BookQuote:
    bookmaker_id: int
    market_key: str
    selection: str
    line: Decimal
    odds: Decimal


@dataclass(frozen=True, slots=True)
class ConsensusRow:
    market_key: str
    selection: str
    line: Decimal
    method: str
    p_fair: float
    n_bookmakers: int
    overround: float
    best_odds: Decimal
    best_bookmaker_id: int
    dispersion: float | None


def consensus(quotes: Sequence[BookQuote], methods: Sequence[DevigMethod] = METHODS) -> list[ConsensusRow]:
    books: dict[tuple[str, Decimal], dict[int, dict[str, Decimal]]] = defaultdict(lambda: defaultdict(dict))
    for q in quotes:
        if q.market_key in EXCLUSIVE:
            books[(q.market_key, q.line)][q.bookmaker_id][q.selection] = q.odds
    rows: list[ConsensusRow] = []
    for (market, line), by_book in sorted(books.items()):
        wanted = EXCLUSIVE[market]
        complete = {b: sel for b, sel in by_book.items() if set(sel) == set(wanted)}
        if not complete:
            continue
        for method in methods:
            fairs: list[dict[str, float]] = []
            overrounds: list[float] = []
            used: list[int] = []
            for b, sel in sorted(complete.items()):
                try:
                    fair = devig({s: DecimalOdds(sel[s]) for s in wanted}, method)
                except InvalidOddsError:
                    continue  # a book with no margin, or an impossible price: not averaged in
                fairs.append({s: fair[s].probability.value for s in wanted})
                overrounds.append(fair[wanted[0]].overround)
                used.append(b)
            if not fairs:
                continue
            for s in wanted:
                ps = [f[s] for f in fairs]
                best_book = _best(used, complete, s)
                rows.append(ConsensusRow(
                    market, s, line, method.value, statistics.fmean(ps), len(fairs),
                    statistics.fmean(overrounds), complete[best_book][s], best_book,
                    statistics.pstdev(ps) if len(ps) > 1 else None,
                ))
    return rows


def _best(books: Sequence[int], prices: dict[int, dict[str, Decimal]], selection: str) -> int:
    """The bookmaker with the highest price; the lowest id on a tie, so the answer is stable."""
    return max(books, key=lambda b: (prices[b][selection], -b))


def write_consensus(conn: psycopg.Connection, fixture_id: int, as_of: datetime, rows: Sequence[ConsensusRow]) -> int:
    """Idempotent: one row per (fixture, market, selection, line, as_of, method)."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, "
            "p_fair, n_bookmakers, overround, best_odds, best_bookmaker_id, dispersion) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            [(fixture_id, r.market_key, r.selection, r.line, as_of, r.method, round(r.p_fair, 6), r.n_bookmakers,
              round(r.overround, 5), r.best_odds, r.best_bookmaker_id,
              None if r.dispersion is None else round(r.dispersion, 6)) for r in rows],
        )
        return max(cur.rowcount, 0)


def recompute_from_snapshots(conn: psycopg.Connection, *, fixture_ids: Sequence[int] | None = None) -> tuple[int, int]:
    """Rebuild the consensus from stored snapshots, one per (fixture, payload).

    Returns (payloads seen, rows written). Safe to re-run: existing rows stay."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT fixture_id, payload_hash, max(captured_at) OVER (PARTITION BY fixture_id, payload_hash), "
            "bookmaker_id, market_key, selection, line, odds_decimal FROM market.odds_snapshots "
            "WHERE (%s::bigint[] IS NULL OR fixture_id = ANY(%s::bigint[])) AND market_key = ANY(%s)",
            (list(fixture_ids) if fixture_ids is not None else None,
             list(fixture_ids) if fixture_ids is not None else None, list(EXCLUSIVE)),
        )
        groups: dict[tuple[int, str, datetime], list[BookQuote]] = defaultdict(list)
        for fid, ph, as_of, bm, mk, sel, line, odds in cur.fetchall():
            groups[(int(fid), str(ph), as_of)].append(BookQuote(int(bm), str(mk), str(sel), Decimal(line),
                                                                Decimal(odds)))
    written = 0
    for (fid, _, as_of), quotes in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][2])):
        written += write_consensus(conn, fid, as_of, consensus(quotes))
    return len(groups), written
