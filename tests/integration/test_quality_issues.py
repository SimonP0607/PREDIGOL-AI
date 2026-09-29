"""The registry of what the provider said and we could not use.

    RAW  ->  NORMALIZED  ->  QUALITY ISSUE / TRANSFORMATION

The behaviour being replaced was real and is quoted in migration 0027: the
detail normaliser set shots_on_target to NULL whenever it exceeded shots_total,
so a contradiction in the provider's data became a missing value in ours with
nothing recording that it had ever been there.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest

from fbi.ingestion.details import apply_fixture_details
from fbi.providers.api_football.details import FixtureDetail, TeamStatsRef
from fbi.quality.issues import (
    EntityType,
    IssueCode,
    IssueRegistry,
    IssueStatus,
    QualityIssue,
    Severity,
    issues_from,
    record_check,
    unknown_entity,
)
from tests.integration.conftest import Seed
from tests.integration.helpers import must_be_rejected, must_be_rejected_saying

FETCHED = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def only_this_test(db: psycopg.Connection) -> None:
    """Other modules commit real issues as a side effect of capturing prices.

    The delete happens inside this test's own transaction, which the db fixture
    rolls back, so it isolates the counting assertions here without touching what
    anything else recorded.
    """
    db.execute("DELETE FROM audit.data_quality_issues")

REQUIRED_CODES = {
    "PROVIDER_INCONSISTENCY", "INCOMPLETE_LINEUP", "RESULT_UNRESOLVED", "MISSING_DETAIL",
    "NORMALIZATION_REJECTED", "UNKNOWN_PROVIDER_ENTITY", "STALE_DATA",
}


def _issue(seed: Seed, **over: object) -> QualityIssue:
    base: dict[str, object] = {
        "code": IssueCode.PROVIDER_INCONSISTENCY,
        "entity_type": EntityType.TEAM_STATISTICS,
        "entity_id": seed.fixture_id,
        "field": "shots_on_target",
        "observed": 7,
        "expected": "at most shots (5)",
        "payload_hash": seed.payload_hash,
        "run_id": seed.run_id,
    }
    base.update(over)
    return QualityIssue(**base)  # type: ignore[arg-type]


# ── the catalogue ───────────────────────────────────────────────────────────


def test_every_code_the_mandate_names_exists_with_a_severity(db: psycopg.Connection) -> None:
    with db.cursor() as cur:
        cur.execute("SELECT code, default_severity, is_provider_fact FROM audit.data_quality_codes")
        rows = {c: (s, f) for c, s, f in cur.fetchall()}
    assert set(rows) >= REQUIRED_CODES
    assert set(IssueCode) == set(rows), "the enum and the catalogue cannot drift apart"
    assert rows["RESULT_UNRESOLVED"][0] == "error"
    assert rows["UNKNOWN_PROVIDER_ENTITY"] == ("info", True), "not our bug: the provider named it"
    assert rows["STALE_DATA"][1] is False, "stale data is our pipeline, not the provider's data"


def test_an_unknown_code_cannot_be_recorded(db: psycopg.Connection, seed: Seed) -> None:
    with must_be_rejected(db, "the code has to be in the catalogue"):
        db.execute(
            "INSERT INTO audit.data_quality_issues (code, severity, entity_type, entity_id, fingerprint) "
            "VALUES ('SOMETHING_NEW','warning','fixture',%s,'f1')", (seed.fixture_id,)
        )


# ── recording and idempotence ───────────────────────────────────────────────


def test_an_issue_carries_its_whole_provenance(db: psycopg.Connection, seed: Seed) -> None:
    issue_id = IssueRegistry(db).record(_issue(seed))
    with db.cursor() as cur:
        cur.execute(
            "SELECT code, severity, entity_type, entity_id, provider, payload_hash, run_id, field, "
            "       observed, expected, observed_number, status, occurrences "
            "FROM audit.data_quality_issues WHERE id = %s", (issue_id,)
        )
        row = cur.fetchone()
    assert row == ("PROVIDER_INCONSISTENCY", "warning", "team_statistics", seed.fixture_id,
                   "api-football", seed.payload_hash, seed.run_id, "shots_on_target", "7",
                   "at most shots (5)", Decimal("7"), "open", 1)


def test_the_same_issue_seen_twice_is_one_issue_seen_twice(db: psycopg.Connection, seed: Seed) -> None:
    registry = IssueRegistry(db)
    first = registry.record(_issue(seed))
    again = registry.record(_issue(seed))
    assert first == again, "the fingerprint identifies the problem, not the sighting"
    with db.cursor() as cur:
        cur.execute("SELECT occurrences, last_seen_at >= detected_at FROM audit.data_quality_issues "
                    "WHERE id = %s", (first,))
        assert cur.fetchone() == (2, True)


def test_a_different_wrong_number_is_a_different_issue(db: psycopg.Connection, seed: Seed) -> None:
    registry = IssueRegistry(db)
    assert registry.record(_issue(seed, observed=7)) != registry.record(_issue(seed, observed=9))


def test_one_sweep_offering_the_same_problem_twice_counts_it_once(
    db: psycopg.Connection, seed: Seed
) -> None:
    """A payload naming the same contradiction for both teams' rows should not
    make the occurrence count say "seen twice"."""
    result = IssueRegistry(db).record_many(issues_from([_issue(seed), _issue(seed)]))
    assert (result.opened, result.seen_again) == (1, 0)


def test_an_issue_without_a_subject_is_refused(db: psycopg.Connection) -> None:
    with must_be_rejected_saying(db, "issue_entity_is_identified"):
        db.execute(
            "INSERT INTO audit.data_quality_issues (code, severity, entity_type, fingerprint) "
            "VALUES ('STALE_DATA','warning','fixture','no-subject')"
        )


def test_details_cannot_become_a_dumping_ground(db: psycopg.Connection, seed: Seed) -> None:
    """A structured column is the answer to a recurring field, not a bigger blob."""
    with must_be_rejected_saying(db, "issue_details_stay_small"):
        db.execute(
            "INSERT INTO audit.data_quality_issues (code, severity, entity_type, entity_id, "
            " fingerprint, details) VALUES ('STALE_DATA','warning','fixture',%s,'big',%s::jsonb)",
            (seed.fixture_id, '{"payload": "' + "x" * 5000 + '"}'),
        )


def test_a_long_observed_value_is_clipped_not_refused(db: psycopg.Connection, seed: Seed) -> None:
    """Evidence, not a document: the useful part is at the front."""
    issue_id = IssueRegistry(db).record(_issue(seed, observed="y" * 900))
    with db.cursor() as cur:
        cur.execute("SELECT length(observed) FROM audit.data_quality_issues WHERE id = %s", (issue_id,))
        assert cur.fetchone() == (500,)


# ── the lifecycle ───────────────────────────────────────────────────────────


def test_an_issue_cannot_be_resolved_without_saying_why(db: psycopg.Connection, seed: Seed) -> None:
    issue_id = IssueRegistry(db).record(_issue(seed))
    with must_be_rejected_saying(db, "issue_resolution_is_explained"):
        db.execute("UPDATE audit.data_quality_issues SET status = 'resolved' WHERE id = %s", (issue_id,))
    with must_be_rejected_saying(db, "issue_wont_fix_is_explained"):
        db.execute("UPDATE audit.data_quality_issues SET status = 'wont_fix' WHERE id = %s", (issue_id,))


def test_resolving_records_the_reason_and_the_moment(db: psycopg.Connection, seed: Seed) -> None:
    registry = IssueRegistry(db)
    issue = _issue(seed)
    registry.record(issue)
    assert registry.resolve(issue.fingerprint, resolution="the provider corrected the payload")
    with db.cursor() as cur:
        cur.execute("SELECT status, resolution, resolved_at IS NOT NULL FROM audit.data_quality_issues "
                    "WHERE fingerprint = %s", (issue.fingerprint,))
        assert cur.fetchone() == ("resolved", "the provider corrected the payload", True)


def test_an_empty_resolution_is_refused_before_it_reaches_the_database(
    db: psycopg.Connection, seed: Seed
) -> None:
    registry = IssueRegistry(db)
    issue = _issue(seed)
    registry.record(issue)
    with pytest.raises(ValueError, match="without saying why"):
        registry.resolve(issue.fingerprint, resolution="   ")


def test_a_resolved_issue_that_comes_back_is_reopened(db: psycopg.Connection, seed: Seed) -> None:
    """Otherwise a fixed-then-broken-again problem stays invisible."""
    registry = IssueRegistry(db)
    issue = _issue(seed)
    registry.record(issue)
    registry.resolve(issue.fingerprint, resolution="believed fixed upstream")
    registry.record(issue)
    with db.cursor() as cur:
        cur.execute("SELECT status, resolved_at, occurrences FROM audit.data_quality_issues "
                    "WHERE fingerprint = %s", (issue.fingerprint,))
        assert cur.fetchone() == ("open", None, 2)


def test_an_acknowledged_issue_is_not_reopened_by_seeing_it_again(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Acknowledged means "we know, and we are living with it": a re-sighting
    should not undo that."""
    registry = IssueRegistry(db)
    issue = _issue(seed)
    registry.record(issue)
    registry.resolve(issue.fingerprint, resolution="known provider quirk",
                     status=IssueStatus.ACKNOWLEDGED)
    registry.record(issue)
    with db.cursor() as cur:
        cur.execute("SELECT status FROM audit.data_quality_issues WHERE fingerprint = %s",
                    (issue.fingerprint,))
        assert cur.fetchone() == ("acknowledged",)


# ── the summary is honest about what it counts ───────────────────────────────


def test_issues_and_occurrences_are_counted_separately(db: psycopg.Connection, seed: Seed) -> None:
    """Fifteen incomplete line-ups seen three times each are fifteen problems,
    not forty-five."""
    registry = IssueRegistry(db)
    for team in range(15):
        for _sighting in range(3):
            registry.record(QualityIssue(
                code=IssueCode.INCOMPLETE_LINEUP, entity_type=EntityType.LINEUP,
                entity_id=seed.fixture_id, provider_entity_id=9000 + team, field="starters",
                observed=10, expected="11", payload_hash=seed.payload_hash,
            ))
    summary = {row["code"]: row for row in registry.summary()}
    assert summary["INCOMPLETE_LINEUP"]["issues"] == 15
    assert summary["INCOMPLETE_LINEUP"]["occurrences"] == 45
    assert summary["INCOMPLETE_LINEUP"]["is_provider_fact"] is True


def test_a_resolved_issue_leaves_the_open_summary(db: psycopg.Connection, seed: Seed) -> None:
    registry = IssueRegistry(db)
    issue = _issue(seed)
    registry.record(issue)
    assert registry.summary()
    registry.resolve(issue.fingerprint, resolution="not real: our parser was wrong")
    assert registry.summary() == []


def test_open_issues_can_be_filtered_by_code_and_entity(db: psycopg.Connection, seed: Seed) -> None:
    registry = IssueRegistry(db)
    registry.record(_issue(seed))
    registry.record(unknown_entity(entity_type=EntityType.PROVIDER_MARKET, name="Corners Asian Handicap",
                                   provider_entity_id=56, payload_hash=seed.payload_hash))
    assert len(registry.open_issues()) == 2
    assert len(registry.open_issues(code=IssueCode.UNKNOWN_PROVIDER_ENTITY)) == 1
    assert len(registry.open_issues(entity_type=EntityType.TEAM_STATISTICS)) == 1


# ── a check records its denominator ─────────────────────────────────────────


def test_a_check_records_what_it_ran_against(db: psycopg.Connection, seed: Seed) -> None:
    """A percentage needs a population. population = NULL means "could not be
    established", which is not the same as zero."""
    passed = record_check(db, run_id=seed.run_id, check_name="lineups_are_complete", scope="tier1",
                          severity=Severity.WARNING, population=1025, offenders=0)
    failed = record_check(db, run_id=seed.run_id, check_name="results_are_resolved", scope="tier1",
                          severity=Severity.ERROR, population=1025, offenders=6, issues_opened=6)
    unknowable = record_check(db, run_id=seed.run_id, check_name="odds_coverage", scope="tier2",
                              severity=Severity.INFO, population=None, offenders=None)
    with db.cursor() as cur:
        cur.execute("SELECT id, passed, population, offenders, issues_opened FROM "
                    "audit.data_quality_checks WHERE id = ANY(%s) ORDER BY id",
                    ([passed, failed, unknowable],))
        assert cur.fetchall() == [(passed, True, 1025, 0, 0), (failed, False, 1025, 6, 6),
                                  (unknowable, True, None, None, 0)]


def test_more_offenders_than_the_population_is_refused(db: psycopg.Connection, seed: Seed) -> None:
    with must_be_rejected_saying(db, "check_offenders_fit_the_population"):
        db.execute(
            "INSERT INTO audit.data_quality_checks (run_id, check_name, scope, severity, passed, "
            " population, offenders) VALUES (%s,'impossible','t','warning',false,10,11)", (seed.run_id,)
        )


# ── the normaliser stops fixing the provider quietly ────────────────────────


def _detail(fixture: int, team: int, values: dict[str, object], unknown: tuple[str, ...] = ()) -> FixtureDetail:
    """A payload carrying ONLY the statistics block.

    The three blocks it does not carry each raise a MISSING_DETAIL issue, which is
    the point of recording per-dataset coverage - so the assertions below count by
    code rather than in total.
    """
    return FixtureDetail(
        provider_fixture_id=fixture,
        stats=(TeamStatsRef(provider_fixture_id=fixture, provider_team_id=team,
                            values=values, unknown_types=unknown),),  # type: ignore[arg-type]
        events=(), lineups=(), players=(), blocks_present=frozenset({"statistics"}),
    )


BLOCKS_ABSENT_FROM_A_STATISTICS_ONLY_PAYLOAD = 3


def _by_code(db: psycopg.Connection) -> dict[str, int]:
    with db.cursor() as cur:
        cur.execute("SELECT code, count(*) FROM audit.data_quality_issues GROUP BY 1")
        return {str(c): int(n) for c, n in cur.fetchall()}


@pytest.fixture()
def provider_ids(db: psycopg.Connection, seed: Seed) -> tuple[int, int]:
    """The seeded fixture and its home team, as the provider numbers them."""
    with db.cursor() as cur:
        cur.execute("SELECT f.provider_fixture_id, t.provider_team_id FROM core.fixtures f "
                    "JOIN core.teams t ON t.id = f.home_team_id WHERE f.id = %s", (seed.fixture_id,))
        row = cur.fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def test_a_contradiction_is_recorded_and_the_null_is_explained(
    db: psycopg.Connection, seed: Seed, provider_ids: tuple[int, int]
) -> None:
    """The exact failure the registry was built for.

    The schema's CHECK genuinely forbids shots_on_target > shots, so the value
    cannot be stored - but the row now says WHICH column was dropped, and the
    observed value survives in the registry and in the raw payload.
    """
    fixture, team = provider_ids
    report = apply_fixture_details(
        db, [_detail(fixture, team, {"shots": 5, "shots_on_target": 7, "corners": 4})],
        payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
    )
    assert report.stats_rows == 1
    assert _by_code(db) == {"PROVIDER_INCONSISTENCY": 1,
                            "MISSING_DETAIL": BLOCKS_ABSENT_FROM_A_STATISTICS_ONLY_PAYLOAD}
    with db.cursor() as cur:
        cur.execute("SELECT shots, shots_on_target, corners, dropped_fields FROM core.fixture_team_stats "
                    "WHERE fixture_id = %s AND team_side = 'home'", (seed.fixture_id,))
        assert cur.fetchone() == (5, None, 4, ["shots_on_target"])
        cur.execute("SELECT code, field, observed, expected, observed_number, expected_number, detail, "
                    "       payload_hash, run_id FROM audit.data_quality_issues "
                    "WHERE entity_type = 'team_statistics'")
        row = cur.fetchone()
    assert row is not None
    assert row[:6] == ("PROVIDER_INCONSISTENCY", "shots_on_target", "7", "at most shots (5)",
                       Decimal("7"), None)
    assert "the provider reported shots_on_target=7 with shots=5" in row[6]
    assert (row[7], row[8]) == (seed.payload_hash, seed.run_id)


def test_a_negative_count_is_recorded_too(
    db: psycopg.Connection, seed: Seed, provider_ids: tuple[int, int]
) -> None:
    fixture, team = provider_ids
    apply_fixture_details(
        db, [_detail(fixture, team, {"shots": 9, "corners": -2})],
        payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
    )
    assert _by_code(db)["PROVIDER_INCONSISTENCY"] == 1
    with db.cursor() as cur:
        cur.execute("SELECT field, observed, detail, dropped_fields FROM audit.data_quality_issues i "
                    "JOIN core.fixture_team_stats s ON s.fixture_id = i.entity_id "
                    "WHERE i.code = 'PROVIDER_INCONSISTENCY'")
        row = cur.fetchone()
    assert row is not None
    assert (row[0], row[1], row[3]) == ("corners", "-2", ["corners"])
    assert "not a statistic" in row[2]


def test_an_unknown_statistic_type_stops_being_only_a_log_line(
    db: psycopg.Connection, seed: Seed, provider_ids: tuple[int, int]
) -> None:
    """A new provider field must not look like one we never received."""
    fixture, team = provider_ids
    report = apply_fixture_details(
        db, [_detail(fixture, team, {"shots": 9}, unknown=("Big Chances Created", "Total Duels"))],
        payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
    )
    assert report.unknown_stat_types == {"Big Chances Created", "Total Duels"}
    assert _by_code(db)["UNKNOWN_PROVIDER_ENTITY"] == 2
    with db.cursor() as cur:
        cur.execute("SELECT observed FROM audit.data_quality_issues "
                    "WHERE code = 'UNKNOWN_PROVIDER_ENTITY' ORDER BY observed")
        assert [r[0] for r in cur.fetchall()] == ["Big Chances Created", "Total Duels"]


def test_a_coherent_payload_reports_no_contradiction(
    db: psycopg.Connection, seed: Seed, provider_ids: tuple[int, int]
) -> None:
    fixture, team = provider_ids
    report = apply_fixture_details(
        db, [_detail(fixture, team, {"shots": 12, "shots_on_target": 5, "passes": 400,
                                     "passes_accurate": 350})],
        payload_hash=seed.payload_hash, fetched_at=FETCHED, run_id=seed.run_id,
    )
    assert report.stats_rows == 1
    assert "PROVIDER_INCONSISTENCY" not in _by_code(db)
    with db.cursor() as cur:
        cur.execute("SELECT dropped_fields FROM core.fixture_team_stats WHERE fixture_id = %s",
                    (seed.fixture_id,))
        assert cur.fetchone() == ([],), "nothing was dropped, so nothing is named"


def test_reapplying_the_same_payload_does_not_inflate_the_count(
    db: psycopg.Connection, seed: Seed, provider_ids: tuple[int, int]
) -> None:
    fixture, team = provider_ids
    detail = _detail(fixture, team, {"shots": 5, "shots_on_target": 7})
    for _ in range(3):
        apply_fixture_details(db, [detail], payload_hash=seed.payload_hash, fetched_at=FETCHED,
                              run_id=seed.run_id)
    with db.cursor() as cur:
        cur.execute("SELECT count(*), max(occurrences), min(occurrences) FROM audit.data_quality_issues")
        assert cur.fetchone() == (1 + BLOCKS_ABSENT_FROM_A_STATISTICS_ONLY_PAYLOAD, 3, 3), \
            "the same problems, three sightings each"
