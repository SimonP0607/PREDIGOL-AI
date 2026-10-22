"""Plan F0, defect 7, on a real database: ONE definition of CLV, in every place that writes it.

The same price, taken at 2.10, and the same closing references - the Shin consensus of the last snapshot before kick-off
(0.47 fair; an earlier one at 0.50 and one after kick-off at 0.99 must not count) and the same bookmaker's final
pre-match price (2.00) - give the same two numbers wherever they are computed:

    CLV          2.10 x 0.47 - 1 = -0.013     picks.pick_line_value.lv_devigged (SQL), intel.decision_outcomes.clv,
                                              the AI shadow report's clv, the research pick audit, pm-v2's Facts.clv
    price move   2.10 / 2.00 - 1 = +0.05      picks.pick_line_value.lv_raw (SQL), the AI shadow report's price_move,
                                              pm-v2's Facts.price_move (and its stored column)

The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai import shadow
from fbi.ai.pick_postmortem import Facts
from fbi.intel import outcomes
from fbi.market import closing_value
from fbi.picks.fast_settlement import fill_line_value
from fbi.research.pick_audit import AUDIT_SQL, audited

from .conftest import Seed
from .helpers import scalar
from .test_intel import AT, IntelWorld

ODDS = Decimal("2.10")
CLOSE_ODDS = Decimal("2.00")
P_CLOSE = Decimal("0.47")
KICKOFF = AT + timedelta(hours=5)


def _world(db: psycopg.Connection[Any], seed: Seed) -> tuple[IntelWorld, int, int]:
    """One Over 2.5 pick at 2.10, played and won, with its closing references."""
    w = IntelWorld(db, seed)
    fid = w.fixture(KICKOFF)
    pick = w.pick(fid, "OU", "Over", "2.5", p_model=0.60, p_market=0.50, odds=float(ODDS), created=AT)
    w.consensus(fid, "OU", "Over", "2.5", p_fair=0.50, best=2.05, as_of=KICKOFF - timedelta(hours=3))
    w.consensus(fid, "OU", "Over", "2.5", p_fair=float(P_CLOSE), best=2.05, as_of=KICKOFF - timedelta(minutes=5))
    w.consensus(fid, "OU", "Over", "2.5", p_fair=0.99, best=1.01, as_of=KICKOFF + timedelta(minutes=5))
    db.execute("INSERT INTO market.final_prematch_odds (fixture_id, bookmaker_id, market_key, selection, line, "
               "odds_decimal, provider_update_at, minutes_to_ko, fetched_at, payload_hash) "
               "VALUES (%s, %s, 'OU', 'Over', 2.5, %s, %s, 10, %s, %s)",
               (fid, seed.bookmaker_id, CLOSE_ODDS, KICKOFF - timedelta(minutes=10), KICKOFF + timedelta(hours=1),
                seed.payload_hash))
    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fid,))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 2, 1)", (fid,))
    w.settle(pick, True, KICKOFF + timedelta(hours=2))
    return w, fid, pick


def test_the_same_price_and_close_give_the_same_clv_in_every_place(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, fid, pick = _world(db, seed)
    clv, move = closing_value.clv(ODDS, P_CLOSE), closing_value.price_move(ODDS, CLOSE_ODDS)
    assert clv == Decimal("-0.0130") and move == Decimal("0.05"), "the numbers the rest of the test holds everything to"

    # picks.pick_line_value: lv_devigged is the CLV, lv_raw the price move (the SQL twins of the two functions)
    assert fill_line_value(db, at=KICKOFF + timedelta(hours=7)) == 1
    lv = db.execute("SELECT lv_raw, lv_devigged FROM picks.pick_line_value WHERE pick_id = %s", (pick,)).fetchone()
    assert lv == (move, clv)

    # intel.decision_outcomes.clv (outcome-v1)
    db.execute("INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, "
               "selection, line, pick_id, model_name, odds, p_model, p_cal, p_market, filters, state, context_status, "
               "input_hash) VALUES ('decision-v1', %s, 'T-3h', %s, %s, 'OU', 'Over', 2.5, %s, 'dixon_coles', %s, 0.60, "
               "0.60, 0.50, '[]', 'INVESTIGACION', 'PENDING', 'clv-single')",
               (KICKOFF - timedelta(hours=3), fid, KICKOFF, pick, ODDS))
    assert outcomes.settle_decisions(db, at=KICKOFF + timedelta(hours=3)) == 1
    stored = db.execute("SELECT clv, close_p_fair FROM intel.decision_outcomes").fetchone()
    assert stored == (clv, P_CLOSE), "the last consensus BEFORE kick-off: not the earlier one, not the one after"

    # the research pick audit
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(AUDIT_SQL)
        picks = audited(list(cur.fetchall()))
    assert len(picks) == 1 and picks[0].clv == pytest.approx(float(clv))

    # the AI shadow report: one review of the same selection, before kick-off
    db.execute("INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, odds, bookmaker_id, "
               "p_model, p_market, engine, engine_version, input_hash, decision, confidence, output, mode, status) "
               "VALUES (%s, %s, 'OU', 'Over', 2.5, %s, %s, 0.60, 0.50, 'combined', 'rules-review-v1+none', 'x', "
               "'APPROVE', 0.7, '{}'::jsonb, 'shadow', 'ok')", (KICKOFF - timedelta(hours=1), fid, ODDS, seed.bookmaker_id))
    items = shadow.load(db, engine="combined", since=AT, until=KICKOFF + timedelta(days=1))
    assert len(items) == 1 and items[0].p_close == float(P_CLOSE) and items[0].close == float(CLOSE_ODDS)
    arm = shadow.metrics(items)
    assert arm["clv"] == round(float(clv), 4) and arm["n_clv"] == 1
    assert arm["price_move"] == round(float(move), 4) and arm["n_price_move"] == 1

    # the post-mortem by selection, from the same facts
    f = Facts(settled="win", decision="APPROVE", p_model=0.60, p_market=0.50, p_close=float(P_CLOSE), odds=float(ODDS),
              close_odds=float(CLOSE_ODDS))
    assert f.clv == round(float(clv), 4) and f.price_move == round(float(move), 4)
    _ = w


def test_a_post_mortem_row_reads_with_its_clv_and_its_price_move_apart(db: psycopg.Connection[Any],
                                                                      seed: Seed) -> None:
    """The admin's list: ``clv`` is derived from the odds and the closing probability the row stores, ``price_move`` is the
    stored column (which rows written before clv-v1 call ``clv``). A row from before holds a price move and is never taken
    for a CLV."""
    from fbi.api.services.ai_v2 import postmortems

    db.execute("INSERT INTO ai.pick_postmortems (fixture_id, market_key, selection, line, created_at, version, roles, "
               "settled, verdict, odds, close_odds, clv, answers) VALUES (%s, 'OU', 'Over', 2.5, now(), 'pm-test', "
               "'{shadow}', 'win', 'approved_won', %s, %s, %s, %s)",
               (seed.fixture_id, ODDS, CLOSE_ODDS, closing_value.price_move(ODDS, CLOSE_ODDS),
                Jsonb({"model": {"data": {"p_close": float(P_CLOSE)}},
                       "odds_moved": {"answer": "a favor", "data": {"clv": 0.05, "close_odds": 2.0}}})))
    db.execute("INSERT INTO ai.pick_postmortems (fixture_id, market_key, selection, line, created_at, version, roles, "
               "settled, verdict, odds, close_odds, clv, answers) VALUES (%s, 'OU', 'Under', 2.5, now(), 'pm-test', "
               "'{shadow}', 'win', 'approved_won', %s, %s, %s, %s)",
               (seed.fixture_id, ODDS, CLOSE_ODDS, closing_value.price_move(ODDS, CLOSE_ODDS), Jsonb({})))
    rows = {r.selection: r for r in postmortems(db, fixture_id=seed.fixture_id).data}
    over, under = rows["Over"], rows["Under"]
    assert over.price_move == Decimal("0.0500") and over.clv == Decimal("-0.0130")
    assert under.price_move == Decimal("0.0500") and under.clv is None, "no closing probability stored: no CLV"
    assert scalar(db.execute("SELECT count(*) FROM ai.pick_postmortems")) == 2
