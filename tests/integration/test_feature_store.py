"""The database refuses leakage the engine should never produce anyway.

Belt and braces: the engine's event loop is the first defence; these
constraints are the second. A feature set computed as of a moment after
kick-off, or from an input at or after its own cut-off, cannot be stored.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.features.data import load_matches
from fbi.features.engine import FEATURE_NAMES, FEATURE_VERSION, walk_forward
from fbi.features.store import (
    ensure_registry,
    load_feature_matrix,
    write_elo_history,
    write_feature_sets,
)
from fbi.ingestion.ledger import RunCounters, RunLedger
from tests.integration.conftest import Seed
from tests.integration.helpers import must_be_rejected, scalar

KO = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)  # the seed fixture's kick-off


@pytest.fixture()
def store(db: psycopg.Connection, seed: Seed) -> Iterator[psycopg.Connection]:
    ensure_registry(db)
    db.commit()
    yield db
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM features.feature_sets")
        cur.execute("DELETE FROM features.elo_ratings")
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 55000 AND 55999")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'feature_build'")
    db.commit()


def insert_set(cur: psycopg.Cursor, fixture_id: int, cutoff: datetime, newest: datetime | None) -> None:
    cur.execute(
        "INSERT INTO features.feature_sets (fixture_id, feature_version, data_cutoff, code_version, input_hash, "
        "n_inputs, newest_input_at) VALUES (%s, 'test', %s, 'x', 'h', 1, %s)",
        (fixture_id, cutoff, newest),
    )


def test_a_cutoff_after_kickoff_is_refused_by_the_database(store: psycopg.Connection, seed: Seed) -> None:
    # The seed fixture's kick-off as stored now: another module's sync may have moved it.
    kickoff = store.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (seed.fixture_id,)).fetchone()
    assert kickoff is not None
    with must_be_rejected(store, "a pre-match feature set cannot be computed after kick-off") as cur:
        insert_set(cur, seed.fixture_id, kickoff[0] + timedelta(minutes=1), None)


def test_an_input_at_the_cutoff_is_refused_by_the_database(store: psycopg.Connection, seed: Seed) -> None:
    cutoff = KO - timedelta(hours=1)
    with must_be_rejected(store, "no input may be as recent as the cut-off") as cur:
        insert_set(cur, seed.fixture_id, cutoff, cutoff)


def test_a_clean_feature_set_is_accepted(store: psycopg.Connection, seed: Seed) -> None:
    with store.cursor() as cur:
        insert_set(cur, seed.fixture_id, KO - timedelta(hours=1), KO - timedelta(days=3))
    store.rollback()


def test_feature_sets_are_append_only_and_the_newest_information_set_is_read(
    store: psycopg.Connection, seed: Seed
) -> None:
    """Backfilling more history gives the same fixture and cut-off a NEW feature
    set (more inputs, different hash). The old one stays; readers take the one
    built from the most information."""
    with store.cursor() as cur:
        for i, days in enumerate((10, 20)):
            cur.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_short, status_group) VALUES (%s,%s,%s,%s,%s,'FT','finished') RETURNING id",
                (55000 + i, seed.season_id, seed.home_team_id, seed.away_team_id, KO - timedelta(days=days)),
            )
            fid = scalar(cur)
            cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, 0)",
                        (fid, i + 1))
    store.commit()
    matches = load_matches(store)
    target = next(m for m in matches if m.fixture_id == seed.fixture_id)
    cutoff = KO - timedelta(hours=1)
    run = RunLedger(store).open("feature_build")

    only_one = [m for m in matches if m.fixture_id != seed.fixture_id][:1]
    v1, _ = walk_forward(only_one, [(target, cutoff)])
    v2, elo = walk_forward(matches, [(target, cutoff)])
    assert v1[0].input_hash != v2[0].input_hash

    assert write_feature_sets(store, v1, version=FEATURE_VERSION, code_version="t", run_id=run, lineage={}) == (1, 0)
    assert write_feature_sets(store, v1, version=FEATURE_VERSION, code_version="t", run_id=run, lineage={}) == (0, 1), (
        "the same information set is the same vector: written once")
    assert write_feature_sets(store, v2, version=FEATURE_VERSION, code_version="t", run_id=run, lineage={}) == (1, 0)
    assert write_elo_history(store, elo, version="elo-v2.0", run_id=run) == 4
    RunLedger(store).close(run, RunCounters(rows_inserted=2))
    store.commit()

    with store.cursor() as cur:
        cur.execute("SELECT count(*) FROM features.feature_sets WHERE fixture_id = %s", (seed.fixture_id,))
        assert scalar(cur) == 2, "the older, poorer vector is kept for audit"
    matrix = load_feature_matrix(store, version=FEATURE_VERSION, fixture_ids=[seed.fixture_id])
    cut, values = matrix[seed.fixture_id]
    assert cut == cutoff and set(values) == set(FEATURE_NAMES)
    assert values["home_history_n"] == 2.0, "the reader takes the vector with the most inputs"
