"""RP-4.5 on a real database (revision 0182): a factor can be recorded as measured with or without effect, citing its experiment; only a validation lets anything
use it; the typed facts of the context block get their first row; the database itself refuses a measurement without an experiment and its result.
The transaction is rolled back after every test."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.intel import factor_block, factor_residual, factors

pytestmark = pytest.mark.integration

T0 = datetime(2034, 6, 1, 12, tzinfo=UTC)
REASON = "measured against the market on the test matches"
RESULT = {"matches": 2400, "mean": 0.004, "se": 0.009}
KEY = factors.CALENDAR
INSERT = ("INSERT INTO intel.context_factors (factor, version, status, decided_at, decided_by, who, reason, evidence, previous_id) "
          "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)")


def measured(db: psycopg.Connection[Any], *, effect: bool = False, experiment: str = "rp45-rest-01", at: datetime = T0, key: str = KEY) -> factors.Change:
    return factors.record_test(db, key, effect=effect, experiment=experiment, result=RESULT, reason=REASON, at=at)


def test_a_measurement_is_written_by_the_system_and_cites_its_experiment(db: psycopg.Connection[Any]) -> None:
    got = measured(db)
    d = got.decision
    assert got.changed and d.status == factors.TESTED_NO_EFFECT and d.decided_by == "system" and d.who is None and d.previous_id is None
    assert d.experiment == "rp45-rest-01" and d.evidence["result"] == RESULT and d.evidence["factor"] == KEY
    stand = factors.standings(db, at=T0)[KEY]
    assert stand.status == factors.TESTED_NO_EFFECT and not factors.usable_as_signal(stand.status)
    assert factors.standings(db, at=T0 - timedelta(seconds=1))[KEY].status == factors.DESCRIPTIVE


def test_the_same_experiment_twice_writes_nothing_and_another_one_supersedes(db: psycopg.Connection[Any]) -> None:
    first = measured(db)
    again = measured(db, at=T0 + timedelta(days=1))
    assert not again.changed and again.decision.id == first.decision.id
    second = measured(db, effect=True, experiment="rp45-rest-02", at=T0 + timedelta(days=2))
    assert second.changed and second.decision.status == factors.TESTED_EFFECT and second.decision.previous_id == first.decision.id
    assert factors.newest(db, KEY, factors.known(KEY).version) == second.decision


def test_a_measurement_never_moves_a_validation_and_a_no_effect_blocks_validating_by_the_same_experiment(db: psycopg.Connection[Any]) -> None:
    first = measured(db)
    with pytest.raises(PermissionError, match="no effect"):
        factors.promote(db, KEY, experiment="rp45-rest-01", result=RESULT, reason=REASON, who="Simon", at=T0 + timedelta(days=1))
    promoted = factors.promote(db, KEY, experiment="rp45-rest-03", result=RESULT, reason=REASON, who="Simon", at=T0 + timedelta(days=1))
    assert promoted.changed and promoted.decision.status == factors.VALIDATED and promoted.decision.previous_id == first.decision.id
    with pytest.raises(PermissionError, match="validated"):
        measured(db, effect=True, experiment="rp45-rest-04", at=T0 + timedelta(days=2))
    taken_back = factors.retire(db, KEY, reason="the effect did not repeat", who="Simon", at=T0 + timedelta(days=3))
    assert taken_back.decision.status == factors.DESCRIPTIVE


def test_a_person_may_record_a_measurement_too(db: psycopg.Connection[Any]) -> None:
    got = factors.record_test(db, KEY, effect=True, experiment="rp45-rest-05", result=RESULT, reason=REASON, who="Simon", at=T0)
    assert got.decision.decided_by == "owner" and got.decision.who == "Simon"


def test_the_residual_report_goes_into_the_registry_as_the_experiments_result(db: psycopg.Connection[Any]) -> None:
    from .test_factor_residual_inputs import observations

    report = factor_residual.report(observations())
    state = report["verdict"]["state"]
    got = factors.record_test(db, KEY, effect=state == factors.TESTED_EFFECT, experiment="rp45-residual-01", result=report, reason=REASON, at=T0)
    assert got.decision.evidence["result"]["version"] == factor_residual.VERSION


@pytest.mark.parametrize("evidence", [
    {"factor": KEY, "version": "v"},
    {"factor": KEY, "version": "v", "experiment": "x"},
    {"factor": KEY, "version": "v", "experiment": "x", "result": {}},
    {"factor": KEY, "version": "other", "experiment": "x", "result": {"a": 1}},
])
def test_the_database_refuses_a_measurement_without_its_experiment_and_result(db: psycopg.Connection[Any], evidence: dict[str, Any]) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(INSERT, (KEY, "v", factors.TESTED_EFFECT, T0, "system", None, REASON, Jsonb(evidence), None))


def test_the_database_still_refuses_a_validation_by_the_system_and_an_unknown_state(db: psycopg.Connection[Any]) -> None:
    good = {"factor": KEY, "version": "v", "experiment": "x", "result": {"a": 1}}
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(INSERT, (KEY, "v", factors.VALIDATED, T0, "system", None, REASON, Jsonb(good), None))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(INSERT, (KEY, "v", "PROVEN", T0, "system", None, REASON, Jsonb(good), None))


def test_the_block_load_gives_every_typed_fact_its_first_row_once(db: psycopg.Connection[Any]) -> None:
    before = factor_block.coverage(db, at=T0)
    assert before["factors"] == len(factors.CATALOGUE) + len(factor_block.BLOCK) == before["with_status"]
    assert set(before["without_row"]) == set(factor_block.BY_KEY)
    assert factor_block.register(db, at=T0) == len(factor_block.BLOCK)
    assert factor_block.register(db, at=T0 + timedelta(days=1)) == 0, "idempotent"
    after = factor_block.coverage(db, at=T0)
    assert after["without_row"] == [] and all(not r["usable"] for r in after["rows"])
    assert {r["factor"]: r["status"] for r in after["rows"] if r["factor"] in factor_block.BY_KEY} == dict.fromkeys(factor_block.BY_KEY, factors.DESCRIPTIVE)
    # the packet lists the catalogue only: the load changes nothing it shows
    assert set(factors.standings(db, at=T0)) == set(factors.BY_KEY)
    assert set(factors.block(factors.standings(db, at=T0))) >= set(factors.BY_KEY)
    assert not set(factors.block(factors.standings(db, at=T0))) & set(factor_block.BY_KEY)


def test_a_typed_fact_can_be_measured_and_validated_like_a_block(db: psycopg.Connection[Any]) -> None:
    factor_block.register(db, at=T0)
    got = measured(db, key=factor_block.STAKES, at=T0 + timedelta(days=1))
    assert got.decision.status == factors.TESTED_NO_EFFECT and got.decision.previous_id is not None
