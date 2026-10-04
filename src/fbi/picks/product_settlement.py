"""Settling what the product shows: daily-set items, PrediGol's parlays, a user's picks and parlays.

Every single settles exactly as a pick does (``fbi.picks.settlement``: the regulation score,
quarter lines as two halves, a cancelled match void, postponed/abandoned/awarded left PENDING
for a human), at the price FROZEN on the record - the price at selection for PrediGol's
items, and for a user's pick the price they say they got, or else the price we showed when
they saved it. Profit is per unit staked.

A parlay follows its legs:

  LOST          a leg lost (or half-lost), whatever the others are still doing
  WON           every leg won
  PARTIAL_VOID  the others won and at least one leg was void or pushed: it pays at the odds of
                the winning legs only
  VOID          every leg void or pushed: the stake comes back
  ACTIVE        none of the above yet, and a leg has kicked off

No provider request; idempotent - a settled record is never settled again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.picks import settlement

ONE = Decimal(1)


def settle_single(r: dict[str, Any], odds: Decimal | None) -> settlement.Settlement:
    state = settlement.MatchState(r["status_short"], r["reg_goals_home"], r["reg_goals_away"],
                                  r.get("et_goals_home"), r.get("et_goals_away"))
    return settlement.settle(r["market_key"], r["selection"], Decimal(r["line"]), odds or Decimal("2"), ONE, state)


def parlay_outcome(legs: list[tuple[str, Decimal | None]]) -> tuple[str, Decimal | None] | None:
    """(status, profit per unit) once a parlay is decided, else None. ``legs``: (STATUS, odds)."""
    statuses = [s for s, _ in legs]
    if any(s in ("LOSS", "HALF_LOSS") for s in statuses):
        return "LOST", Decimal(-1)
    if any(s == "PENDING" for s in statuses):
        return None
    if all(s in ("VOID", "PUSH") for s in statuses):
        return "VOID", Decimal(0)
    winning = [o for s, o in legs if s in ("WIN", "HALF_WIN")]
    if any(o is None for o in winning):
        payout = None
    else:
        payout = math.prod((o for o in winning if o is not None), start=ONE) - ONE
    partial = any(s in ("VOID", "PUSH", "HALF_WIN") for s in statuses)
    return ("PARTIAL_VOID" if partial else "WON"), (payout.quantize(Decimal("0.0001")) if payout is not None else None)


@dataclass
class ProductSettlementReport:
    items: int = 0
    parlay_legs: int = 0
    parlays: int = 0
    user_picks: int = 0
    user_parlay_legs: int = 0
    user_parlays: int = 0
    activated: int = 0
    sets_settled: int = 0
    pending_review: dict[str, int] = field(default_factory=dict)


SINGLES: dict[str, tuple[str, str, str]] = {
    # name: (select, key columns for the update, odds expression)
    "items": ("""
        SELECT i.set_id AS k1, i.rank AS k2, i.market_key, i.selection, i.line, i.odds AS price, f.status_short,
               r.reg_goals_home, r.reg_goals_away, r.et_goals_home, r.et_goals_away
          FROM picks.daily_set_items i JOIN core.fixtures f ON f.id = i.fixture_id
          LEFT JOIN core.fixture_results r ON r.fixture_id = i.fixture_id
         WHERE i.status = 'PENDING' AND f.kickoff_at <= %(at)s""",
              "UPDATE picks.daily_set_items SET status = %s, profit_units = %s, settled_at = %s "
              "WHERE set_id = %s AND rank = %s AND status = 'PENDING'", "price"),
    "parlay_legs": ("""
        SELECT l.parlay_id AS k1, l.leg_no AS k2, l.market_key, l.selection, l.line, l.odds AS price, f.status_short,
               r.reg_goals_home, r.reg_goals_away, r.et_goals_home, r.et_goals_away
          FROM picks.parlay_legs l JOIN core.fixtures f ON f.id = l.fixture_id
          LEFT JOIN core.fixture_results r ON r.fixture_id = l.fixture_id
         WHERE l.status = 'PENDING' AND f.kickoff_at <= %(at)s""",
                    "UPDATE picks.parlay_legs SET status = %s, settled_at = %s WHERE parlay_id = %s AND leg_no = %s "
                    "AND status = 'PENDING'", "price"),
    "user_picks": ("""
        SELECT u.id AS k1, NULL::int AS k2, u.market_key, u.selection, u.line, COALESCE(u.user_odds, u.odds) AS price,
               f.status_short, r.reg_goals_home, r.reg_goals_away, r.et_goals_home, r.et_goals_away
          FROM picks.user_picks u JOIN core.fixtures f ON f.id = u.fixture_id
          LEFT JOIN core.fixture_results r ON r.fixture_id = u.fixture_id
         WHERE u.status = 'PENDING' AND f.kickoff_at <= %(at)s""",
                   "UPDATE picks.user_picks SET status = %s, profit_units = %s, settled_at = %s "
                   "WHERE id = %s AND status = 'PENDING'", "price"),
    "user_parlay_legs": ("""
        SELECT l.user_parlay_id AS k1, l.leg_no AS k2, l.market_key, l.selection, l.line, l.odds AS price,
               f.status_short, r.reg_goals_home, r.reg_goals_away, r.et_goals_home, r.et_goals_away
          FROM picks.user_parlay_legs l JOIN core.fixtures f ON f.id = l.fixture_id
          LEFT JOIN core.fixture_results r ON r.fixture_id = l.fixture_id
         WHERE l.status = 'PENDING' AND f.kickoff_at <= %(at)s""",
                         "UPDATE picks.user_parlay_legs SET status = %s, settled_at = %s WHERE user_parlay_id = %s "
                         "AND leg_no = %s AND status = 'PENDING'", "price"),
}

PARLAYS: dict[str, tuple[str, str, str]] = {
    "parlays": ("""
        SELECT p.id, p.status, min(f.kickoff_at) AS first_kickoff,
               array_agg(l.status ORDER BY l.leg_no) AS statuses, array_agg(l.odds ORDER BY l.leg_no) AS odds
          FROM picks.parlays p JOIN picks.parlay_legs l ON l.parlay_id = p.id JOIN core.fixtures f ON f.id = l.fixture_id
         WHERE p.status IN ('READY', 'ACTIVE') GROUP BY p.id, p.status""",
                "UPDATE picks.parlays SET status = %s, profit_units = %s, settled_at = %s WHERE id = %s",
                "UPDATE picks.parlays SET status = 'ACTIVE' WHERE id = %s AND status = 'READY'"),
    "user_parlays": ("""
        SELECT p.id, p.status, min(f.kickoff_at) AS first_kickoff,
               array_agg(l.status ORDER BY l.leg_no) AS statuses, array_agg(l.odds ORDER BY l.leg_no) AS odds
          FROM picks.user_parlays p JOIN picks.user_parlay_legs l ON l.user_parlay_id = p.id
          JOIN core.fixtures f ON f.id = l.fixture_id
         WHERE p.status IN ('READY', 'ACTIVE') GROUP BY p.id, p.status""",
                     "UPDATE picks.user_parlays SET status = %s, profit_units = %s, settled_at = %s WHERE id = %s",
                     "UPDATE picks.user_parlays SET status = 'ACTIVE' WHERE id = %s AND status = 'READY'"),
}


def settle_products(conn: psycopg.Connection[Any], *, at: datetime) -> ProductSettlementReport:
    report = ProductSettlementReport()
    for name, (select, update, _) in SINGLES.items():
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(select, {"at": at})
            rows = list(cur.fetchall())
        settled = 0
        with conn.cursor() as cur:
            for r in rows:
                price = Decimal(r["price"]) if r["price"] is not None else None
                result = settle_single(r, price)
                if not result.is_final:
                    if result.review_reason:
                        report.pending_review[name] = report.pending_review.get(name, 0) + 1
                    continue
                status = result.status.value.upper()
                profit = result.profit_units if price is not None else None
                if r["k2"] is None:
                    cur.execute(update, (status, profit, at, r["k1"]))
                elif "profit_units" in update:
                    cur.execute(update, (status, profit, at, r["k1"], r["k2"]))
                else:
                    cur.execute(update, (status, at, r["k1"], r["k2"]))
                settled += max(cur.rowcount, 0)
        setattr(report, name, settled)
    for name, (select, final, activate) in PARLAYS.items():
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(select)
            rows = list(cur.fetchall())
        done = 0
        with conn.cursor() as cur:
            for r in rows:
                legs = [(str(s), Decimal(o) if o is not None else None) for s, o in zip(r["statuses"], r["odds"],
                                                                                        strict=True)]
                outcome = parlay_outcome(legs)
                if outcome is not None:
                    cur.execute(final, (outcome[0], outcome[1], at, r["id"]))
                    done += max(cur.rowcount, 0)
                elif r["status"] == "READY" and r["first_kickoff"] <= at:
                    cur.execute(activate, (r["id"],))
                    report.activated += max(cur.rowcount, 0)
        setattr(report, name, done)
    with conn.cursor() as cur:
        cur.execute("UPDATE picks.daily_sets s SET status = 'SETTLED', updated_at = %s WHERE s.status = 'COMPLETE' "
                    "AND NOT EXISTS (SELECT 1 FROM picks.daily_set_items i WHERE i.set_id = s.id AND i.status = "
                    "'PENDING')", (at,))
        report.sets_settled = max(cur.rowcount, 0)
    return report
