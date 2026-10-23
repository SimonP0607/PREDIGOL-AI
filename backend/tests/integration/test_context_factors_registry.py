"""The registry of context factors on a real database (plan F6, revision 0088): every factor is DESCRIPTIVE until a person validates it,
the validation is about one version of the code and is read as of a moment, and the database itself refuses a validation without a person,
an experiment and its result. The transaction is rolled back after every test."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.intel import factors, h2h

pytestmark = pytest.mark.integration

T0 = datetime(2034, 4, 1, 12, tzinfo=UTC)
DAY = timedelta(days=1)
REASON = "the weighted record beat the form on the test matches"
RESULT = {"matches": 2100, "logloss_delta": -0.004, "ci95": [-0.007, -0.001]}
H2H = factors.H2H
INSERT = ("INSERT INTO intel.context_factors (factor, version, status, decided_at, decided_by, who, reason, evidence, previous_id) "
          "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id")


def evidence(factor: str = H2H, version: str = h2h.VERSION, **change: Any) -> Jsonb:
    base: dict[str, Any] = {"factor": factor, "version": version, "experiment": "F12-h2h-01", "result": RESULT}
    return Jsonb({k: v for k, v in (base | change).items() if v is not None})


def validated(db: psycopg.Connection[Any], at: datetime = T0, experiment: str = "F12-h2h-01") -> factors.Change:
    return factors.promote(db, H2H, experiment=experiment, result=RESULT, reason=REASON, who="Simon", at=at)


def count(db: psycopg.Connection[Any]) -> int:
    row = db.execute("SELECT count(*) FROM intel.context_factors").fetchone()
    assert row is not None
    return int(row[0])


# ── the standings ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_factor_nobody_has_decided_on_is_descriptive(db: psycopg.Connection[Any]) -> None:
    assert count(db) == 0
    stands = factors.standings(db, at=T0)
    assert set(stands) == set(factors.BY_KEY)
    assert all(s.status == factors.DESCRIPTIVE and s.decision is None for s in stands.values())


def test_a_validation_counts_from_the_moment_it_was_decided_and_not_before(db: psycopg.Connection[Any]) -> None:
    got = validated(db)
    assert got.changed and got.decision.status == factors.VALIDATED and got.decision.previous_id is None
    assert got.decision.who == "Simon" and got.decision.decided_by == "owner" and got.decision.reason == REASON
    assert got.decision.evidence == {"factor": H2H, "version": h2h.VERSION, "experiment": "F12-h2h-01", "result": RESULT}
    assert factors.standings(db, at=T0 - timedelta(seconds=1))[H2H].status == factors.DESCRIPTIVE
    now = factors.standings(db, at=T0)[H2H]
    assert now.status == factors.VALIDATED and now.decision is not None and now.decision.id == got.decision.id
    assert {k: s.status for k, s in factors.standings(db, at=T0 + DAY).items() if k != H2H} == {
        k: factors.DESCRIPTIVE for k in factors.BY_KEY if k != H2H}, "the others are untouched"


def test_taking_a_validation_back_is_a_new_decision_and_the_past_stays_as_it_was(db: psycopg.Connection[Any]) -> None:
    first = validated(db).decision
    back = factors.retire(db, H2H, reason="the experiment did not replicate on new matches", who="Simon", at=T0 + 10 * DAY)
    assert back.changed and back.decision.status == factors.DESCRIPTIVE and back.decision.previous_id == first.id
    assert back.decision.evidence["retired_decision"] == first.id and back.decision.evidence["retired_experiment"] == "F12-h2h-01"
    assert factors.standings(db, at=T0 + 5 * DAY)[H2H].status == factors.VALIDATED, "as of the 6th it was validated"
    after = factors.standings(db, at=T0 + 10 * DAY)[H2H]
    assert after.status == factors.DESCRIPTIVE and after.decision is not None and after.decision.id == back.decision.id
    assert [d.id for d in factors.history(db, H2H)] == [first.id, back.decision.id]
    assert count(db) == 2, "nothing was rewritten"


def test_validated_again_after_being_taken_back_continues_the_same_line(db: psycopg.Connection[Any]) -> None:
    first = validated(db).decision
    back = factors.retire(db, H2H, reason="the experiment did not replicate on new matches", who="Simon", at=T0 + DAY).decision
    again = validated(db, T0 + 2 * DAY, "F12-h2h-02").decision
    assert [d.previous_id for d in (first, back, again)] == [None, first.id, back.id]
    assert factors.standings(db, at=T0 + 3 * DAY)[H2H].status == factors.VALIDATED


def test_the_same_experiment_validating_again_writes_nothing_and_another_one_is_a_new_decision(db: psycopg.Connection[Any]) -> None:
    first = validated(db)
    same = validated(db, T0 + DAY)
    assert not same.changed and same.decision.id == first.decision.id and count(db) == 1
    other = validated(db, T0 + 2 * DAY, "F12-h2h-02")
    assert other.changed and other.decision.previous_id == first.decision.id and other.decision.experiment == "F12-h2h-02"


def test_a_validation_is_about_one_version_of_the_code(db: psycopg.Connection[Any]) -> None:
    """The head-to-head was validated when it was ``h2h-v1``; the code in force is ``h2h-v2``: nothing carries over."""
    old: str = "h2h-v1"
    db.execute(INSERT, (H2H, old, "VALIDATED", T0, "owner", "Simon", REASON, evidence(version=old), None))
    assert factors.standings(db, at=T0 + DAY)[H2H].status == factors.DESCRIPTIVE
    assert factors.BY_KEY[H2H].version == h2h.VERSION and old != h2h.VERSION
    assert factors.newest(db, H2H, old) is not None and factors.newest(db, H2H, h2h.VERSION) is None
    assert validated(db, T0 + 2 * DAY).decision.previous_id is None, "the new version starts its own line"
    assert [d.version for d in factors.history(db, H2H)] == [old, h2h.VERSION]


def test_taking_back_what_is_not_validated_is_refused(db: psycopg.Connection[Any]) -> None:
    with pytest.raises(PermissionError, match="nothing to take back"):
        factors.retire(db, H2H, reason="there was nothing to take back", who="Simon", at=T0)
    validated(db)
    factors.retire(db, H2H, reason="the experiment did not replicate on new matches", who="Simon", at=T0 + DAY)
    with pytest.raises(PermissionError, match="nothing to take back"):
        factors.retire(db, H2H, reason="taken back a second time, for nothing", who="Simon", at=T0 + 2 * DAY)


def test_a_decision_cannot_be_dated_before_the_one_it_follows(db: psycopg.Connection[Any]) -> None:
    validated(db, T0 + 5 * DAY)
    with pytest.raises(ValueError, match="before the one it follows"):
        factors.retire(db, H2H, reason="dated before the decision it takes back", who="Simon", at=T0)
    assert count(db) == 1


def test_only_a_factor_of_the_catalogue_can_be_decided_on(db: psycopg.Connection[Any]) -> None:
    with pytest.raises(LookupError, match="not a context factor"):
        factors.promote(db, "moon_phase", experiment="X", result=RESULT, reason=REASON, who="Simon", at=T0)
    assert count(db) == 0


def test_a_refused_validation_leaves_no_row(db: psycopg.Connection[Any]) -> None:
    refused: list[dict[str, Any]] = [{"experiment": " "}, {"result": {}}, {"reason": "short"}, {"who": " "}]
    for kwargs in refused:
        args: dict[str, Any] = {"experiment": "F12-h2h-01", "result": RESULT, "reason": REASON, "who": "Simon"} | kwargs
        with pytest.raises(ValueError):
            factors.promote(db, H2H, at=T0, **args)
    assert count(db) == 0


def test_the_latest_view_has_the_newest_decision_of_each_factor_and_version(db: psycopg.Connection[Any]) -> None:
    validated(db)
    back = factors.retire(db, H2H, reason="the experiment did not replicate on new matches", who="Simon", at=T0 + DAY).decision
    factors.promote(db, factors.TACTICS, experiment="F12-tactics-01", result=RESULT, reason=REASON, who="Simon", at=T0)
    rows = {(r[0], r[1]): (r[2], r[3]) for r in db.execute("SELECT factor, version, status, id FROM intel.context_factors_latest").fetchall()}
    assert rows[(H2H, h2h.VERSION)] == ("DESCRIPTIVE", back.id)
    assert rows[(factors.TACTICS, factors.BY_KEY[factors.TACTICS].version)][0] == "VALIDATED"
    assert len(rows) == 2


# ── what the database refuses ──────────────────────────────────────────────────────────────────────────────────────────


def refused(db: psycopg.Connection[Any], params: tuple[Any, ...], error: type[Exception] = psycopg.errors.CheckViolation) -> None:
    with pytest.raises(error), db.transaction():
        db.execute(INSERT, params)


GOOD = (H2H, h2h.VERSION, "VALIDATED", T0, "owner", "Simon", REASON, evidence(), None)


def test_the_database_accepts_a_validation_by_a_person_with_an_experiment_and_its_result(db: psycopg.Connection[Any]) -> None:
    assert db.execute(INSERT, GOOD).fetchone() is not None


@pytest.mark.parametrize("change", [
    {"decided_by": "system", "who": None},                                  # the system does not validate
    {"who": None},                                                           # a person is named
    {"who": "  "},                                                           # and the name says something
    {"evidence": evidence(experiment=None)},                                 # no experiment
    {"evidence": evidence(experiment="   ")},                                # a blank one
    {"evidence": evidence(experiment=5)},                                    # not a name
    {"evidence": evidence(result=None)},                                     # no result
    {"evidence": evidence(result={})},                                       # an empty one
    {"evidence": evidence(result=[1, 2])},                                   # not an object
    {"evidence": evidence(factor="tactics_profile")},                        # about another factor
    {"evidence": evidence(version="h2h-v1")},                                # about another version
    {"evidence": Jsonb({})},                                                 # nothing at all
    {"evidence": Jsonb([])},                                                 # not even an object
    {"reason": "short"},
    {"status": "MAYBE"},
    {"decided_by": "bot"},
    {"factor": "H2H Weighted"},
    {"factor": "x"},
    {"version": "  "},
], ids=["system", "no_person", "blank_person", "no_experiment", "blank_experiment", "experiment_not_a_name", "no_result",
        "empty_result", "result_not_an_object", "other_factor", "other_version", "empty_evidence", "evidence_not_an_object",
        "short_reason", "unknown_status", "unknown_decider", "bad_key", "short_key", "blank_version"])
def test_the_database_refuses_a_decision_that_breaks_a_rule(db: psycopg.Connection[Any], change: dict[str, Any]) -> None:
    names = ("factor", "version", "status", "decided_at", "decided_by", "who", "reason", "evidence", "previous_id")
    row = {**dict(zip(names, GOOD, strict=True)), **change}
    refused(db, tuple(row[n] for n in names))


@pytest.mark.parametrize("params", [
    (H2H, h2h.VERSION, "DESCRIPTIVE", T0, "system", "Simon", REASON, Jsonb({}), None),   # the system has no name
    (H2H, h2h.VERSION, "DESCRIPTIVE", T0, "owner", None, REASON, Jsonb({}), None),       # a person has
], ids=["system_with_a_name", "owner_without_one"])
def test_a_name_goes_with_a_person_and_only_with_a_person(db: psycopg.Connection[Any], params: tuple[Any, ...]) -> None:
    refused(db, params)


def test_a_descriptive_row_needs_no_experiment(db: psycopg.Connection[Any]) -> None:
    assert db.execute(INSERT, (H2H, h2h.VERSION, "DESCRIPTIVE", T0, "system", None, "a note by the system, nothing more",
                               Jsonb({}), None)).fetchone() is not None


def test_the_rows_of_a_factor_form_one_line(db: psycopg.Connection[Any]) -> None:
    first = db.execute(INSERT, GOOD).fetchone()
    assert first is not None
    follows = (*GOOD[:8], first[0])
    refused(db, GOOD, psycopg.errors.UniqueViolation)                      # a second first decision for the same version
    db.execute(INSERT, follows)
    refused(db, follows, psycopg.errors.UniqueViolation)                   # two decisions following the same one
    tactics_version = factors.BY_KEY[factors.TACTICS].version
    other = db.execute(INSERT, (factors.TACTICS, tactics_version, "VALIDATED", T0, "owner", "Simon", REASON,
                                evidence(factor=factors.TACTICS, version=tactics_version), None)).fetchone()
    assert other is not None
    refused(db, (*GOOD[:8], other[0]), psycopg.errors.ForeignKeyViolation)   # a line cannot follow another factor's row
    refused(db, (*GOOD[:8], first[0] + 10_000), psycopg.errors.ForeignKeyViolation)


def test_a_decision_is_never_edited_or_deleted_afterwards(db: psycopg.Connection[Any]) -> None:
    validated(db)
    for sql in ("UPDATE intel.context_factors SET status = 'DESCRIPTIVE'", "UPDATE intel.context_factors SET reason = 'edited quietly later'",
                "DELETE FROM intel.context_factors"):
        with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), db.transaction():
            db.execute(sql)
    assert count(db) == 1


def test_the_owner_can_lift_the_guard_inside_one_transaction_for_a_documented_task(db: psycopg.Connection[Any]) -> None:
    """The contract of every ``intel`` table (revision 0076): ``SET LOCAL fbi.intel_maintenance = 'on'``. Nothing in the application does."""
    validated(db)
    with db.transaction():
        db.execute("SET LOCAL fbi.intel_maintenance = 'on'")
        db.execute("DELETE FROM intel.context_factors")
    assert count(db) == 0
