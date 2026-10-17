"""A quality registry that only grows cannot tell today's faults from last month's.

The sweep recorded what each check found and never closed anything, so a problem that had
been FIXED stayed open for ever - including six Champions League ties whose results were
recovered from the raw store the same day. Most of the registry's value is an operator
being able to read it and believe it.

Closing carries two risks, and both are guarded here: a check whose listing was truncated
at 500 rows cannot speak for what it never enumerated, and a check may only close its own
(code, entity_type) pairs because the same code is opened by unrelated producers.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from fbi.quality.detect import (
    CheckOutcome,
    _close_what_the_check_no_longer_finds,
    payload_dated_relations,
)
from fbi.quality.issues import (
    EntityType,
    IssueCode,
    IssueRegistry,
    QualityIssue,
    Severity,
)
from tests.integration.conftest import Seed


@pytest.fixture(autouse=True)
def clean_slate(db: psycopg.Connection) -> Iterator[None]:
    yield
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM audit.data_quality_issues "
                    "WHERE provider_entity_id BETWEEN 95000 AND 95999")
    db.commit()


def issue(code: IssueCode, entity: EntityType, provider_id: int, observed: str,
          field: str = "f") -> QualityIssue:
    return QualityIssue(code=code, entity_type=entity, severity=Severity.WARNING,
                        provider_entity_id=provider_id, field=field, observed=observed,
                        expected="something else")


def status_of(db: psycopg.Connection, fingerprint: str) -> tuple[str, str | None]:
    row = db.execute("SELECT status, resolution FROM audit.data_quality_issues "
                     "WHERE fingerprint = %s", (fingerprint,)).fetchone()
    assert row is not None
    return (row[0], row[1])


def test_an_issue_the_check_no_longer_finds_is_closed_with_a_reason(
    db: psycopg.Connection, seed: Seed
) -> None:
    registry = IssueRegistry(db)
    gone = issue(IssueCode.RESULT_UNRESOLVED, EntityType.FIXTURE_RESULT, 95001, "0-0",
                 field="goals_home")
    registry.record(gone)
    db.commit()

    clean = CheckOutcome("results_are_resolved", "finished_fixtures", Severity.ERROR,
                         population=100, offenders=0, issues=[])
    closed = _close_what_the_check_no_longer_finds(db, registry, clean)
    db.commit()

    assert closed == 1
    status, resolution = status_of(db, gone.fingerprint)
    assert status == "resolved"
    assert "no longer finds it" in (resolution or ""), "the schema refuses a close without a reason"


def test_an_issue_the_check_still_finds_stays_open(db: psycopg.Connection, seed: Seed) -> None:
    registry = IssueRegistry(db)
    still = issue(IssueCode.RESULT_UNRESOLVED, EntityType.FIXTURE_RESULT, 95002, "2-2",
                  field="goals_home")
    registry.record(still)
    db.commit()

    outcome = CheckOutcome("results_are_resolved", "finished_fixtures", Severity.ERROR,
                           population=100, offenders=1, issues=[still])
    closed = _close_what_the_check_no_longer_finds(db, registry, outcome)
    db.commit()

    assert closed == 0
    assert status_of(db, still.fingerprint)[0] == "open"


def test_a_truncated_listing_closes_nothing(db: psycopg.Connection, seed: Seed) -> None:
    """_rows stops at 500. A check reporting 900 offenders while listing one has not seen
    the other 899, and closing "what it did not produce" would resolve real problems."""
    registry = IssueRegistry(db)
    listed = issue(IssueCode.RESULT_UNRESOLVED, EntityType.FIXTURE_RESULT, 95003, "1-0",
                  field="goals_home")
    unlisted = issue(IssueCode.RESULT_UNRESOLVED, EntityType.FIXTURE_RESULT, 95004, "3-1",
                    field="goals_home")
    registry.record(listed)
    registry.record(unlisted)
    db.commit()

    truncated = CheckOutcome("results_are_resolved", "finished_fixtures", Severity.ERROR,
                             population=1000, offenders=900, issues=[listed])
    closed = _close_what_the_check_no_longer_finds(db, registry, truncated)
    db.commit()

    assert closed == 0
    assert status_of(db, unlisted.fingerprint)[0] == "open"


def test_a_check_cannot_close_another_producers_issue_of_the_same_code(
    db: psycopg.Connection, seed: Seed
) -> None:
    """UNKNOWN_PROVIDER_ENTITY is opened by the bookmaker check AND, on a different
    entity, by detail ingestion for an unmapped statistic type. A clean bookmaker check
    must not touch them."""
    registry = IssueRegistry(db)
    not_mine = issue(IssueCode.UNKNOWN_PROVIDER_ENTITY, EntityType.TEAM_STATISTICS,
                     95005, "goals_prevented", field="stat_type")
    registry.record(not_mine)
    db.commit()

    clean_books = CheckOutcome("prices_come_from_known_books", "bookmakers", Severity.INFO,
                               population=33, offenders=0, issues=[])
    closed = _close_what_the_check_no_longer_finds(db, registry, clean_books)
    db.commit()

    assert closed == 0, "a different entity type is a different producer"
    assert status_of(db, not_mine.fingerprint)[0] == "open"


def test_the_same_code_and_entity_on_a_different_field_is_a_different_producer(
    db: psycopg.Connection, seed: Seed
) -> None:
    """This one cost 11,694 records. Detail ingestion opens PROVIDER_INCONSISTENCY on
    team_statistics for `goals_prevented`; values_are_possible opens the same code on the
    same entity for `possession_pct`. Scoped on code and entity alone, a clean run of the
    check resolved every ingestion record with a reason that was not true of them."""
    registry = IssueRegistry(db)
    ingestion = issue(IssueCode.PROVIDER_INCONSISTENCY, EntityType.TEAM_STATISTICS,
                      95010, "null", field="goals_prevented")
    registry.record(ingestion)
    db.commit()

    clean_check = CheckOutcome("values_are_possible", "api_football_detail", Severity.WARNING,
                               population=None, offenders=0, issues=[])
    closed = _close_what_the_check_no_longer_finds(db, registry, clean_check)
    db.commit()

    assert closed == 0, "the field is what tells the two producers apart"
    assert status_of(db, ingestion.fingerprint)[0] == "open"


def test_the_check_still_closes_its_own_field_on_that_shared_pair(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The guard must not make the feature useless: possession_pct IS the check's own."""
    registry = IssueRegistry(db)
    mine = issue(IssueCode.PROVIDER_INCONSISTENCY, EntityType.TEAM_STATISTICS,
                 95011, "142", field="possession_pct")
    registry.record(mine)
    db.commit()

    clean_check = CheckOutcome("values_are_possible", "api_football_detail", Severity.WARNING,
                               population=None, offenders=0, issues=[])
    closed = _close_what_the_check_no_longer_finds(db, registry, clean_check)
    db.commit()

    assert closed == 1
    assert status_of(db, mine.fingerprint)[0] == "resolved"


def test_a_clean_run_closes_a_relation_the_schema_puts_in_scope(
    db: psycopg.Connection, seed: Seed
) -> None:
    """lineage_holds builds its field from a relation name, so it cannot be listed in
    CHECK_SCOPES. It declares the scope from the schema instead - every core relation
    that names a payload and carries its own fetch time - and that set is enumerable, so
    a run finding zero offenders CAN say the problem is fixed.

    Before this, a clean run could close nothing at all, because a clean run produces
    nothing to union with. Three LINEAGE_BROKEN issues stayed open for two days after the
    199,733 rows behind them were repaired and the check had gone to zero. A registry
    that cannot report a fix is one an operator stops believing.
    """
    relations = payload_dated_relations(db)
    assert relations, "the schema should put at least one relation in scope"
    registry = IssueRegistry(db)
    repaired = issue(IssueCode.LINEAGE_BROKEN, EntityType.PAYLOAD, 95014, "3618",
                     field=relations[0])
    registry.record(repaired)
    db.commit()

    clean = CheckOutcome("lineage_holds", "market_and_detail", Severity.ERROR,
                         population=None, offenders=0, issues=[])
    assert _close_what_the_check_no_longer_finds(db, registry, clean) == 1
    db.commit()
    status, resolution = status_of(db, repaired.fingerprint)
    assert status == "resolved"
    assert resolution is not None and "no longer finds it" in resolution


def test_a_clean_run_still_cannot_close_a_field_outside_that_scope(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The guard is unchanged in the direction that matters. A relation the schema query
    does not return is not something this check examined, so it may not speak for it -
    whatever code the issue carries."""
    registry = IssueRegistry(db)
    foreign = issue(IssueCode.LINEAGE_BROKEN, EntityType.PAYLOAD, 95015, "7",
                    field="some_relation_this_check_never_examined")
    registry.record(foreign)
    db.commit()

    clean = CheckOutcome("lineage_holds", "market_and_detail", Severity.ERROR,
                         population=None, offenders=0, issues=[])
    assert _close_what_the_check_no_longer_finds(db, registry, clean) == 0
    db.commit()
    assert status_of(db, foreign.fingerprint)[0] == "open"


def test_a_run_time_field_is_closed_only_when_the_check_names_it_that_run(
    db: psycopg.Connection, seed: Seed
) -> None:
    """A field that is neither declared by hand nor returned by the schema query can
    still be closed by the run that produced it - but only by that run."""
    registry = IssueRegistry(db)
    dynamic = issue(IssueCode.LINEAGE_BROKEN, EntityType.PAYLOAD, 95012, "12",
                    field="market.odds_snapshots")
    registry.record(dynamic)
    db.commit()

    clean = CheckOutcome("lineage_holds", "market_and_detail", Severity.ERROR,
                         population=None, offenders=0, issues=[])
    assert _close_what_the_check_no_longer_finds(db, registry, clean) == 0
    db.commit()
    assert status_of(db, dynamic.fingerprint)[0] == "open"

    other = issue(IssueCode.LINEAGE_BROKEN, EntityType.PAYLOAD, 95013, "3",
                  field="market.odds_snapshots")
    names_it = CheckOutcome("lineage_holds", "market_and_detail", Severity.ERROR,
                            population=None, offenders=1, issues=[other])
    assert _close_what_the_check_no_longer_finds(db, registry, names_it) == 1
    db.commit()
    assert status_of(db, dynamic.fingerprint)[0] == "resolved"


def test_a_check_with_no_declared_scope_closes_nothing(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Fail closed: an unknown check name must not be able to resolve anything."""
    registry = IssueRegistry(db)
    other = issue(IssueCode.STALE_DATA, EntityType.FIXTURE, 95006, "x", field="status_short")
    registry.record(other)
    db.commit()

    unknown = CheckOutcome("a_check_nobody_declared", "scope", Severity.WARNING,
                           population=1, offenders=0, issues=[])
    assert _close_what_the_check_no_longer_finds(db, registry, unknown) == 0
    db.commit()
    assert status_of(db, other.fingerprint)[0] == "open"


def test_closing_is_idempotent(db: psycopg.Connection, seed: Seed) -> None:
    registry = IssueRegistry(db)
    gone = issue(IssueCode.STALE_DATA, EntityType.FIXTURE, 95007, "y", field="status_short")
    registry.record(gone)
    db.commit()
    clean = CheckOutcome("results_are_not_stale", "unfinished_fixtures", Severity.WARNING,
                         population=10, offenders=0, issues=[])

    first = _close_what_the_check_no_longer_finds(db, registry, clean)
    db.commit()
    second = _close_what_the_check_no_longer_finds(db, registry, clean)
    db.commit()

    assert first == 1 and second == 0, "an already-resolved issue is not resolved again"


# --- a check with more offenders than it records ----------------------------


def test_a_check_that_enumerated_every_row_may_close_even_when_it_recorded_few(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The leak this closed: lineups_are_complete had 2,894 offenders against a
    500-row recording cap, so the completeness guard refused to close anything
    and 36,823 INCOMPLETE_LINEUP rows stood open while the check itself put the
    real figure at 2,894.

    Recording a sample and enumerating everything are different jobs. The guard
    is unchanged in substance - a check may only speak for what it saw - it is
    just measured against what was SEEN rather than what was WRITTEN.
    """
    registry = IssueRegistry(db)
    stale = issue(IssueCode.STALE_DATA, EntityType.FIXTURE, 95020, "old",
                  field="status_short")
    registry.record(stale)
    db.commit()

    still_there = issue(IssueCode.STALE_DATA, EntityType.FIXTURE, 95021, "new",
                        field="status_short")
    outcome = CheckOutcome(
        "results_are_not_stale", "unfinished_fixtures", Severity.WARNING,
        population=100, offenders=900,
        issues=[still_there],                     # one recorded
        found=frozenset({still_there.fingerprint}),
        enumerated_rows=900,                      # nine hundred seen
    )
    assert outcome.complete
    assert _close_what_the_check_no_longer_finds(db, registry, outcome) == 1
    db.commit()
    assert status_of(db, stale.fingerprint)[0] == "resolved"


def test_a_check_that_did_not_see_every_row_still_closes_nothing(
    db: psycopg.Connection, seed: Seed
) -> None:
    registry = IssueRegistry(db)
    stale = issue(IssueCode.STALE_DATA, EntityType.FIXTURE, 95022, "old",
                  field="status_short")
    registry.record(stale)
    db.commit()

    truncated = CheckOutcome(
        "results_are_not_stale", "unfinished_fixtures", Severity.WARNING,
        population=100, offenders=900, issues=[], found=frozenset(),
        enumerated_rows=500,   # it only got through 500 of the 900
    )
    assert not truncated.complete
    assert _close_what_the_check_no_longer_finds(db, registry, truncated) == 0
    db.commit()
    assert status_of(db, stale.fingerprint)[0] == "open"


def test_completeness_is_counted_in_rows_not_in_fingerprints(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Several offending rows can share one issue - two line-ups of a fixture
    both naming ten starters produce the same fingerprint - so a complete run
    has fewer fingerprints than offenders. Comparing the two made a complete run
    look truncated, and that alone stopped 2,894 enumerated offenders from
    closing anything."""
    one = issue(IssueCode.STALE_DATA, EntityType.FIXTURE, 95023, "x",
                field="status_short")
    outcome = CheckOutcome(
        "results_are_not_stale", "unfinished_fixtures", Severity.WARNING,
        population=10, offenders=3,
        issues=[one],
        found=frozenset({one.fingerprint}),   # three rows, one fingerprint
        enumerated_rows=3,
    )
    assert outcome.complete, "three rows seen, three offenders - complete"
    assert len(outcome.enumerated) == 1


def test_without_the_row_count_the_recorded_issues_are_the_measure(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Every check whose offenders fit inside the cap passes nothing extra, and
    must behave exactly as it did before."""
    one = issue(IssueCode.STALE_DATA, EntityType.FIXTURE, 95024, "x",
                field="status_short")
    assert CheckOutcome("results_are_not_stale", "s", Severity.WARNING, 10, 1,
                        issues=[one]).complete
    assert not CheckOutcome("results_are_not_stale", "s", Severity.WARNING, 10, 2,
                            issues=[one]).complete
