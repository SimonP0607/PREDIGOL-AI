"""What the probability view reads (plan PICKS, F3, option B): the models' newest numbers and the market's fresh consensus, as of a moment.

Read-only and clock-free: the moment is an argument, so the same database gives the same answer to a writer running now and to a replay of
a past decision. It reads ``models.predictions`` and ``market.market_consensus`` and nothing else - it does not name the forecast table
(``tests/unit/test_forecast_isolation.py``) - and ``view_at`` runs ``market_view.forecast_market`` over them, which is what the Match Center
states and what decision-v2 (shadow) judges.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.forecasting.market_view import (
    MARKETS,
    MAX_MARKET_AGE,
    MarketForecast,
    Row,
    Source,
    forecast_market,
)
from fbi.intel.calibration import CalibrationState

SOURCES_SQL = """
WITH newest AS (
    SELECT DISTINCT ON (p.fixture_id, r.name) p.fixture_id, r.name AS model, p.model_version_id, p.data_cutoff_ts
      FROM models.predictions p JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry r ON r.id = v.model_id
     WHERE p.fixture_id = ANY(%(ids)s) AND p.backtest_session_id IS NULL AND p.data_cutoff_ts <= %(at)s
     ORDER BY p.fixture_id, r.name, p.data_cutoff_ts DESC, p.model_version_id DESC
)
SELECT n.model, p.fixture_id, p.model_version_id, p.data_cutoff_ts, p.market_key, p.selection, p.line,
       p.p_raw::float8 AS p, p.p_lo::float8 AS lo, p.p_hi::float8 AS hi, COALESCE(p.p_push, 0)::float8 AS push,
       p.feature_set_hash
  FROM models.predictions p JOIN newest n ON n.fixture_id = p.fixture_id AND n.model_version_id = p.model_version_id
       AND n.data_cutoff_ts = p.data_cutoff_ts
 WHERE p.fixture_id = ANY(%(ids)s) AND p.backtest_session_id IS NULL
   AND (p.market_key, p.line) IN (SELECT c.m, c.l FROM unnest(%(core_markets)s::text[], %(core_lines)s::numeric[]) AS c(m, l))
"""
"""The newest real-time forecast of each model for each match, restricted to the core markets. ``p_raw`` is the model's own
number: ``p_calibrated`` is the same today, but ``p_raw`` is the one that means it."""

CONSENSUS_SQL = """
SELECT DISTINCT ON (m.fixture_id, m.market_key, m.selection, m.line)
       m.fixture_id, m.market_key, m.selection, m.line, m.p_fair::float8 AS p_fair, m.as_of
  FROM market.market_consensus m
 WHERE m.fixture_id = ANY(%(ids)s) AND m.devig_method = 'shin' AND m.as_of <= %(at)s AND m.as_of >= %(since)s
   AND m.p_fair > 0 AND m.p_fair < 1
   AND (m.market_key, m.line) IN (SELECT c.m, c.l FROM unnest(%(core_markets)s::text[], %(core_lines)s::numeric[]) AS c(m, l))
 ORDER BY m.fixture_id, m.market_key, m.selection, m.line, m.as_of DESC
"""


def _core() -> dict[str, list[Any]]:
    """The markets that are forecast, as the two parallel arrays the queries unnest (a row list cannot be a parameter)."""
    keys = sorted(MARKETS)
    return {"core_markets": [m for m, _ in keys], "core_lines": [line for _, line in keys]}


def read_sources(conn: psycopg.Connection[Any], ids: list[int], at: datetime
                  ) -> dict[tuple[int, str, Decimal], dict[str, list[Row]]]:
    out: dict[tuple[int, str, Decimal], dict[str, list[Row]]] = defaultdict(lambda: defaultdict(list))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SOURCES_SQL, {"ids": ids, "at": at, **_core()})
        for r in cur.fetchall():
            line = Decimal(r["line"])
            if (str(r["market_key"]), line) not in MARKETS:
                continue
            out[(int(r["fixture_id"]), str(r["market_key"]), line)][str(r["model"])].append(Row(
                str(r["selection"]),
                Source(str(r["model"]), int(r["model_version_id"]), r["data_cutoff_ts"], str(r["feature_set_hash"]),
                       float(r["p"]), None if r["lo"] is None else float(r["lo"]),
                       None if r["hi"] is None else float(r["hi"]), float(r["push"]))))
    return out


def read_consensus(conn: psycopg.Connection[Any], ids: list[int], at: datetime
                    ) -> dict[tuple[int, str, Decimal], dict[str, tuple[float, datetime]]]:
    out: dict[tuple[int, str, Decimal], dict[str, tuple[float, datetime]]] = defaultdict(dict)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CONSENSUS_SQL, {"ids": ids, "at": at, "since": at - MAX_MARKET_AGE, **_core()})
        for r in cur.fetchall():
            out[(int(r["fixture_id"]), str(r["market_key"]), Decimal(r["line"]))][str(r["selection"])] = (
                float(r["p_fair"]), r["as_of"])
    return out


def view_at(conn: psycopg.Connection[Any], fixture_ids: list[int], *, at: datetime, cal: CalibrationState
            ) -> dict[tuple[int, str, Decimal], MarketForecast]:
    """The view of every core market of these matches as of ``at``: one model, one cut-off, a complete set that adds up to one, calibrated
    only where a champion exists and its price is fresh. The matches' own fitness (data class, quarantine) is the caller's to apply."""
    if not fixture_ids:
        return {}
    sources = read_sources(conn, fixture_ids, at)
    consensus = read_consensus(conn, fixture_ids, at)
    out: dict[tuple[int, str, Decimal], MarketForecast] = {}
    for key in sorted(sources):
        fixture_id, market_key, line = key
        found = forecast_market(fixture_id, market_key, line, sources[key], cal, consensus.get(key, {}))
        if found is not None:
            out[key] = found
    return out
