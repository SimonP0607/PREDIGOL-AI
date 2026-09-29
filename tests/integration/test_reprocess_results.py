"""Correcting 78 wrong 90-minute scores from bytes already on disk, for no request.

reg_goals_*, outcome_1x2, total_goals and btts all derived the 90-minute score as
``goals - COALESCE(et_goals, 0)``. Where the provider gives ``extratime`` as the running
total - 82 of 1,645 measured extra-time fixtures - that yields 0, so a tie that stood
2-1 after ninety minutes was stored as 0-0 and settled 'Draw'. The provider states the
score in ``score.fulltime`` and always did, in payloads already in the raw store.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from fbi.ingestion.payload_store import PayloadStore
from fbi.ops.reprocess import reprocess_results
from tests.integration.conftest import Seed

FETCHED = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)


@pytest.fixture()
def raw_root(tmp_path: Path) -> Path:
    return tmp_path / "raw"


@pytest.fixture(autouse=True)
def clean_slate(db: psycopg.Connection) -> Iterator[None]:
    yield
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM core.fixture_results r USING core.fixtures f "
                    "WHERE r.fixture_id = f.id AND f.provider_fixture_id BETWEEN 84000 AND 84999")
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 84000 AND 84999")
        cur.execute("DELETE FROM audit.data_quality_issues WHERE provider_entity_id BETWEEN 84000 AND 84999")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE endpoint = '/fixtures'")
    db.commit()


def score_body(fid: int, status: str, *, goals: tuple[int, int],
               fulltime: tuple[int | None, int | None],
               extratime: tuple[int | None, int | None] = (None, None),
               penalty: tuple[int | None, int | None] = (None, None)) -> dict:
    def block(pair: tuple[int | None, int | None]) -> dict:
        return {"home": pair[0], "away": pair[1]}
    return {"response": [{
        "fixture": {"id": fid, "date": "2026-02-01T15:00:00+00:00", "status": {"short": status}},
        "goals": block(goals),
        "score": {"halftime": block((0, 0)), "fulltime": block(fulltime),
                  "extratime": block(extratime), "penalty": block(penalty)},
    }], "errors": [], "results": 1}


def store(db: psycopg.Connection, seed: Seed, raw_root: Path, body: dict, *, ids: str) -> str:
    stored = PayloadStore(raw_root).store(endpoint="/fixtures", params={"ids": ids},
                                          fetched_at=FETCHED, http_status=200, body=body)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, "
            " http_status, results_count, file_path, bytes) "
            "VALUES (%s,%s,'/fixtures',%s::jsonb,%s,200,1,%s,%s) ON CONFLICT (hash) DO NOTHING",
            (stored.hash, seed.run_id, json.dumps({"ids": ids}), FETCHED, stored.file_path,
             stored.bytes_written),
        )
    db.commit()
    return stored.hash


def fixture_row(db: psycopg.Connection, seed: Seed, fid: int, status: str) -> int:
    row = db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
        " away_team_id, kickoff_at, status_short, status_group) "
        "VALUES (%s,%s,%s,%s,'2026-02-01T15:00Z',%s,'finished') RETURNING id",
        (fid, seed.season_id, seed.home_team_id, seed.away_team_id, status)).fetchone()
    assert row is not None
    db.commit()
    return int(row[0])


def derived(db: psycopg.Connection, fid: int) -> tuple:
    row = db.execute(
        "SELECT r.ft_goals_home, r.ft_goals_away, r.reg_goals_home, r.reg_goals_away, "
        "       r.outcome_1x2, r.total_goals, r.btts "
        "  FROM core.fixture_results r JOIN core.fixtures f ON f.id = r.fixture_id "
        " WHERE f.provider_fixture_id = %s", (fid,)).fetchone()
    return tuple(row) if row is not None else ()


def test_a_running_total_extratime_is_corrected_from_the_stored_payload(
    db: psycopg.Connection, seed: Seed, raw_root: Path
) -> None:
    """The shape of all 78: goals 3-1, extratime 3-1, so the subtraction said 0-0 Draw.
    fulltime says 2-1, which is a home win."""
    fixture_row(db, seed, 84001, "AET")
    store(db, seed, raw_root, score_body(84001, "AET", goals=(3, 1), fulltime=(2, 1),
                                         extratime=(3, 1)), ids="84001")

    report = reprocess_results(db, raw_root, apply=True)

    assert report.fixtures_touched == 1
    ft_h, ft_a, reg_h, reg_a, outcome, total, btts = derived(db, 84001)
    assert (ft_h, ft_a) == (2, 1)
    assert (reg_h, reg_a) == (2, 1), "the generated column follows the stated score"
    assert outcome == "Home", "not the Draw the subtraction produced"
    assert total == 3 and btts is True


def test_the_disagreement_becomes_a_quality_issue_not_just_a_printed_line(
    db: psycopg.Connection, seed: Seed, raw_root: Path
) -> None:
    """The registry is where "the provider contradicted itself" belongs. A printed line
    disappears; an operator asking later why a match settled oddly needs the record."""
    fixture_row(db, seed, 84002, "AET")
    store(db, seed, raw_root, score_body(84002, "AET", goals=(3, 1), fulltime=(2, 1),
                                         extratime=(3, 1)), ids="84002")

    report = reprocess_results(db, raw_root, apply=True)

    assert report.issues_opened == 1
    assert any("84002" in p for p in report.problems)
    row = db.execute(
        "SELECT code, entity_type, field, observed, detail FROM audit.data_quality_issues "
        " WHERE provider_entity_id = 84002").fetchone()
    assert row is not None
    assert row[0] == "PROVIDER_INCONSISTENCY" and row[1] == "fixture_result"
    assert "running total" in (row[4] or "")


def test_a_self_contradictory_score_is_recorded_even_though_no_result_is_written(
    db: psycopg.Connection, seed: Seed, raw_root: Path
) -> None:
    """Five finished AET fixtures on the machine give extratime greater than the final
    score. No result can be derived, and the reason must not be a mystery."""
    fixture_row(db, seed, 84009, "AET")
    store(db, seed, raw_root, score_body(84009, "AET", goals=(2, 0), fulltime=(4, 0),
                                         extratime=(0, 2)), ids="84009")

    reprocess_results(db, raw_root, apply=True)

    assert derived(db, 84009) == (), "nothing is invented"
    row = db.execute("SELECT code, field, observed FROM audit.data_quality_issues "
                     " WHERE provider_entity_id = 84009").fetchone()
    assert row is not None and row[0] == "PROVIDER_INCONSISTENCY"


def test_penalties_straight_from_ninety_minutes_gain_the_result_they_never_had(
    db: psycopg.Connection, seed: Seed, raw_root: Path
) -> None:
    """Six Champions League ties had no result row at all, because a PEN fixture with a
    null extratime was skipped wholesale."""
    fixture_row(db, seed, 84003, "PEN")
    store(db, seed, raw_root, score_body(84003, "PEN", goals=(1, 0), fulltime=(1, 0),
                                         penalty=(6, 5)), ids="84003")

    reprocess_results(db, raw_root, apply=True)

    ft_h, ft_a, reg_h, reg_a, outcome, _total, _btts = derived(db, 84003)
    assert (ft_h, ft_a) == (1, 0) and (reg_h, reg_a) == (1, 0)
    assert outcome == "Home", "the shoot-out decides the tie; the market settles on ninety minutes"


def test_an_incremental_extratime_is_unchanged(
    db: psycopg.Connection, seed: Seed, raw_root: Path
) -> None:
    """1,557 of 1,645 fixtures. The correction must not disturb them."""
    fixture_row(db, seed, 84004, "AET")
    store(db, seed, raw_root, score_body(84004, "AET", goals=(3, 1), fulltime=(2, 1),
                                         extratime=(1, 0)), ids="84004")

    report = reprocess_results(db, raw_root, apply=True)

    assert report.issues_opened == 0
    ft_h, ft_a, reg_h, reg_a, outcome, _t, _b = derived(db, 84004)
    assert (ft_h, ft_a) == (2, 1) and (reg_h, reg_a) == (2, 1) and outcome == "Home"


def test_verifying_without_applying_writes_nothing(
    db: psycopg.Connection, seed: Seed, raw_root: Path
) -> None:
    fixture_row(db, seed, 84005, "AET")
    store(db, seed, raw_root, score_body(84005, "AET", goals=(3, 1), fulltime=(2, 1),
                                         extratime=(3, 1)), ids="84005")

    report = reprocess_results(db, raw_root, apply=False)

    assert report.fixtures_touched == 1, "it says what it would do"
    assert derived(db, 84005) == (), "and does none of it"


def test_reprocessing_twice_changes_nothing(
    db: psycopg.Connection, seed: Seed, raw_root: Path
) -> None:
    fixture_row(db, seed, 84006, "AET")
    store(db, seed, raw_root, score_body(84006, "AET", goals=(3, 1), fulltime=(2, 1),
                                         extratime=(3, 1)), ids="84006")

    reprocess_results(db, raw_root, apply=True)
    first = derived(db, 84006)
    reprocess_results(db, raw_root, apply=True)

    assert derived(db, 84006) == first


def test_a_season_payload_is_replayed_too_not_only_the_id_batches(
    db: psycopg.Connection, seed: Seed, raw_root: Path
) -> None:
    """Scores arrive in both shapes /fixtures is called in, and the season pass is where
    most of them come from. A replay restricted to ?ids= batches would correct a small
    fraction and look finished."""
    fixture_row(db, seed, 84008, "AET")
    body = score_body(84008, "AET", goals=(3, 1), fulltime=(2, 1), extratime=(3, 1))
    stored = PayloadStore(raw_root).store(
        endpoint="/fixtures", params={"league": 39, "season": 2025}, fetched_at=FETCHED,
        http_status=200, body=body)
    db.execute(
        "INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, "
        " http_status, results_count, file_path, bytes) "
        "VALUES (%s,%s,'/fixtures',%s::jsonb,%s,200,1,%s,%s) ON CONFLICT (hash) DO NOTHING",
        (stored.hash, seed.run_id, json.dumps({"league": 39, "season": 2025}), FETCHED,
         stored.file_path, stored.bytes_written))
    db.commit()

    report = reprocess_results(db, raw_root, apply=True)

    assert report.fixtures_touched == 1, "a season payload carries scores just as a batch does"
    ft_h, ft_a, reg_h, reg_a, outcome, _t, _b = derived(db, 84008)
    assert (ft_h, ft_a) == (2, 1) and (reg_h, reg_a) == (2, 1) and outcome == "Home"


def test_a_ninety_minute_score_above_the_final_score_never_reaches_the_table(
    db: psycopg.Connection, seed: Seed, raw_root: Path
) -> None:
    """The CHECK would refuse it; the normaliser drops it first, so the rest of the row
    still lands."""
    fixture_row(db, seed, 84007, "FT")
    store(db, seed, raw_root, score_body(84007, "FT", goals=(1, 0), fulltime=(3, 0)), ids="84007")

    reprocess_results(db, raw_root, apply=True)

    ft_h, ft_a, reg_h, reg_a, _o, _t, _b = derived(db, 84007)
    assert (ft_h, ft_a) == (None, None)
    assert (reg_h, reg_a) == (1, 0), "it falls back to the behaviour it had before"
