"""The family forecasts against the market (plan F11): did the model know something the prices did not?

``fbi.families.score`` says whether the probabilities a family stated were right. That is necessary and not enough: a model can be well
calibrated and still know less than the books, and then no price can be beaten with it. The test that matters for value is the one made here:
on the same rows and the same outcomes, the log loss of the family against the log loss of the market's own probability - the prices with the
margin taken out - as the market stood just before the kick-off (``close``) and a day before it (``h24``), when a pick would have been taken.

The market's probability is the CONSENSUS of the books the price clock captured (``market.odds_quotes``, read as of a cut-off, never "latest"):

* each book is de-vigged on its own, proportionally - its implied probabilities divided by their sum - and only a COMPLETE book counts (every
  outcome of the market quoted at that line, a believable margin: a book with no margin is stale or broken, one with too much is not a
  price). The books are then averaged;
* a consensus of fewer than ``MIN_BOOKS`` books is not a consensus and is not compared;
* only markets whose outcomes are exclusive and few (over/under, both teams to score, odd/even, draw no bet, 1X2) and only lines that cannot
  push: on a line that can push, the books' fair probability is the one of the bet being settled and the family's is not, so they are not the
  same number.

The difference is reported as ``market_minus_model`` (positive: the model was better) with its standard error, which is clustered by match: the
lines and the selections of one match are not independent observations. Nothing here writes, asks the provider or reaches a model, a price
decision or a pick; it only reads.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final

import psycopg
from psycopg.rows import dict_row

if TYPE_CHECKING:
    from fbi.families.score import Graded

REFERENCES: Final = (("close", timedelta(0)), ("h24", timedelta(hours=24)))
"""The moments the market is read at: the last price before the kick-off, and the last price a day before it."""
OUTCOMES: Final = {"over_under": 2, "both_teams_score": 2, "odd_even": 2, "draw_no_bet": 2, "one_x_two": 3}
"""The kinds of bet a consensus is built for, and how many outcomes a complete book quotes at one line."""
MIN_BOOKS: Final = 3
MAX_OVERROUND: Final = 1.25
"""The most margin a believable book carries. ``fbi.market.consensus`` measured 1.08 on average and 1.13 at worst on the markets it covers."""
PRICE_WINDOW: Final = timedelta(days=10)
"""How long before the first kick-off of the window a price can have been captured (the provider keeps pre-match prices 7 days)."""

FairKey = tuple[str, int, str, Decimal, str]
"""(moment, match, market key, line, selection)"""


@dataclass(frozen=True, slots=True)
class Quote:
    """The last price of one selection at one book, as it stood at a moment."""

    ref: str
    fixture_id: int
    bookmaker_id: int
    key: str
    kind: str
    selection: str
    line: Decimal
    odds: float


def comparable(line: Decimal) -> bool:
    """A line the books' fair probability and the family's can both be read at: no line at all, or a half line (no push is possible)."""
    return line == 0 or line % 1 == Decimal("0.5")


@dataclass(frozen=True, slots=True)
class Book:
    """One COMPLETE book at one line and one moment: every outcome of the market quoted once, with a believable margin (``overround``)."""

    ref: str
    fixture_id: int
    key: str
    line: Decimal
    quotes: tuple[Quote, ...]
    overround: float


def complete_books(quotes: Iterable[Quote]) -> Iterator[Book]:
    """The books that are a price: the quotes of one book at one line and one moment, when it quotes every outcome of the market exactly once
    and its margin is believable (above 1, at most ``MAX_OVERROUND``). A half book, a kind of bet without a consensus and a margin that is not
    one are left out - the consensus and the best price are read from these books and from no others."""
    books: dict[tuple[str, int, int, str, Decimal], list[Quote]] = defaultdict(list)
    for q in quotes:
        books[(q.ref, q.fixture_id, q.bookmaker_id, q.key, q.line)].append(q)
    for (ref, fixture_id, _, key, line), members in books.items():
        expected = OUTCOMES.get(members[0].kind)
        if expected is None or len(members) != expected or len({m.selection for m in members}) != expected:
            continue
        overround = sum(1.0 / m.odds for m in members)
        if not 1.0 < overround <= MAX_OVERROUND:
            continue
        yield Book(ref, fixture_id, key, line, tuple(members), overround)


def consensus(quotes: Iterable[Quote]) -> dict[FairKey, tuple[float, int]]:
    """The fair probability of each selection - the mean over the complete books of their own de-vigged probabilities - and how many books
    it is the mean of."""
    shares: dict[FairKey, list[float]] = defaultdict(list)
    for book in complete_books(quotes):
        for m in book.quotes:
            shares[(book.ref, book.fixture_id, book.key, book.line, m.selection)].append((1.0 / m.odds) / book.overround)
    return {k: (sum(v) / len(v), len(v)) for k, v in shares.items()}


def best_prices(quotes: Iterable[Quote]) -> dict[FairKey, tuple[float, int]]:
    """The highest price any complete book quoted for each selection - the price a bettor who shops around would have taken - and how many
    complete books quoted it (the same books the consensus is the mean of)."""
    best: dict[FairKey, tuple[float, int]] = {}
    for book in complete_books(quotes):
        for m in book.quotes:
            k = (book.ref, book.fixture_id, book.key, book.line, m.selection)
            odds, books = best.get(k, (0.0, 0))
            best[k] = (max(odds, m.odds), books + 1)
    return best


QUOTES_SQL: Final = """
SELECT DISTINCT ON (r.ref, q.fixture_id, q.bookmaker_id, q.definition_id, q.selection, q.line)
       r.ref, q.fixture_id, q.bookmaker_id, d.market_key, d.kind, q.selection, q.line, q.odds_decimal
  FROM unnest(%(refs)s::text[], %(leads)s::interval[]) AS r(ref, lead)
 CROSS JOIN core.fixtures x
  JOIN market.odds_quotes q ON q.fixture_id = x.id
  JOIN market.market_definitions d ON d.id = q.definition_id
 WHERE x.id = ANY(%(fixtures)s::bigint[]) AND d.scope = 'prematch' AND d.market_key = ANY(%(keys)s::text[]) AND d.kind = ANY(%(kinds)s::text[])
   AND q.captured_at >= %(since)s AND q.captured_at <= x.kickoff_at - r.lead
 ORDER BY r.ref, q.fixture_id, q.bookmaker_id, q.definition_id, q.selection, q.line, q.captured_at DESC
"""
"""The last price of every selection at every book at each moment: a price counts from the instant it was captured until the next one."""


def load_quotes(conn: psycopg.Connection[Any], *, fixtures: Sequence[int], keys: Sequence[str], since: datetime) -> list[Quote]:
    """The last prices, at each of the ``REFERENCES``, of the markets ``keys`` of the matches ``fixtures`` (``since``: the first kick-off)."""
    if not fixtures or not keys:
        return []
    params = {"refs": [r for r, _ in REFERENCES], "leads": [lead for _, lead in REFERENCES], "fixtures": list(fixtures), "keys": list(keys),
              "kinds": list(OUTCOMES), "since": since - PRICE_WINDOW}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(QUOTES_SQL, params)
        return [Quote(str(r["ref"]), int(r["fixture_id"]), int(r["bookmaker_id"]), str(r["market_key"]), str(r["kind"]), str(r["selection"]),
                      Decimal(r["line"]), float(r["odds_decimal"])) for r in cur.fetchall()]


CHUNK: Final = 250
"""The matches whose prices are read, and boiled down to a consensus and a best price, at a time: the quotes of a window of weeks (millions)
would not fit in memory as objects, and the two boiled-down numbers of each selection are all the comparison needs."""


def read_prices(conn: psycopg.Connection[Any], *, fixtures: Iterable[int], keys: Sequence[str], since: datetime
                ) -> tuple[dict[FairKey, tuple[float, int]], dict[FairKey, tuple[float, int]]]:
    """The consensus and the best price of every selection of the markets ``keys`` of the matches ``fixtures`` at each of the ``REFERENCES``,
    read ``CHUNK`` matches at a time (the keys carry the match, so the chunks never overlap)."""
    fair: dict[FairKey, tuple[float, int]] = {}
    best: dict[FairKey, tuple[float, int]] = {}
    ordered = sorted(set(fixtures))
    for start in range(0, len(ordered), CHUNK):
        quotes = load_quotes(conn, fixtures=ordered[start:start + CHUNK], keys=keys, since=since)
        fair.update(consensus(quotes))
        best.update(best_prices(quotes))
    return fair, best


def _loss(p: float, won: int) -> float:
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return -math.log(p if won else 1.0 - p)


@dataclass(frozen=True, slots=True)
class Pair:
    """One graded row next to the market's probability for it."""

    model: str
    ref: str
    key: str
    fixture_id: int
    p_model: float
    p_market: float
    won: int
    books: int


def pairs(graded: Iterable[Graded], fair: Mapping[FairKey, tuple[float, int]], *, min_books: int = MIN_BOOKS) -> list[Pair]:
    """The graded rows the market also has a consensus for, at each moment, on a line both can be read at."""
    out: list[Pair] = []
    for g in graded:
        row = g.row
        if not comparable(row.line):
            continue
        for ref, _ in REFERENCES:
            found = fair.get((ref, row.fixture_id, row.key, row.line, row.selection))
            if found is not None and found[1] >= min_books:
                out.append(Pair(row.model, ref, row.key, row.fixture_id, row.p, found[0], g.won, found[1]))
    return out


def _block(members: Sequence[Pair]) -> dict[str, Any]:
    n = len(members)
    diffs = [_loss(m.p_market, m.won) - _loss(m.p_model, m.won) for m in members]
    mean = sum(diffs) / n
    by_match: dict[int, float] = defaultdict(float)
    for m, d in zip(members, diffs, strict=True):
        by_match[m.fixture_id] += d - mean
    se = math.sqrt(sum(v * v for v in by_match.values())) / n
    return {"n": n, "fixtures": len(by_match), "mean_p_model": sum(m.p_model for m in members) / n,
            "mean_p_market": sum(m.p_market for m in members) / n, "observed": sum(m.won for m in members) / n,
            "log_loss_model": sum(_loss(m.p_model, m.won) for m in members) / n,
            "log_loss_market": sum(_loss(m.p_market, m.won) for m in members) / n,
            "market_minus_model": mean, "se": se, "mean_books": sum(m.books for m in members) / n}


def versus(graded: Iterable[Graded], fair: Mapping[FairKey, tuple[float, int]], *, min_books: int = MIN_BOOKS) -> dict[str, Any]:
    """Model by model and moment by moment, the family against the market on the rows both have: log loss of each, their difference with its
    standard error, and the same for each market key."""
    found = pairs(graded, fair, min_books=min_books)
    by_model: dict[str, dict[str, list[Pair]]] = defaultdict(lambda: defaultdict(list))
    by_key: dict[tuple[str, str, str], list[Pair]] = defaultdict(list)
    for p in found:
        by_model[p.model][p.ref].append(p)
        by_key[(p.model, p.ref, p.key)].append(p)
    models: dict[str, Any] = {}
    for model, refs in sorted(by_model.items()):
        entry: dict[str, Any] = {ref: _block(members) for ref, members in sorted(refs.items())}
        entry["by_key"] = [{"key": key, "ref": ref, **_block(members)} for (m, ref, key), members in sorted(by_key.items()) if m == model]
        models[model] = entry
    return {"min_books": min_books, "references": [r for r, _ in REFERENCES], "models": models}


def render(report: Mapping[str, Any], *, min_rows: int = 50) -> str:
    """The comparison as text, model by model."""
    if not report["models"]:
        return f"  against the market: no graded row has a consensus of {report['min_books']}+ books on a line both can be read at"
    lines = [f"against the market (the books' own probabilities, margin removed, {report['min_books']}+ books; "
             "market minus model: positive means the model was better):"]
    for model, entry in report["models"].items():
        for ref in report["references"]:
            if ref in entry:
                b = entry[ref]
                lines.append(f"  {model} {ref:<5}: {b['n']} rows of {b['fixtures']} matches - log loss model {b['log_loss_model']:.4f}, market "
                             f"{b['log_loss_market']:.4f}, market minus model {b['market_minus_model']:+.4f} ± {b['se']:.4f}")
        for x in entry["by_key"]:
            if x["n"] >= min_rows and x["ref"] == "close":
                lines.append(f"      {x['key']:<16} close  n {x['n']:>5}  model said {x['mean_p_model'] * 100:5.1f} %  market {x['mean_p_market'] * 100:5.1f} %  "
                             f"happened {x['observed'] * 100:5.1f} %  market minus model {x['market_minus_model']:+.4f} ± {x['se']:.4f}")
    return "\n".join(lines)
