"""The sweep: find what can go wrong, record it, repair nothing.

Every check reports its DENOMINATOR as well as its offenders, because a coverage
figure without one is invented. And every offender becomes an issue with its
provenance, because "we noticed and did nothing about it" is only useful if the
noticing was written down.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.quality.detect import (
    check_lineage_holds,
    check_lineups_are_complete,
    check_results_are_not_stale,
    check_results_are_resolved,
    check_values_are_possible,
    sweep,
)
from fbi.quality.issues import IssueCode, Severity
from tests.integration.conftest import Seed

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
FETCHED = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clock() -> Iterator[FrozenClock]:
    frozen = FrozenClock(NOW)
    set_clock(frozen)
    yield frozen
    set_clock(SystemClock())


@pytest.fixture(autouse=True)
def only_this_test(db: psycopg.Connection) -> Iterator[None]:
    """sweep() commits after every check, so this module cannot rely on the db
    fixture's rollback: what it creates it removes."""
    db.execute("DELETE FROM audit.data_quality_issues")
    db.execute("DELETE FROM audit.data_quality_checks")
    yield
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM audit.data_quality_issues")
        cur.execute("DELETE FROM audit.data_quality_checks")
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 84000 AND 84999")
    db.commit()


def _fixture(db: psycopg.Connection, seed: Seed, pid: int, *, status: str, group: str,
             kickoff: datetime | None = None) -> int:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
            "away_team_id, kickoff_at, status_short, status_group) VALUES (%s,%s,%s,%s,%s,%s,%s) "
            "RETURNING id",
            (pid, seed.season_id, seed.home_team_id, seed.away_team_id,
             kickoff or (NOW - timedelta(days=2)), status, group),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


# ── results that cannot be derived ──────────────────────────────────────────


def test_a_penalty_shoot_out_without_an_extra_time_score_is_unresolved(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The six fixtures the mandate names. reg_goals_* is goals minus extra-time
    goals, so with no extra-time score it equals the after-extra-time score -
    and settling a 90-minute market on that counts extra-time goals as regulation
    goals. The shoot-out is NOT turned into a 90-minute result."""
    fid = _fixture(db, seed, 84001, status="PEN", group="finished")
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, pen_home, pen_away) "
               "VALUES (%s,1,1,4,3)", (fid,))
    outcome = check_results_are_resolved(db)
    assert outcome.offenders >= 1 and not outcome.passed
    assert outcome.population is not None and outcome.population >= outcome.offenders
    mine = [i for i in outcome.issues if i.entity_id == fid]
    assert len(mine) == 1
    assert mine[0].code is IssueCode.RESULT_UNRESOLVED and mine[0].severity is Severity.ERROR
    assert mine[0].field == "et_goals_home" and mine[0].observed == "1-1"
    assert mine[0].detail is not None and "cannot be derived" in mine[0].detail


def test_extra_time_with_a_recorded_score_is_resolved(db: psycopg.Connection, seed: Seed) -> None:
    fid = _fixture(db, seed, 84002, status="AET", group="finished")
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, et_goals_home, "
               "et_goals_away) VALUES (%s,3,1,1,0)", (fid,))
    assert [i for i in check_results_are_resolved(db).issues if i.entity_id == fid] == []


def test_a_finished_fixture_with_no_result_row_is_unresolved(
    db: psycopg.Connection, seed: Seed
) -> None:
    fid = _fixture(db, seed, 84003, status="FT", group="finished")
    mine = [i for i in check_results_are_resolved(db).issues if i.entity_id == fid]
    assert len(mine) == 1
    assert mine[0].detail is not None and "no row in core.fixture_results" in mine[0].detail


def test_the_check_reports_the_denominator_it_used(db: psycopg.Connection, seed: Seed) -> None:
    """Six unresolved out of how many? Without the population the number means
    nothing, and a ratio computed without one would be a lie."""
    outcome = check_results_are_resolved(db)
    assert outcome.population is not None
    assert outcome.ratio is None or 0.0 <= outcome.ratio <= 1.0


# ── line-ups ────────────────────────────────────────────────────────────────


def test_a_lineup_short_of_eleven_starters_is_found_and_not_padded(
    db: psycopg.Connection, seed: Seed
) -> None:
    fid = _fixture(db, seed, 84004, status="FT", group="finished")
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, "
                    "payload_hash, fetched_at) VALUES (%s,'home','api-football','4-4-2',%s,%s)",
                    (fid, seed.payload_hash, FETCHED))
        for n in range(9):
            cur.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, "
                        "provider_player_id, player_name, is_starter) "
                        "VALUES (%s,'home','api-football',%s,%s,true)", (fid, 9500 + n, f"P{n}"))
    outcome = check_lineups_are_complete(db)
    mine = [i for i in outcome.issues if i.entity_id == fid]
    assert len(mine) == 1 and mine[0].observed == 9 and mine[0].expected == "11"
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixture_lineup_players WHERE fixture_id = %s", (fid,))
        assert cur.fetchone() == (9,), "recorded, not padded"


def test_a_complete_lineup_is_not_reported(db: psycopg.Connection, seed: Seed) -> None:
    fid = _fixture(db, seed, 84005, status="FT", group="finished")
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, "
                    "fetched_at) VALUES (%s,'away','api-football',%s,%s)",
                    (fid, seed.payload_hash, FETCHED))
        for n in range(11):
            cur.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, "
                        "provider_player_id, player_name, is_starter) "
                        "VALUES (%s,'away','api-football',%s,%s,true)", (fid, 9600 + n, f"P{n}"))
    assert [i for i in check_lineups_are_complete(db).issues if i.entity_id == fid] == []


# ── impossible values ───────────────────────────────────────────────────────


def test_impossible_possession_is_recorded_not_corrected(db: psycopg.Connection, seed: Seed) -> None:
    fid = _fixture(db, seed, 84006, status="FT", group="finished")
    db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, possession_pct, "
               "payload_hash, fetched_at) VALUES (%s,'home','api-football',100,%s,%s)",
               (fid, seed.payload_hash, FETCHED))
    mine = [i for i in check_values_are_possible(db).issues if i.entity_id == fid]
    assert len(mine) == 1 and mine[0].field == "possession_pct"
    with db.cursor() as cur:
        cur.execute("SELECT possession_pct FROM core.fixture_team_stats WHERE fixture_id = %s", (fid,))
        assert cur.fetchone() == (100,), "left exactly as the provider sent it"


def test_an_event_after_the_130th_minute_is_recorded(db: psycopg.Connection, seed: Seed) -> None:
    fid = _fixture(db, seed, 84007, status="FT", group="finished")
    db.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, event_type, "
               "payload_hash, fetched_at) VALUES (%s,'api-football',0,145,'Goal',%s,%s)",
               (fid, seed.payload_hash, FETCHED))
    mine = [i for i in check_values_are_possible(db).issues if i.entity_id == fid]
    assert len(mine) == 1 and mine[0].observed == 145


# ── stale ───────────────────────────────────────────────────────────────────


def test_a_fixture_still_scheduled_six_hours_after_kickoff_is_stale(
    db: psycopg.Connection, seed: Seed
) -> None:
    fid = _fixture(db, seed, 84008, status="NS", group="scheduled",
                   kickoff=NOW - timedelta(hours=9))
    mine = [i for i in check_results_are_not_stale(db).issues if i.entity_id == fid]
    assert len(mine) == 1 and mine[0].code is IssueCode.STALE_DATA


def test_a_fixture_that_kicked_off_an_hour_ago_is_not_stale(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Extra time, penalties and a delay all fit inside six hours."""
    fid = _fixture(db, seed, 84009, status="1H", group="live", kickoff=NOW - timedelta(hours=1))
    assert [i for i in check_results_are_not_stale(db).issues if i.entity_id == fid] == []


# ── lineage ─────────────────────────────────────────────────────────────────


def test_a_row_dated_after_its_own_payload_is_found(db: psycopg.Connection, seed: Seed) -> None:
    """The fault that hid 1,809 fixtures' detail: the raw store keeps identical
    bodies once and indexes the first fetch, so a writer given the second fetch
    time produces a row newer than the payload it names."""
    fid = _fixture(db, seed, 84010, status="FT", group="finished")
    with db.cursor() as cur:
        cur.execute("SELECT fetched_at FROM raw.ingestion_payloads WHERE hash = %s",
                    (seed.payload_hash,))
        row = cur.fetchone()
    assert row is not None
    db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, "
               "payload_hash, fetched_at) VALUES (%s,'home','api-football',9,%s,%s)",
               (fid, seed.payload_hash, row[0] + timedelta(minutes=8)))
    outcome = check_lineage_holds(db)
    drifted = [i for i in outcome.issues if i.field == "fixture_team_stats"]
    assert len(drifted) == 1
    assert drifted[0].code is IssueCode.LINEAGE_BROKEN
    assert drifted[0].detail is not None and "deduplicates identical bodies" in drifted[0].detail


def test_a_row_dated_with_its_payload_is_fine(db: psycopg.Connection, seed: Seed) -> None:
    fid = _fixture(db, seed, 84011, status="FT", group="finished")
    with db.cursor() as cur:
        cur.execute("SELECT fetched_at FROM raw.ingestion_payloads WHERE hash = %s",
                    (seed.payload_hash,))
        row = cur.fetchone()
    assert row is not None
    db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, "
               "payload_hash, fetched_at) VALUES (%s,'home','api-football',9,%s,%s)",
               (fid, seed.payload_hash, row[0]))
    assert [i for i in check_lineage_holds(db).issues if i.field == "fixture_team_stats"] == []


# ── the sweep as a whole ────────────────────────────────────────────────────


def test_the_sweep_records_every_check_with_its_denominator_or_says_it_has_none(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Five checks count offenders out of a population. Two span more than one
    population - statistics rows and event rows; near-close rows and three detail
    tables - and report NULL rather than picking one, because a ratio over the
    wrong denominator is worse than no ratio.

    The schema enforces the distinction: offenders <= population. The first version
    of check_lineage_holds reported 3 offenders out of a population of 0 and the
    constraint refused the row.
    """
    report = sweep(db, run_id=seed.run_id, apply=True)
    assert len(report.checks) == 7
    with db.cursor() as cur:
        cur.execute("SELECT check_name, population, offenders FROM audit.data_quality_checks "
                    "WHERE run_id = %s ORDER BY check_name", (seed.run_id,))
        rows = {str(n): (p, o) for n, p, o in cur.fetchall()}
    assert len(rows) == 7
    assert rows["values_are_possible"][0] is None
    assert rows["lineage_holds"][0] is None
    for name in ("results_are_resolved", "lineups_are_complete", "detail_has_been_fetched",
                 "results_are_not_stale", "prices_come_from_known_books"):
        population, offenders = rows[name]
        assert population is not None, f"{name} has one population and must report it"
        assert offenders is not None and offenders <= population
    assert all(c.ratio is None for c in report.checks if c.population is None), \
        "no denominator, no ratio: never an invented 0.0 or 1.0"


def test_a_verify_only_sweep_writes_nothing(db: psycopg.Connection, seed: Seed) -> None:
    fid = _fixture(db, seed, 84012, status="PEN", group="finished")
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s,2,2)",
               (fid,))
    report = sweep(db, run_id=seed.run_id, apply=False)
    assert report.offenders > 0 and report.issues_opened == 0
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit.data_quality_issues")
        assert cur.fetchone() == (0,)
        cur.execute("SELECT count(*) FROM audit.data_quality_checks WHERE run_id = %s", (seed.run_id,))
        assert cur.fetchone() == (0,)


def test_running_the_sweep_twice_does_not_inflate_its_own_numbers(
    db: psycopg.Connection, seed: Seed
) -> None:
    fid = _fixture(db, seed, 84013, status="PEN", group="finished")
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s,0,0)",
               (fid,))
    first = sweep(db, run_id=seed.run_id, apply=True)
    second = sweep(db, run_id=seed.run_id, apply=True)
    assert first.issues_opened > 0
    assert second.issues_opened == 0 and second.issues_seen_again == first.issues_opened
    with db.cursor() as cur:
        cur.execute("SELECT code, count(*), max(occurrences) FROM audit.data_quality_issues "
                    "WHERE entity_id = %s GROUP BY 1 ORDER BY 1", (fid,))
        rows = cur.fetchall()
    assert rows == [("MISSING_DETAIL", 1, 2), ("RESULT_UNRESOLVED", 1, 2)], \
        "two different problems about one fixture, each seen twice - not four problems"
