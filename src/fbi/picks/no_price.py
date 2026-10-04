"""MODEL_INTERESTING_NO_PRICE: what the model would need from a bookmaker we do not have.

Our users bet with Colombian operators that no source of ours prices. When a market has no
price at all, a pick is impossible - there is nothing to compare the model with - and
inventing or estimating a bookmaker's price is forbidden. What can be said honestly is the
model's own number: its probability, the fair odds that follow from it, and the MINIMUM odds
at which the current decision rule would accept the bet, computed from the pessimistic end
of the model's interval:

    min_odds = (1 + rule.min_ev) / p_low

A user who sees at least that price at their own bookmaker has, by the model's reckoning,
the edge the rule asks for. Rule ``no-price-watch-v1`` (versioned like the pick rules):

* the market is one of 1X2, Over/Under 2.5 and BTTS, and has no price at all because the
  provider was asked and had none (PRICE_UNAVAILABLE) or does not cover the competition
  (NOT_COVERED) - a price still PENDING is waited for, not replaced;
* the forecast is the newest real-time one of the watch model, made before now;
* one selection per market: the model's most likely outcome;
* MODEL_INTERESTING_NO_PRICE when ``min_odds`` falls inside the rule's odds band, so a
  bookmaker could plausibly offer it; otherwise the market stays PRICE_UNAVAILABLE with the
  model's view attached.

It is never a pick: it is not counted, settled as one, or shown among the picks, and while no
model version has beaten the market in its own backtest it is labelled evaluation mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.market.price_status import CORE_MARKETS, MarketPrice, PriceStatus, market_prices
from fbi.picks.rules import CURRENT_RULE, DecisionRule

RULE_VERSION = "no-price-watch-v1"
WATCH_MODEL = "dixon_coles"
"""The goals model prices all three core markets from one score matrix. The model choice moves
to the champion registry once one exists; no model has beaten the market yet."""
WATCHED = frozenset({PriceStatus.PRICE_UNAVAILABLE, PriceStatus.NOT_COVERED})


class WatchStatus(StrEnum):
    MODEL_INTERESTING_NO_PRICE = "MODEL_INTERESTING_NO_PRICE"
    PRICE_UNAVAILABLE = "PRICE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class NoPriceView:
    fixture_id: int
    market_key: str
    line: Decimal
    price_status: PriceStatus
    status: WatchStatus
    selection: str
    model: str
    model_version_id: int
    prediction_id: int
    data_cutoff_ts: datetime
    probability: Decimal
    p_low: Decimal
    fair_odds: Decimal
    min_odds: Decimal
    rule_version: str = RULE_VERSION
    evaluation_mode: bool = True


FORECASTS_SQL = """
WITH newest AS (
    SELECT DISTINCT ON (p.fixture_id) p.fixture_id, p.model_version_id, p.data_cutoff_ts
      FROM models.predictions p JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry m ON m.id = v.model_id
     WHERE p.fixture_id = ANY(%(ids)s) AND p.backtest_session_id IS NULL AND m.name = %(model)s
       AND p.data_cutoff_ts <= %(at)s
     ORDER BY p.fixture_id, p.data_cutoff_ts DESC, p.model_version_id DESC
)
SELECT p.id, p.fixture_id, p.model_version_id, p.market_key, p.selection, p.line, p.p_calibrated, p.p_lo,
       p.data_cutoff_ts
  FROM models.predictions p JOIN newest n ON n.fixture_id = p.fixture_id
       AND n.model_version_id = p.model_version_id AND n.data_cutoff_ts = p.data_cutoff_ts
 WHERE p.backtest_session_id IS NULL
"""


def _q(x: Decimal, places: str = "0.01") -> Decimal:
    return x.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def watch(conn: psycopg.Connection[Any], fixture_ids: list[int], *, at: datetime,
          rule: DecisionRule = CURRENT_RULE, model: str = WATCH_MODEL,
          prices: list[MarketPrice] | None = None) -> list[NoPriceView]:
    """The model's view of every unpriced core market of these fixtures."""
    prices = prices if prices is not None else market_prices(conn, fixture_ids, at=at)
    unpriced = {(p.fixture_id, p.market_key, p.line): p for p in prices if p.status in WATCHED}
    if not unpriced:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FORECASTS_SQL, {"ids": sorted({k[0] for k in unpriced}), "model": model, "at": at})
        rows = list(cur.fetchall())
    best: dict[tuple[int, str, Decimal], dict[str, Any]] = {}
    for r in rows:
        key = (int(r["fixture_id"]), str(r["market_key"]), Decimal(r["line"]))
        if key not in unpriced or r["p_calibrated"] is None:
            continue
        if key not in best or Decimal(r["p_calibrated"]) > Decimal(best[key]["p_calibrated"]):
            best[key] = r
    out: list[NoPriceView] = []
    for key, r in sorted(best.items(), key=lambda kv: (kv[0][0], [m for m, _ in CORE_MARKETS].index(kv[0][1]))):
        p = Decimal(r["p_calibrated"])
        p_low = Decimal(r["p_lo"]) if r["p_lo"] is not None else p
        if p <= 0 or p_low <= 0:
            continue
        min_odds = _q((1 + rule.min_ev) / p_low)
        status = (WatchStatus.MODEL_INTERESTING_NO_PRICE if rule.min_odds <= min_odds <= rule.max_odds
                  else WatchStatus.PRICE_UNAVAILABLE)
        out.append(NoPriceView(
            fixture_id=key[0], market_key=key[1], line=key[2], price_status=unpriced[key].status, status=status,
            selection=str(r["selection"]), model=model, model_version_id=int(r["model_version_id"]),
            prediction_id=int(r["id"]), data_cutoff_ts=r["data_cutoff_ts"], probability=_q(p, "0.0001"),
            p_low=_q(p_low, "0.0001"), fair_odds=_q(1 / p), min_odds=min_odds))
    return out
