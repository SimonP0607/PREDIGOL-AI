"""Plan F0, defect 5, first half: a correction of a result is a recorded revision (migration 0080).

The result of a match is overwritten in place by whichever writer reads a newer payload; until now the previous score was
gone the moment the new one was written. A trigger on ``core.fixture_results`` (and one on the status of a match that had
finished) writes the history, so no writer can skip it. The transaction is rolled back after each test."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ingestion.fixtures import PayloadLineage
from fbi.ingestion.results import ResultRepository
from fbi.providers.base import FixtureResultRef

from .conftest import Seed
from .helpers import scalar

KICKOFF = datetime(2032, 8, 1, 12, tzinfo=UTC)


def fixture(db: psycopg.Connection[Any], seed: Seed, n: int, *, status: str = "NS", group: str = "scheduled") -> int:
    teams = [scalar(db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                               (976000 + 2 * n + side, f"Rev-{n}-{side}"))) for side in (0, 1)]
    return int(scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
        "status_short, status_group) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (7360000 + n, seed.season_id, teams[0], teams[1], KICKOFF, status, group))))


def revisions(db: psycopg.Connection[Any], fixture_id: int) -> list[tuple[Any, ...]]:
    return db.execute("SELECT kind, changed, old_state, new_state FROM core.fixture_result_revisions "
                      "WHERE fixture_id = %s ORDER BY id", (fixture_id,)).fetchall()


def ref(provider_id: int, status: str, home: int, away: int, **extra: int | None) -> FixtureResultRef:
    return FixtureResultRef(provider_fixture_id=provider_id, status_short=status, goals_home=home, goals_away=away,
                            ht_goals_home=extra.get("ht_goals_home"), ht_goals_away=extra.get("ht_goals_away"),
                            ft_goals_home=extra.get("ft_goals_home"), ft_goals_away=extra.get("ft_goals_away"),
                            et_goals_home=extra.get("et_goals_home"), et_goals_away=extra.get("et_goals_away"),
                            pen_home=extra.get("pen_home"), pen_away=extra.get("pen_away"))


def lineage(db: psycopg.Connection[Any], seed: Seed, tag: str, minutes: int) -> PayloadLineage:
    """A stored payload fetched ``minutes`` after kick-off (the fixtures and results rows point at it)."""
    at = KICKOFF + timedelta(minutes=minutes)
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, "
               "bytes) VALUES (%s, %s, '/fixtures', '{}', %s, 200, %s, 1)", (f"rev-{tag}", seed.run_id, at, tag))
    return PayloadLineage(payload_hash=f"rev-{tag}", fetched_at=at)


def test_the_first_read_of_a_result_is_not_a_revision_and_a_correction_is(db: psycopg.Connection[Any],
                                                                          seed: Seed) -> None:
    f = fixture(db, seed, 1)
    repo = ResultRepository(db)
    repo.apply([ref(7360001, "FT", 2, 1)], lineage=lineage(db, seed, "a1", 110))
    assert revisions(db, f) == [], "the first read is the result, not a correction of it"

    repo.apply([ref(7360001, "FT", 2, 1)], lineage=lineage(db, seed, "a2", 260))
    assert revisions(db, f) == [], "the same score in a newer payload corrects nothing"
    assert db.execute("SELECT source_payload_hash FROM core.fixture_results WHERE fixture_id = %s",
                      (f,)).fetchone() == ("rev-a2",), "(the lineage still moves)"

    repo.apply([ref(7360001, "FT", 1, 1)], lineage=lineage(db, seed, "a3", 300))
    [(kind, changed, old, new)] = revisions(db, f)
    assert kind == "score" and set(changed) == {"goals_home", "reg_goals_home"}
    assert (old["goals_home"], old["goals_away"], old["reg_goals_home"], old["reg_goals_away"]) == (2, 1, 2, 1)
    assert (new["goals_home"], new["goals_away"], new["reg_goals_home"], new["reg_goals_away"]) == (1, 1, 1, 1)
    row = db.execute("SELECT before_payload_hash, after_payload_hash, after_fetched_at, observed_at "
                     "FROM core.fixture_result_revisions WHERE fixture_id = %s", (f,)).fetchone()
    assert row is not None and row[:3] == ("rev-a2", "rev-a3", KICKOFF + timedelta(minutes=300))
    assert row[3] is not None


def test_an_older_payload_cannot_correct_a_newer_result_and_so_leaves_no_revision(db: psycopg.Connection[Any],
                                                                                  seed: Seed) -> None:
    f = fixture(db, seed, 2)
    repo = ResultRepository(db)
    repo.apply([ref(7360002, "FT", 3, 0)], lineage=lineage(db, seed, "b1", 300))
    repo.apply([ref(7360002, "FT", 0, 0)], lineage=lineage(db, seed, "b2", 110))  # fetched earlier: refused
    assert revisions(db, f) == []
    assert db.execute("SELECT goals_home FROM core.fixture_results WHERE fixture_id = %s", (f,)).fetchone() == (3,)


@pytest.mark.parametrize(("first", "second", "changed"), [
    ({}, {"ft_goals_home": 2, "ft_goals_away": 1}, {"ft_goals_home", "ft_goals_away"}),
    ({"ht_goals_home": 0, "ht_goals_away": 0}, {"ht_goals_home": 1, "ht_goals_away": 0}, {"ht_goals_home"}),
    ({"pen_home": None, "pen_away": None}, {"pen_home": 4, "pen_away": 3}, {"pen_home", "pen_away"}),
], ids=["the stated 90-minute score appears", "the half-time score", "a shoot-out"])
def test_every_score_column_is_watched(db: psycopg.Connection[Any], seed: Seed, first: dict[str, int | None],
                                       second: dict[str, int | None], changed: set[str]) -> None:
    f = fixture(db, seed, 3)
    repo = ResultRepository(db)
    repo.apply([ref(7360003, "FT", 2, 1, **first)], lineage=lineage(db, seed, "c1", 110))
    repo.apply([ref(7360003, "FT", 2, 1, **second)], lineage=lineage(db, seed, "c2", 260))
    [(kind, got, _old, _new)] = revisions(db, f)
    assert kind == "score" and changed <= set(got)


def test_a_match_that_had_finished_and_changes_status_is_a_revision_and_the_normal_path_is_not(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    f = fixture(db, seed, 4)
    db.execute("UPDATE core.fixtures SET status_short = '2H', status_group = 'live' WHERE id = %s", (f,))
    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (f,))
    assert revisions(db, f) == [], "scheduled -> in play -> finished is a match being played, not a correction"

    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished', updated_at = now() "
               "WHERE id = %s", (f,))
    assert revisions(db, f) == [], "the same status again changes nothing"

    db.execute("UPDATE core.fixtures SET status_short = 'AET', status_group = 'finished' WHERE id = %s", (f,))
    db.execute("UPDATE core.fixtures SET status_short = 'AWD', status_group = 'cancelled' WHERE id = %s", (f,))
    got = revisions(db, f)
    assert [(k, c) for k, c, _, _ in got] == [("status", ["status_short"]), ("status", ["status_short"])]
    assert got[0][2] == {"status_short": "FT", "status_group": "finished"}
    assert got[1][3] == {"status_short": "AWD", "status_group": "cancelled"}


def test_the_history_is_never_edited_and_goes_only_with_its_fixture(db: psycopg.Connection[Any], seed: Seed) -> None:
    f = fixture(db, seed, 5)
    repo = ResultRepository(db)
    repo.apply([ref(7360005, "FT", 1, 0)], lineage=lineage(db, seed, "d1", 110))
    repo.apply([ref(7360005, "FT", 1, 1)], lineage=lineage(db, seed, "d2", 260))
    with pytest.raises(psycopg.errors.CheckViolation, match="never edited"), db.transaction():
        db.execute("UPDATE core.fixture_result_revisions SET new_state = old_state WHERE fixture_id = %s", (f,))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE core.fixture_result_revisions SET observed_at = observed_at - interval '1 day'")
    assert len(revisions(db, f)) == 1
    db.execute("DELETE FROM core.fixtures WHERE id = %s", (f,))
    assert revisions(db, f) == []


def test_a_result_write_does_not_depend_on_the_writer_being_able_to_write_the_history(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    """The trigger functions are SECURITY DEFINER: the role that writes results needs no right on the history."""
    f = fixture(db, seed, 6)
    ResultRepository(db).apply([ref(7360006, "FT", 1, 0)], lineage=lineage(db, seed, "e1", 110))
    db.execute("DO $$ BEGIN CREATE ROLE history_blind NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    try:
        db.execute("GRANT USAGE ON SCHEMA core TO history_blind")
        db.execute("GRANT SELECT, UPDATE ON core.fixture_results TO history_blind")
        db.execute("GRANT SELECT ON core.fixtures TO history_blind")
        db.execute("SET LOCAL ROLE history_blind")
        with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
            db.execute("SELECT count(*) FROM core.fixture_result_revisions").fetchone()
        db.execute("UPDATE core.fixture_results SET goals_home = 2 WHERE fixture_id = %s", (f,))
        db.execute("RESET ROLE")
        [(kind, _changed, _old, new)] = revisions(db, f)
        assert kind == "score" and new["goals_home"] == 2
    finally:
        db.execute("RESET ROLE")
        db.rollback()
