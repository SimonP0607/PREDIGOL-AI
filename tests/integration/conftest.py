"""Integration-test fixtures.

Every test in this package runs against a REAL PostgreSQL 16 database that is
built exclusively by running the Alembic migrations. The schema is never
created by hand, so a migration that does not apply cleanly fails the suite.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.helpers import scalar

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ADMIN_URL = os.environ.get(
    "FBI_TEST_ADMIN_URL",
    "postgresql://postgres:fbi_local_dev@127.0.0.1:5433/postgres",
)
TEST_DB = os.environ.get("FBI_TEST_DB", "fbi_test")


def _dsn(database: str) -> str:
    head, _, _ = ADMIN_URL.rpartition("/")
    return f"{head}/{database}"


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """Drop, recreate and migrate the test database. Yields its DSN."""
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (TEST_DB,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
        conn.execute(f'CREATE DATABASE "{TEST_DB}"')

    dsn = _dsn(TEST_DB)
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    command.upgrade(cfg, "head")
    yield dsn


@dataclass(frozen=True)
class Seed:
    """Ids of the minimal reference rows, resolved rather than hard-coded."""

    competition_id: int
    season_id: int
    home_team_id: int
    away_team_id: int
    fixture_id: int
    bookmaker_id: int
    run_id: int
    payload_hash: str
    model_version_id: int


@pytest.fixture(scope="session")
def seed(migrated_database: str) -> Seed:
    """Insert the minimal graph every invariant test needs. Committed once."""
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO core.competitions (provider_league_id,name,type,entity_scope,competition_type) "
            "VALUES (39,'Premier League','league','club','domestic_league') RETURNING id"
        )
        competition_id = scalar(cur)
        cur.execute(
            "INSERT INTO core.competition_seasons (competition_id,season) VALUES (%s,2025) RETURNING id",
            (competition_id,),
        )
        season_id = scalar(cur)
        cur.execute(
            "INSERT INTO core.teams (provider_team_id,name) VALUES (33,'Manchester United') RETURNING id"
        )
        home_team_id = scalar(cur)
        cur.execute("INSERT INTO core.teams (provider_team_id,name) VALUES (40,'Liverpool') RETURNING id")
        away_team_id = scalar(cur)
        cur.execute(
            "INSERT INTO core.fixtures "
            "(provider_fixture_id,competition_season_id,home_team_id,away_team_id,kickoff_at) "
            "VALUES (1001,%s,%s,%s,'2026-09-15 19:00Z') RETURNING id",
            (season_id, home_team_id, away_team_id),
        )
        fixture_id = scalar(cur)
        cur.execute(
            "INSERT INTO market.bookmakers (provider_bookmaker_id,name) VALUES (8,'Bet365') RETURNING id"
        )
        bookmaker_id = scalar(cur)
        cur.execute(
            # Seeded by migration 0025; kept here so the fixture is explicit
            # about what it depends on and still works if that ever changes.
            "INSERT INTO market.markets (key,name,n_outcomes,has_line,is_exclusive) VALUES "
            "('1X2','Match Winner',3,false,true),('DC','Double Chance',3,false,false) "
            "ON CONFLICT (key) DO NOTHING"
        )
        cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) VALUES ('test', 'test_seed', 'completed', now()) RETURNING id")
        run_id = scalar(cur)
        cur.execute(
            "INSERT INTO raw.ingestion_payloads (hash,run_id,endpoint,fetched_at,http_status,file_path,bytes) "
            "VALUES ('h1',%s,'/odds',now(),200,'x',1) RETURNING hash",
            (run_id,),
        )
        payload_hash = scalar(cur)
        cur.execute(
            "INSERT INTO models.model_registry (name,family,description) "
            "VALUES ('dixon_coles','goals','test') RETURNING id"
        )
        model_id = scalar(cur)
        cur.execute(
            "INSERT INTO models.model_versions (model_id,version,train_from,train_to,n_train,code_version) "
            "VALUES (%s,'v1','2020-01-01','2024-06-30',5000,'abc123') RETURNING id",
            (model_id,),
        )
        model_version_id = scalar(cur)

    return Seed(
        competition_id=competition_id,
        season_id=season_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        fixture_id=fixture_id,
        bookmaker_id=bookmaker_id,
        run_id=run_id,
        payload_hash=payload_hash,
        model_version_id=model_version_id,
    )


@pytest.fixture()
def db(migrated_database: str, seed: Seed) -> Iterator[psycopg.Connection]:
    """A connection whose transaction is rolled back after every test.

    Tests are therefore order independent - the flaw of the original
    999_constraint_tests.sql script, where a failed negative case still
    advanced the serial sequences and broke later hard-coded ids.
    """
    conn = psycopg.connect(migrated_database)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
