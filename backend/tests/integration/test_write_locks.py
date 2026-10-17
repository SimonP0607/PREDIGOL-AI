"""Teams that a payload names as they are are not written or locked (9 Oct 2026, on the server).

Every /fixtures payload rewrote every team it named, so the in-play capture waited on the fixtures sync (three waits
of seven minutes). A row merely read is locked by nobody: another transaction can take it at once (FOR UPDATE NOWAIT
does not fail).

(The model registry's upsert, which made two overlapping pick passes wait on each other, is left as it was: it lives
in fbi.backtesting, part of the model-code fingerprint, and changing it made a new version of every model - 9 Oct
2026, 13:19-13:4x UTC. One pass at a time (apps.worker.scheduler.OnePass) is what removes that wait.)
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import psycopg
import pytest

from fbi.ingestion.fixtures import FixtureRepository
from fbi.providers.base import FixtureRef
from tests.integration.conftest import Seed

KICKOFF = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)


@pytest.fixture
def other(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database, autocommit=True) as c:
        yield c


def _free(conn: psycopg.Connection, sql: str, *args: object) -> bool:
    """Whether another transaction can lock these rows right now (the probe's own lock is rolled back at once)."""
    try:
        with conn.transaction():
            conn.execute("SET LOCAL lock_timeout = '2s'")
            conn.execute(sql + " FOR UPDATE NOWAIT", args).fetchall()
            raise psycopg.Rollback()
    except psycopg.errors.LockNotAvailable:
        return False
    return True


@pytest.fixture
def teams(migrated_database: str, seed: Seed) -> dict[int, int]:
    """Two teams of this module's own, committed with known names (other tests rename the seed's)."""
    with psycopg.connect(migrated_database, autocommit=True) as c:
        rows = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (880001, 'Alpha FC'), (880002, 'Beta FC') "
                         "ON CONFLICT (provider_team_id) DO UPDATE SET name = EXCLUDED.name "
                         "RETURNING provider_team_id, id").fetchall()
    return {int(p): int(i) for p, i in rows}


def test_a_payload_that_names_known_teams_as_they_are_writes_and_locks_nothing(
        db: psycopg.Connection, other: psycopg.Connection, teams: dict[int, int]) -> None:
    repo = FixtureRepository(db)
    ref = FixtureRef(990001, 39, 2025, KICKOFF, 880001, 880002, "NS")
    sql = "SELECT provider_team_id, xmin::text, updated_at FROM core.teams WHERE provider_team_id IN (880001, 880002)"
    before = db.execute(sql + " ORDER BY 1").fetchall()
    assert repo.ensure_teams([ref], {880001: "Alpha FC", 880002: "Beta FC"}) == teams
    assert _free(other, "SELECT id FROM core.teams WHERE provider_team_id IN (880001, 880002)"), \
        "the in-play capture must not wait for a sync that only read these teams"
    assert db.execute(sql + " ORDER BY 1").fetchall() == before


def test_a_renamed_team_is_written_and_a_missing_name_is_not_replaced_by_a_placeholder(
        db: psycopg.Connection, teams: dict[int, int]) -> None:
    repo = FixtureRepository(db)
    ref = FixtureRef(990001, 39, 2025, KICKOFF, 880001, 880002, "NS")
    assert repo.ensure_teams([ref], {880001: "Alpha United"}) == teams  # the payload names only the home side
    names: dict[int, str] = dict(
        db.execute("SELECT provider_team_id, name FROM core.teams WHERE provider_team_id IN (880001, 880002)")
        .fetchall())
    assert names == {880001: "Alpha United", 880002: "Beta FC"}, "until 9 Oct 2026 Beta FC became 'team 880002'"


def test_a_team_seen_for_the_first_time_is_created(db: psycopg.Connection, teams: dict[int, int]) -> None:
    repo = FixtureRepository(db)
    ref = FixtureRef(990002, 39, 2025, KICKOFF, 880001, 777001, "NS")
    ids = repo.ensure_teams([ref], {777001: "Newcomers FC"})
    assert ids[880001] == teams[880001] and ids[777001] > 0
    row = db.execute("SELECT name FROM core.teams WHERE id = %s", (ids[777001],)).fetchone()
    assert row == ("Newcomers FC",)
    unnamed = repo.ensure_teams([FixtureRef(990003, 39, 2025, KICKOFF, 777002, 880002, "NS")], {})
    row = db.execute("SELECT name FROM core.teams WHERE id = %s", (unnamed[777002],)).fetchone()
    assert row == ("team 777002",), "a team the payload does not name still gets its placeholder"
