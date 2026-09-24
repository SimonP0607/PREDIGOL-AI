"""Everything a backtest reads, loaded once."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg
from psycopg.rows import tuple_row

from fbi.features.data import MatchRecord, load_matches
from fbi.features.store import load_feature_matrix

PRICE_BOOKMAKERS = ("pinnacle", "AVG", "MAX", "bet365")


@dataclass(frozen=True, slots=True)
class MarketTriplet:
    p_home: float
    p_draw: float
    p_away: float
    overround: float


@dataclass
class BacktestData:
    matches: list[MatchRecord]
    features: dict[int, dict[str, float | None]]
    feature_hash: dict[int, str]
    feature_cutoff: dict[int, datetime]
    market: dict[str, dict[int, MarketTriplet]]
    """baseline key ('pinnacle/closing/shin', ...) -> fixture_id -> de-vigged 1X2"""
    prices: dict[str, dict[int, dict[str, float]]]
    """'pinnacle/closing/1X2' or 'pinnacle/closing/OU2.5' -> fixture_id -> selection -> decimal odds"""
    price_source: str = "football-data.co.uk"

    def price(self, key: str, fixture_id: int, selection: str) -> float | None:
        return self.prices.get(key, {}).get(fixture_id, {}).get(selection)


def load_backtest_data(conn: psycopg.Connection, *, feature_version: str) -> BacktestData:
    matches = load_matches(conn)
    matrix = load_feature_matrix(conn, version=feature_version)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT DISTINCT ON (fixture_id) fixture_id, input_hash FROM features.feature_sets "
            "WHERE feature_version = %s ORDER BY fixture_id, n_inputs DESC, generated_at DESC, id DESC",
            (feature_version,),
        )
        hashes = {int(a): str(b) for a, b in cur.fetchall()}
        cur.execute(
            "SELECT fixture_id, bookmaker_code, price_kind, devig_method, p_home, p_draw, p_away, overround "
            "FROM analytics.market_baseline WHERE market_key = '1X2'"
        )
        market: dict[str, dict[int, MarketTriplet]] = {}
        for fid, bm, kind, method, ph, pd, pa, ovr in cur.fetchall():
            market.setdefault(f"{bm}/{kind}/{method}", {})[int(fid)] = MarketTriplet(
                float(ph), float(pd), float(pa), float(ovr))
        cur.execute(
            "SELECT fixture_id, bookmaker_code, price_kind, market_key, line, selection, odds_decimal "
            "FROM market.historical_odds WHERE bookmaker_code = ANY(%s) "
            "AND (market_key = '1X2' OR (market_key = 'OU' AND line = 2.5))",
            (list(PRICE_BOOKMAKERS),),
        )
        prices: dict[str, dict[int, dict[str, float]]] = {}
        for fid, bm, kind, mk, line, sel, odds in cur.fetchall():
            key = f"{bm}/{kind}/{mk}" if mk == "1X2" else f"{bm}/{kind}/OU{float(line):g}"
            prices.setdefault(key, {}).setdefault(int(fid), {})[str(sel)] = float(odds)
    return BacktestData(matches, {k: v[1] for k, v in matrix.items()}, hashes,
                        {k: v[0] for k, v in matrix.items()}, market, prices)
