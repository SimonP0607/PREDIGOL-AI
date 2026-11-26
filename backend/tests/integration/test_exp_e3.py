"""RP-9.3 on a real database: the settled over/under decisions of corners and cards as EXP-E3 reads them (the last decision of each selection, the raw figure, the
market of the same line at the close, an Under read as the Over, one row per match and line, a push or a void left out)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import psycopg
import pytest
from scripts import exp_run

from fbi.research import exp_conditions, exp_e3

from .conftest import Seed
from .test_pattern_search import KICK, Ground

pytestmark = pytest.mark.integration

START = datetime(2026, 10, 1, tzinfo=UTC)
FAR = datetime(2100, 1, 1, tzinfo=UTC)


@pytest.fixture()
def ground(db: psycopg.Connection[Any], seed: Seed) -> Ground:
    return Ground(db, seed)


def test_the_settled_over_under_decisions_are_read_as_the_over_one_per_match_and_line(db: psycopg.Connection[Any], ground: Ground) -> None:
    g = ground
    f1, f2, f3 = g.match(), g.match(), g.match()
    over = g.decide(f1, "CORNERS_OU", "Over", 9.5, p_model=0.60)
    g.settle(over, "win", close=0.55)
    under = g.decide(f2, "CORNERS_OU", "Under", 9.5, p_model=0.30)
    g.settle(under, "win", close=0.35)  # the Under won: the Over did not happen
    both_a = g.decide(f3, "CARDS_OU", "Over", 4.5, p_model=0.50)
    both_b = g.decide(f3, "CARDS_OU", "Under", 4.5, p_model=0.50)
    g.settle(both_a, "loss", close=0.45)
    g.settle(both_b, "win", close=0.55)
    pushed = g.decide(f1, "CARDS_OU", "Over", 4.0, p_model=0.50, p_push=0.2)
    g.settle(pushed, "push", close=0.45)
    rows = exp_e3.load(db, start=START, until=FAR)
    by = {(r.fixture, r.family): r for r in rows}
    assert len(rows) == 3, "a match with both sides of a line is one row; a push is not a yes/no"
    a = by[(f1, "córneres")]
    assert a.p == pytest.approx(0.60) and a.q == pytest.approx(0.55) and a.over == 1
    b = by[(f2, "córneres")]
    assert b.p == pytest.approx(0.70) and b.q == pytest.approx(0.65) and b.over == 0, "an Under at 0.30 is an Over at 0.70, and it did not happen"
    assert by[(f3, "tarjetas")].over == 0 and by[(f3, "tarjetas")].day == KICK.date()


def test_the_experiment_registers_from_the_launcher_script_and_is_not_due_before_its_sample(db: psycopg.Connection[Any]) -> None:
    exp_conditions.unregister("EXP-E3")
    try:
        exp_run.load_plugins()
        state = exp_conditions.check(db, "EXP-E3", at=FAR, model_code="code")
        assert (state.due, state.code, state.required) == (False, "sample", 1500)
        assert exp_e3.count(db, date(2026, 11, 26)) == 0
    finally:
        for key in ("EXP-E1", "EXP-E3", "EXP-E7"):
            exp_conditions.unregister(key)
