"""REVIEW PREDIGOL (11 Oct 2026), point 14: "Ya empezaron hoy" has its own filters and pages - so its list comes
apart from the list of matches still to come, unfiltered (GET /picks/started)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg

from fbi.api.services.product import picks_board, started_board
from fbi.picks.daily import build_daily_sets

from .conftest import Seed
from .test_daily_records import AT, World

KO = AT + timedelta(hours=2)


def test_the_started_picks_come_unfiltered_and_apart(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    f1 = w.fixtures["F1"]
    moment = KO + timedelta(minutes=60)
    db.execute("UPDATE core.fixtures SET status_short = '2H', status_group = 'live' WHERE id = %s", (f1,))
    started = started_board(db, include_shadow=False, at=moment)
    assert started.status.value == "ok"
    assert [s.pick_id for s in started.data] == [w.picks["F1"]]
    # the board's own list is filtered by the filters of the matches still to come; this one is not
    board = picks_board(db, include_shadow=False, competition_id=None, market="BTTS", min_odds=None, max_odds=None,
                        hours=24, at=moment).data
    assert board is not None and board.started == [], "a market filter above empties the board's started list"
    assert len(started_board(db, include_shadow=False, at=moment).data) == 1, "...but never this one"


def test_nothing_started_is_empty_with_its_reason(db: psycopg.Connection[Any], seed: Seed) -> None:
    env = started_board(db, include_shadow=False, at=AT - timedelta(days=30))
    assert (env.status.value, env.reason, env.data) == ("empty", "no_started_picks", [])
