"""What became of each decision - ``outcome-v1``: the result of its selection, the profit at the decision's own price
(one flat unit and the stake it was given), and its closing-line value.

    profit   win: odds - 1, half win: (odds - 1) / 2, push / void: 0, half loss: -1/2, loss: -1 (per unit)
    CLV      odds x the de-vigged (Shin) consensus probability of the last snapshot before kick-off - 1: the expected
             value of the price taken at the closing fair probability (``picks.pick_line_value.lv_devigged`` is the
             same measure for the shadow picks). The reference is the last captured consensus before kick-off, which
             has not been shown to BE the closing line: ``close_minutes_to_ko`` says how close it was.

Every decision gets an outcome, the rejected ones too: whether what was rejected would have won - and at what price
against the close - is how the filters themselves are judged. Written once (``intel.decision_outcomes`` is
append-only); a result corrected later by the provider would be a new decision's business, never a rewrite.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

VERSION = "outcome-v1"
BATCH = 20000

TODO_SQL = """
WITH todo AS (
    SELECT d.id, d.fixture_id, d.market_key, d.selection, d.line, d.odds, d.stake_units, d.kickoff_at,
           pr.result_status, pr.settled_at
      FROM intel.decisions d
      JOIN picks.pick_results pr ON pr.pick_id = d.pick_id
      LEFT JOIN intel.decision_outcomes o ON o.decision_id = d.id
     WHERE o.decision_id IS NULL AND pr.result_status <> 'pending' AND pr.settled_at <= %(at)s AND d.odds IS NOT NULL
     ORDER BY d.id
     LIMIT %(limit)s
)
SELECT t.*, cp.p_fair AS close_p_fair, cp.best_odds AS close_odds, cp.as_of AS close_as_of
  FROM todo t
  LEFT JOIN LATERAL (
      SELECT m.p_fair, m.best_odds, m.as_of FROM market.market_consensus m
       WHERE m.fixture_id = t.fixture_id AND m.market_key = t.market_key AND m.selection = t.selection
         AND m.line = t.line AND m.devig_method = 'shin' AND m.as_of < t.kickoff_at
       ORDER BY m.as_of DESC LIMIT 1) cp ON true
"""

PER_UNIT = {"win": None, "half_win": None, "push": Decimal(0), "void": Decimal(0), "half_loss": Decimal("-0.5"),
            "loss": Decimal(-1)}


def profit_per_unit(result: str, odds: Decimal) -> Decimal:
    if result == "win":
        return odds - 1
    if result == "half_win":
        return (odds - 1) / 2
    value = PER_UNIT.get(result)
    if value is None:
        raise ValueError(f"unknown result {result}")
    return value


def settle_decisions(conn: psycopg.Connection[Any], *, at: datetime, limit: int = BATCH) -> int:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TODO_SQL, {"at": at, "limit": limit})
        rows = cur.fetchall()
    n = 0
    with conn.cursor() as cur:
        for r in rows:
            odds = Decimal(r["odds"])
            unit = profit_per_unit(str(r["result_status"]), odds)
            close_p = r["close_p_fair"]
            clv = None if close_p is None else (odds * Decimal(close_p) - 1).quantize(Decimal("0.000001"))
            minutes = None if r["close_as_of"] is None else int((r["kickoff_at"] - r["close_as_of"]).total_seconds() // 60)
            cur.execute(
                "INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, "
                "profit_staked, close_p_fair, close_odds, close_as_of, close_minutes_to_ko, clv, version, computed_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (decision_id) DO NOTHING",
                (int(r["id"]), r["settled_at"], r["result_status"], unit.quantize(Decimal("0.0001")),
                 (unit * Decimal(r["stake_units"])).quantize(Decimal("0.0001")), close_p, r["close_odds"],
                 r["close_as_of"], minutes, clv, VERSION, at))
            n += max(cur.rowcount, 0)
    return n
