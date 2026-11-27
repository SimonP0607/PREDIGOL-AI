"""RP-9.7 on a real database: the count of matches the meter can read, the run on a database with no history (the meter returns no table: nothing is declared) and
the registration by the launcher script."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import psycopg
import pytest
from scripts import exp_run

from fbi.families import exp_e7
from fbi.research import exp_conditions

pytestmark = pytest.mark.integration

AT = datetime(2026, 12, 20, 12, tzinfo=UTC)


def test_with_no_history_the_count_is_zero_and_the_run_declares_nothing(db: psycopg.Connection[Any]) -> None:
    assert exp_e7.count(db, date(2026, 11, 26)) == 0
    judgement, population = exp_e7.run(db, AT)
    assert judgement.verdict == "insuficiente" and population["matches"] == 0 and "coverage" in population


def test_the_experiment_registers_from_the_launcher_script_and_waits_for_the_matches_the_meter_needs(db: psycopg.Connection[Any]) -> None:
    exp_conditions.unregister("EXP-E7")
    try:
        exp_run.load_plugins()
        state = exp_conditions.check(db, "EXP-E7", at=AT, model_code="code")
        assert (state.due, state.code, state.required) == (False, "sample", exp_e7.REQUIRED)
    finally:
        for key in ("EXP-E1", "EXP-E3", "EXP-E6", "EXP-E7"):
            exp_conditions.unregister(key)
