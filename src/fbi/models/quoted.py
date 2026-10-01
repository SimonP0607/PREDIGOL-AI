"""Price the lines the market actually quotes, and only those.

The goal model prices seven fixed rows. The capture stores far more: 26 distinct
Over/Under lines, 45 Asian Handicap lines, and Double Chance, none of which had
a model number to compare against.

The lines come from the stored prices rather than from a grid. Pricing Asian
Handicap -3.75 for a match nobody quotes it on produces a number with nothing to
compare it to, and the whole point of the model is Model VERSUS Market: a
prediction is useful exactly where there is a price opposite it. So this asks
market.odds_snapshots what was quoted, per fixture, and prices that.

NO INTERVALS ON THESE ROWS, AND THAT IS DELIBERATE
--------------------------------------------------
The seven fixed rows carry p_lo and p_hi from 200 parameter draws through the
same projection. Doing that for every quoted line would mean projecting 200
matrices across up to 70 lines per fixture. Until that is worth its cost, these
rows leave the interval NULL rather than carrying a copy of the point estimate
dressed up as a bound - which would read as certainty the model never claimed.
``picks.value.assess`` already treats a missing lower bound as "no uncertainty
adjustment available", so nothing downstream has to special-case it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import psycopg
import structlog
from numpy.typing import NDArray
from psycopg.rows import tuple_row

from fbi.models.lines import asian_handicap, double_chance, over_under

log = structlog.get_logger(__name__)

__all__ = ["LinePrediction", "QuotedLines", "price_quoted_lines", "quoted_lines"]

PRICED_MARKETS: tuple[str, ...] = ("AH", "OU", "DC")
"""The markets this module adds. 1X2 and BTTS are already in MARKET_ROWS, and
OU 2.5 is too - the deduplication happens on the primary key, which includes the
line, so a repeated row is refused by the database rather than double counted."""


@dataclass(frozen=True, slots=True)
class LinePrediction:
    market_key: str
    selection: str
    line: Decimal
    p_win: float
    p_push: float


QuotedLines = dict[int, list[tuple[str, str, Decimal]]]
"""fixture id -> the (market, selection, line) triples quoted for it."""


def quoted_lines(
    conn: psycopg.Connection,
    fixture_ids: Sequence[int],
    *,
    markets: Sequence[str] = PRICED_MARKETS,
    since_days: int = 30,
) -> QuotedLines:
    """What the market has quoted for these fixtures, from the stored prices.

    Both series are deliberately NOT mixed here: this reads
    market.odds_snapshots only. An in-play line is not a pre-match line, and a
    pre-match forecast must never be shaped by what the in-play book offered.
    """
    if not fixture_ids:
        return {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT DISTINCT fixture_id, market_key, selection, line "
            "FROM market.odds_snapshots "
            "WHERE fixture_id = ANY(%s) AND market_key = ANY(%s) "
            "  AND captured_at > now() - make_interval(days => %s)",
            (list(fixture_ids), list(markets), since_days),
        )
        out: QuotedLines = {}
        for fixture_id, market_key, selection, line in cur.fetchall():
            out.setdefault(int(fixture_id), []).append(
                (str(market_key), str(selection), Decimal(line))
            )
    for triples in out.values():
        triples.sort()
    return out


def price_quoted_lines(
    matrix: NDArray[np.float64], triples: Sequence[tuple[str, str, Decimal]]
) -> list[LinePrediction]:
    """One prediction per quoted triple, from the score matrix.

    A triple the model cannot price is skipped and logged, never guessed: an
    unknown selection on a known market means the provider's vocabulary moved,
    and a plausible-looking substitute is how the legacy system ended up with
    expected_goals of 108.
    """
    out: list[LinePrediction] = []
    for market_key, selection, line in triples:
        try:
            if market_key == "AH":
                outcome = asian_handicap(matrix, selection=selection, line=line)
            elif market_key == "OU":
                outcome = over_under(matrix, selection=selection, line=line)
            elif market_key == "DC":
                probs = double_chance(matrix)
                if selection not in probs:
                    raise ValueError(f"unknown Double Chance selection {selection!r}")
                out.append(
                    LinePrediction(market_key, selection, line, probs[selection], 0.0)
                )
                continue
            else:
                continue
        except ValueError as exc:
            log.warning(
                "lines.unpriceable",
                market=market_key,
                selection=selection,
                line=str(line),
                detail=str(exc),
            )
            continue
        out.append(
            LinePrediction(market_key, selection, line, outcome.win, outcome.push)
        )
    return out
