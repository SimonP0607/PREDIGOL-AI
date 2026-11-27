"""RP-9.6 on a real database: the finished matches and the last Shin consensus of the Over 2.5 as EXP-E6 reads them (the streak of ten out of the real history,
the consensus before kick-off with three books or more, a quarantined match left out), and the experiment as the launcher sees it."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from scripts import exp_run

from fbi.research import exp_conditions, exp_e6

from .conftest import Seed
from .knowledge_world import World

pytestmark = pytest.mark.integration

FIRST = datetime(2026, 9, 1, 18, tzinfo=UTC)
FAR = datetime(2100, 1, 1, tzinfo=UTC)


def consensus(w: World, fixture: int, kickoff: datetime, p: float, *, books: int = 4, hours_before: int = 3) -> None:
    w.cur.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, n_bookmakers, overround, best_odds, "
                  "best_bookmaker_id) VALUES (%s, 'OU', 'Over', 2.5, %s, 'shin', %s, %s, 1.05, 1.9, %s)",
                  (fixture, kickoff - timedelta(hours=hours_before), p, books, w.seed.bookmaker_id))


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


def ten_wins_then_a_match(w: World) -> int:
    """Team 0 wins ten in a row (2-0, against teams 1 to 3 in turn) and then plays an eleventh with a consensus: its fixture id."""
    for i in range(10):
        w.match(FIRST + timedelta(days=7 * i), home=0, away=1 + i % 3, goals=(2, 0))
    kick = FIRST + timedelta(days=7 * 10)
    fid = w.match(kick, home=0, away=1, goals=(3, 1))
    consensus(w, fid, kick, 0.55)
    return fid


def test_the_streak_is_read_out_of_the_history_and_the_consensus_is_the_last_one_before_the_kick_off(db: psycopg.Connection[Any], world: World) -> None:
    fid = ten_wins_then_a_match(world)
    kick = FIRST + timedelta(days=70)
    world.cur.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, n_bookmakers, overround, best_odds, "
                      "best_bookmaker_id) VALUES (%s, 'OU', 'Over', 2.5, %s, 'shin', 0.70, 4, 1.05, 1.9, %s)", (fid, kick - timedelta(hours=1), world.seed.bookmaker_id))
    world.cur.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, n_bookmakers, overround, best_odds, "
                      "best_bookmaker_id) VALUES (%s, 'OU', 'Over', 2.5, %s, 'shin', 0.10, 4, 1.05, 1.9, %s)", (fid, kick + timedelta(hours=1), world.seed.bookmaker_id))
    matches = exp_e6.load(db, until=FAR)
    assert len(matches) == 11 and matches[-1].fixture == fid and matches[-1].q_over == pytest.approx(0.70), "the one after the kick-off does not exist for the match"
    found = exp_e6.cases(matches)
    assert [c.fixture for c in found] == [fid] and set(found[0].types) == {exp_e6.WINS, exp_e6.FEW}
    assert found[0].residual == pytest.approx(1.0 - 0.70)
    assert found[0].day == kick.date()


def test_a_consensus_of_two_books_is_not_a_consensus_and_a_quarantined_match_is_not_read(db: psycopg.Connection[Any], world: World) -> None:
    for i in range(10):
        world.match(FIRST + timedelta(days=7 * i), home=0, away=1 + i % 3, goals=(2, 0))
    kick = FIRST + timedelta(days=70)
    thin = world.match(kick, home=0, away=1, goals=(1, 0))
    consensus(world, thin, kick, 0.5, books=2)
    bad_kick = kick + timedelta(days=7)
    bad = world.match(bad_kick, home=0, away=2, goals=(1, 0))
    consensus(world, bad, bad_kick, 0.5)
    db.execute("INSERT INTO analytics.fixture_validation (fixture_id, state, rule_version, validated_at) VALUES (%s, 'QUARANTINED', 'test', now())", (bad,))
    matches = {m.fixture: m for m in exp_e6.load(db, until=FAR)}
    assert thin in matches and matches[thin].q_over is None, "two books: the match is read, with no consensus"
    assert bad not in matches
    assert exp_e6.cases(list(matches.values())) == []


def test_the_experiment_registers_from_the_launcher_script_and_is_not_due_before_its_sample(db: psycopg.Connection[Any], world: World) -> None:
    ten_wins_then_a_match(world)
    exp_conditions.unregister("EXP-E6")
    try:
        exp_run.load_plugins()
        state = exp_conditions.check(db, "EXP-E6", at=FAR, model_code="code")
        assert (state.due, state.code, state.required) == (False, "sample", 500)
        assert state.sample == 1 and exp_e6.count(db, date(2026, 11, 26)) == 1
    finally:
        for key in ("EXP-E1", "EXP-E3", "EXP-E6", "EXP-E7"):
            exp_conditions.unregister(key)
