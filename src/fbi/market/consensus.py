"""The live market consensus: de-vigged probabilities across the books WE captured.

One consensus per captured payload - the set of books the provider returned
in one response, at one instant. Each bookmaker's book is de-vigged on its
own (a book that is incomplete for the market is left out rather than
guessed, and so is a book with no margin - usually a stale or broken quote),
then the fair probabilities are averaged across bookmakers. The spread across
bookmakers is kept as ``dispersion``; the best price is kept with the
bookmaker that offered it, among the books that passed.

Only markets whose outcomes are known to be exclusive AND whose selections
pair unambiguously.

ASIAN HANDICAP IS PAIRED BY ITS OVERROUND, NOT BY A SIGN CONVENTION
-------------------------------------------------------------------
Pairing "Home -1" with the wrong "Away" line produces a confident, wrong
probability rather than an error, so this module refused the market entirely
until the pairing could be settled against real data. It now is - but not the
way it first appeared.

The convention is real: the stored line is the handicap that applies to the
stored selection, so one bet is (Home, h) with (Away, -h). Measured twice,
independently - pre-match repeats the home handicap on both rows and the
normaliser negates the away one, while /odds/live signs each row itself, and
both roads end at the same stored form.

But the provider offers SEVERAL handicap bets per book, and their stored lines
collide. For one fixture, one book, one instant, "Home 2.5" at 1.020 sits
beside "Away -2.5" at 11.000 AND "Away 2.5" at 1.020. Pairing on the sign alone
picked a partner from a different bet and produced two-way books devigging to
1.95 - a 95% margin, which no bookmaker has - and others below 1.0, which is
free money. 119 of 948 pairs were affected; 58 were above 1.50.

So the pairing is decided by the thing that cannot be faked: a real two-way
book's overround. Both candidates are tried and the believable one is taken;
when neither is believable the quote is not used for consensus at all. Its
price is still stored - nothing is discarded - it simply does not become a fair
probability on a guess.

Why an overround can carry that weight: measured over these same payloads, the
markets whose pairing is unambiguous come out at 1X2 1.081 (worst 1.122),
BTTS 1.081 (1.128), OU 1.083 (1.134) and DC 1.067 (1.102). A two-way book at
1.25 is already far outside anything the provider's own books do, and 87% of
Asian Handicap pairs sit at or below 1.15 before any filtering.

A DE-VIGGED TWO-WAY PROBABILITY IS CONDITIONAL ON THE BET BEING SETTLED
-----------------------------------------------------------------------
{Home, Away} at a handicap, or {Over, Under} at a whole line, de-vig to two
numbers that sum to 1 - but on a line that can push those two outcomes are not
everything that can happen. What comes out is therefore P(win | settled), not
P(win). The model stores P(win) and P(push) separately, so whoever compares the
two must divide: ``picks.engine`` does, and ``market_consensus.p_fair`` is
documented as conditional for this reason. 66% of the Asian Handicap series and
51% of the Over/Under series sit on lines where the distinction is not zero.

DOUBLE CHANCE SUMS TO TWO, NOT ONE
----------------------------------
Each of 1X, X2 and 12 covers two of the three outcomes, so a fair Double Chance
book sums to 2 and ``devig`` - which builds a probability distribution - cannot
be pointed at it. The three prices are mapped to the 1X2 book they imply, that
is de-vigged by the same Shin estimator as every other market, and the results
are added back up. The map is exact: with no margin, 1X + 12 - 1 is P(home).
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
"""Markets whose selections at ONE line are exclusive and exhaustive of the
settled outcomes."""

OPPOSITE_LINE: dict[str, tuple[str, str]] = {"AH": ("Home", "Away")}
"""Markets whose two sides are quoted at opposite lines: (Home, h) pairs with
(Away, -h). Measured - see the module docstring."""

MAX_TWO_WAY_BOOK = 1.25
"""The most margin a two-way book can plausibly carry.

Measured over our own payloads, on the markets whose pairing is unambiguous:
1X2 averages 1.081 and never exceeds 1.122, BTTS 1.081 / 1.128, Over/Under
1.083 / 1.134, Double Chance 1.067 / 1.102. 1.25 is generous against all of
them, and it is what tells a real Asian Handicap pair from two prices that
merely share a number - those reached 1.95, a 95% margin no bookmaker has.
"""

DOUBLE_CHANCE_SELECTIONS: tuple[str, ...] = ("1X", "X2", "12")

DC_TO_1X2: dict[str, tuple[str, str]] = {
    "Home": ("1X", "12"),
    "Draw": ("1X", "X2"),
    "Away": ("X2", "12"),
}
"""Which two Double Chance prices imply each 1X2 outcome. P(home) = 1X + 12 - 1
once the book sums to 2, and the same linear map applied to the raw implied
probabilities yields a 1X2 book carrying the same margin, which Shin can then
remove."""
METHODS = (DevigMethod.SHIN, DevigMethod.PROPORTIONAL, DevigMethod.POWER)

CONSENSUS_MARKETS: list[str] = [*EXCLUSIVE, *OPPOSITE_LINE, "DC"]
"""Every market this module can de-vig, so the snapshot query fetches the quotes
the builders will actually use. It was ``list(EXCLUSIVE)``, which is why adding
Asian Handicap and Double Chance to the builders alone would have changed
nothing: their prices were never read."""


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
            fairs, overrounds, used = _devig_across_books(complete, wanted, method)
            if not fairs:
                continue
            rows.extend(_rows_from(market, line, method, wanted, fairs, overrounds,
                                   used, complete))
    rows.extend(_handicap_rows(quotes, methods))
    rows.extend(_double_chance_rows(quotes, methods))
    return rows


def _devig_across_books(
    complete: dict[int, dict[str, Decimal]],
    wanted: Sequence[str],
    method: DevigMethod,
) -> tuple[list[dict[str, float]], list[float], list[int]]:
    """De-vig each book on its own, then report what passed.

    A book with no margin - usually a stale or broken quote - is left out
    rather than guessed at, which is why the three lists are returned together:
    the caller must average over the books that actually passed, not over all
    of them.
    """
    fairs: list[dict[str, float]] = []
    overrounds: list[float] = []
    used: list[int] = []
    for b, sel in sorted(complete.items()):
        try:
            fair = devig({s: DecimalOdds(sel[s]) for s in wanted}, method)
        except InvalidOddsError:
            continue
        fairs.append({s: fair[s].probability.value for s in wanted})
        overrounds.append(fair[wanted[0]].overround)
        used.append(b)
    return fairs, overrounds, used


def _rows_from(
    market: str,
    line: Decimal,
    method: DevigMethod,
    wanted: Sequence[str],
    fairs: Sequence[dict[str, float]],
    overrounds: Sequence[float],
    used: Sequence[int],
    prices: dict[int, dict[str, Decimal]],
    *,
    line_of: dict[str, Decimal] | None = None,
) -> list[ConsensusRow]:
    """One row per selection, averaged across the books that passed.

    ``line_of`` lets a market store each selection at its own line, which Asian
    Handicap needs: the two sides of one bet are quoted at opposite lines, so
    "Home -1" and "Away +1" are one book and two rows.
    """
    out: list[ConsensusRow] = []
    for s in wanted:
        ps = [f[s] for f in fairs]
        best_book = _best(used, prices, s)
        out.append(ConsensusRow(
            market, s, line if line_of is None else line_of[s], method.value,
            statistics.fmean(ps), len(fairs), statistics.fmean(overrounds),
            prices[best_book][s], best_book,
            statistics.pstdev(ps) if len(ps) > 1 else None,
        ))
    return out


def _believable_partner(
    home_odds: Decimal, candidates: Sequence[Decimal | None]
) -> Decimal | None:
    """The away price that makes a real two-way book with this home price.

    Tries each candidate and keeps the one whose raw book sits inside
    ``(1, MAX_TWO_WAY_BOOK]``; on a tie the tighter book wins, because a
    bookmaker's own margin is the thing being recognised. Returns None when
    neither candidate is believable - the quote then takes no part in the
    consensus, rather than contributing a probability derived from a guess.
    """
    best: tuple[float, Decimal] | None = None
    for away in candidates:
        if away is None or away <= 1:
            continue
        book = float(1 / home_odds + 1 / away)
        if not (1.0 < book <= MAX_TWO_WAY_BOOK):
            continue
        if best is None or book < best[0]:
            best = (book, away)
    return None if best is None else best[1]


def _handicap_rows(
    quotes: Sequence[BookQuote], methods: Sequence[DevigMethod]
) -> list[ConsensusRow]:
    """Asian Handicap, pairing each (Home, h) with its (Away, -h).

    The pairing is the whole difficulty of this market and the reason it was
    excluded until measured: getting it wrong produces a confident, wrong
    probability rather than an error. See the module docstring for the two
    independent measurements that settled it.

    What comes out is P(win | the bet is settled), because {Home, Away} at a
    handicap de-vig to two numbers summing to 1 while a whole or quarter line
    can also push. The consumer divides the model's P(win) by (1 - P(push))
    before comparing - see picks.engine.
    """
    home_sel, away_sel = OPPOSITE_LINE["AH"]
    home_quotes: dict[tuple[int, Decimal], Decimal] = {}
    away_quotes: dict[tuple[int, Decimal], Decimal] = {}
    for q in quotes:
        if q.market_key != "AH":
            continue
        if q.selection == home_sel:
            home_quotes[(q.bookmaker_id, q.line)] = q.odds
        elif q.selection == away_sel:
            away_quotes[(q.bookmaker_id, q.line)] = q.odds

    pairs: dict[Decimal, dict[int, dict[str, Decimal]]] = defaultdict(dict)
    for (book, home_line), home_odds in sorted(home_quotes.items()):
        partner = _believable_partner(
            home_odds,
            [away_quotes.get((book, -home_line)), away_quotes.get((book, home_line))],
        )
        if partner is None:
            continue
        pairs[home_line][book] = {home_sel: home_odds, away_sel: partner}

    wanted = (home_sel, away_sel)
    rows: list[ConsensusRow] = []
    for home_line, complete in sorted(pairs.items()):
        for method in methods:
            fairs, overrounds, used = _devig_across_books(complete, wanted, method)
            if not fairs:
                continue
            rows.extend(_rows_from(
                "AH", home_line, method, wanted, fairs, overrounds, used, complete,
                # Each side is stored at the line it is quoted at.
                line_of={home_sel: home_line, away_sel: -home_line},
            ))
    return rows


def _double_chance_rows(
    quotes: Sequence[BookQuote], methods: Sequence[DevigMethod]
) -> list[ConsensusRow]:
    """Double Chance, through the 1X2 book its three prices imply.

    A fair Double Chance book sums to 2, so ``devig`` - which builds a
    probability distribution - cannot be pointed at it. The linear map
    ``P(home) = 1X + 12 - 1`` applied to the RAW implied probabilities gives a
    three-outcome book carrying the same proportional margin, which the same
    Shin estimator removes; adding the fair outcomes back up in pairs returns
    the Double Chance probabilities.

    It uses the Double Chance prices rather than borrowing the 1X2 ones, so a
    book whose two markets disagree keeps disagreeing - that is information
    about the book, not noise to average away.

    A book implying a non-positive outcome probability is incoherent and is
    dropped, never clipped: clipping turns a broken quote into a confident
    number, which is the failure this whole module is built to avoid.
    """
    by_book: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for q in quotes:
        if q.market_key == "DC" and q.selection in DOUBLE_CHANCE_SELECTIONS:
            by_book[q.bookmaker_id][q.selection] = q.odds
    complete = {
        b: sel for b, sel in by_book.items()
        if set(sel) == set(DOUBLE_CHANCE_SELECTIONS)
    }
    if not complete:
        return []

    implied: dict[int, dict[str, Decimal]] = {}
    for b, sel in complete.items():
        raw = {s: 1.0 / float(sel[s]) for s in DOUBLE_CHANCE_SELECTIONS}
        half_book = sum(raw.values()) / 2.0
        outcomes = {
            name: raw[a] + raw[c] - half_book for name, (a, c) in DC_TO_1X2.items()
        }
        if any(v <= 0 for v in outcomes.values()):
            continue
        implied[b] = {k: Decimal(str(1.0 / v)) for k, v in outcomes.items()}

    if not implied:
        return []

    outcome_names = ("Home", "Draw", "Away")
    rows: list[ConsensusRow] = []
    for method in methods:
        fairs, overrounds, used = _devig_across_books(implied, outcome_names, method)
        if not fairs:
            continue
        for selection in DOUBLE_CHANCE_SELECTIONS:
            first, second = _outcomes_of(selection)
            ps = [f[first] + f[second] for f in fairs]
            best_book = _best(used, complete, selection)
            rows.append(ConsensusRow(
                "DC", selection, Decimal(0), method.value, statistics.fmean(ps),
                len(fairs), statistics.fmean(overrounds),
                complete[best_book][selection], best_book,
                statistics.pstdev(ps) if len(ps) > 1 else None,
            ))
    return rows


def _outcomes_of(selection: str) -> tuple[str, str]:
    """Which two 1X2 outcomes a Double Chance selection covers."""
    covers = {"1X": ("Home", "Draw"), "X2": ("Draw", "Away"), "12": ("Home", "Away")}
    return covers[selection]


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
             list(fixture_ids) if fixture_ids is not None else None, CONSENSUS_MARKETS),
        )
        groups: dict[tuple[int, str, datetime], list[BookQuote]] = defaultdict(list)
        for fid, ph, as_of, bm, mk, sel, line, odds in cur.fetchall():
            groups[(int(fid), str(ph), as_of)].append(BookQuote(int(bm), str(mk), str(sel), Decimal(line),
                                                                Decimal(odds)))
    written = 0
    for (fid, _, as_of), quotes in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][2])):
        written += write_consensus(conn, fid, as_of, consensus(quotes))
    return len(groups), written
