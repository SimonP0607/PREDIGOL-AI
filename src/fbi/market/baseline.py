"""The market baseline: de-vigged 1X2 probabilities per fixture.

A model is only interesting if it knows something the market does not. So the
first number any model is compared with is the market's own - margin removed
by a named method, from a named bookmaker (or the market average), at a named
price kind. Pinnacle's closing price is the conventional sharp reference; the
market average is the broad one; pre-closing is what was known days earlier.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

import psycopg
from psycopg.rows import tuple_row

from fbi.core.errors import InvalidOddsError
from fbi.domain.market_probability import DevigMethod, devig
from fbi.domain.odds import DecimalOdds

METHODS = (DevigMethod.PROPORTIONAL, DevigMethod.SHIN, DevigMethod.POWER)


@dataclass(frozen=True, slots=True)
class BaselineRow:
    fixture_id: int
    source: str
    bookmaker_code: str
    price_kind: str
    method: str
    p_home: float
    p_draw: float
    p_away: float
    overround: float


def baseline_from_prices(
    fixture_id: int, source: str, bookmaker: str, kind: str, home: Decimal, draw: Decimal, away: Decimal
) -> list[BaselineRow]:
    """All three methods for one triplet. A triplet with no margin (sum of
    1/odds <= 1 - a data error, or a best-price composite) yields nothing."""
    odds = {"Home": DecimalOdds(home), "Draw": DecimalOdds(draw), "Away": DecimalOdds(away)}
    out: list[BaselineRow] = []
    for m in METHODS:
        try:
            fair = devig(odds, m)
        except InvalidOddsError:
            return []
        out.append(BaselineRow(
            fixture_id, source, bookmaker, kind, m.value,
            fair["Home"].probability.value, fair["Draw"].probability.value, fair["Away"].probability.value,
            fair["Home"].overround,
        ))
    return out


def compute_from_historical(conn: psycopg.Connection, *, source: str, bookmakers: tuple[str, ...]) -> list[BaselineRow]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT fixture_id, bookmaker_code, price_kind, selection, odds_decimal FROM market.historical_odds "
            "WHERE source = %s AND market_key = '1X2' AND bookmaker_code = ANY(%s)",
            (source, list(bookmakers)),
        )
        trios: dict[tuple[int, str, str], dict[str, Decimal]] = defaultdict(dict)
        for fid, bm, kind, sel, odds in cur.fetchall():
            trios[(int(fid), str(bm), str(kind))][str(sel)] = Decimal(odds)
    rows: list[BaselineRow] = []
    for (fid, bm, kind), t in trios.items():
        if {"Home", "Draw", "Away"} <= set(t):
            rows.extend(baseline_from_prices(fid, source, bm, kind, t["Home"], t["Draw"], t["Away"]))
    return rows


def write_baseline(conn: psycopg.Connection, rows: list[BaselineRow]) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO analytics.market_baseline (fixture_id, source, bookmaker_code, price_kind, market_key, "
            "devig_method, p_home, p_draw, p_away, overround) VALUES (%s,%s,%s,%s,'1X2',%s,%s,%s,%s,%s) "
            "ON CONFLICT (fixture_id, source, bookmaker_code, price_kind, market_key, devig_method) DO UPDATE SET "
            "p_home = EXCLUDED.p_home, p_draw = EXCLUDED.p_draw, p_away = EXCLUDED.p_away, "
            "overround = EXCLUDED.overround, computed_at = now()",
            [(r.fixture_id, r.source, r.bookmaker_code, r.price_kind, r.method,
              round(r.p_home, 6), round(r.p_draw, 6), round(1.0 - round(r.p_home, 6) - round(r.p_draw, 6), 6),
              round(r.overround, 5)) for r in rows],
        )
    return len(rows)
