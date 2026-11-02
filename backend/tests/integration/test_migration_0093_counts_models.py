"""Migration 0093 (the registry accepts the family of counts, plan F10): one constraint, no row, and a downgrade that takes only what the
new family holds.

Deploying must change nothing the system does: 0093 widens one CHECK of ``models.model_registry``; no table is added, no column changes, no
row is written, and the models that run today keep their family and their versions. Going back removes the models of counts with their
versions and forecasts - and nothing of any other model. Run on a scratch database at revision 0092, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import errors

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0093"
REGISTRY = "models.model_registry"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    """Every column of every table and view of the schemas the migrations touch: 0093 must not change one."""
    return c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'market', 'models', 'intel', 'picks', 'raw', 'audit') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()


def _register(c: psycopg.Connection[Any], name: str, family: str) -> int:
    row = c.execute("INSERT INTO models.model_registry (name, family, description) VALUES (%s, %s, 'test') RETURNING id", (name, family)).fetchone()
    assert row is not None
    return int(row[0])


def _version(c: psycopg.Connection[Any], model_id: int, version: str) -> int:
    row = c.execute("INSERT INTO models.model_versions (model_id, version, train_from, train_to, n_train, code_version) "
                    "VALUES (%s, %s, '2020-01-01', '2026-09-30', 1000, 'test') RETURNING id", (model_id, version)).fetchone()
    assert row is not None
    return int(row[0])


def _forecast(c: psycopg.Connection[Any], fixture_id: int, version_id: int, model: str) -> None:
    for selection, p in (("Over", 0.55), ("Under", 0.45)):
        c.execute("INSERT INTO models.match_forecasts (version, known_at, fixture_id, family, market_key, selection, line, model_name, "
                  "model_version_id, data_cutoff_ts, p_model, p, calibration, basis, input_hash, code_version) VALUES "
                  "(%s, '2026-10-01T10:00Z', %s, 'TOTAL_GOALS', 'OU', %s, 2.5, %s, %s, '2026-10-01T09:00Z', %s, %s, "
                  "'UNCALIBRATED', 'no_champion', 'h', 'test')", (model, fixture_id, selection, model, version_id, p, p))


def _fixture(c: psycopg.Connection[Any]) -> int:
    def one(sql: str, *args: Any) -> int:
        row = c.execute(sql, args).fetchone()
        assert row is not None
        return int(row[0])

    comp = one("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
               "VALUES (39, 'Premier League', 'league', 'club', 'domestic_league') RETURNING id")
    season = one("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2025) RETURNING id", comp)
    home = one("INSERT INTO core.teams (provider_team_id, name) VALUES (33, 'Manchester United') RETURNING id")
    away = one("INSERT INTO core.teams (provider_team_id, name) VALUES (40, 'Liverpool') RETURNING id")
    return one("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
               "VALUES (1001, %s, %s, %s, '2026-10-02 19:00Z') RETURNING id", season, home, away)


def test_0093_widens_one_constraint_and_the_downgrade_takes_only_the_counts_models(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0092")
        with psycopg.connect(dsn) as c:
            before = _shape(c)
            registry_before = c.execute(f"SELECT name, family FROM {REGISTRY} ORDER BY name").fetchall()
            with pytest.raises(errors.CheckViolation):
                _register(c, "family-goals-halves", "counts")
            c.rollback()

        command.upgrade(_cfg(), "0093")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before, "not a column more or less, in any table"
            assert c.execute(f"SELECT name, family FROM {REGISTRY} ORDER BY name").fetchall() == registry_before, "no row written"
            row = c.execute("SELECT version_num FROM alembic_version").fetchone()
            assert row == ("0093",)
            comment = c.execute("SELECT col_description(%s::regclass, attnum) FROM pg_attribute WHERE attrelid = %s::regclass "
                                "AND attname = 'family'", (REGISTRY, REGISTRY)).fetchone()
            assert comment is not None and comment[0] and "counts" in comment[0], "the column says what the family is"
            with pytest.raises(errors.CheckViolation):
                _register(c, "not-a-family", "nonsense")  # the constraint is widened by one word, not removed
            c.rollback()

            # a model of counts, a model of goals, a version and a forecast of each
            fid = _fixture(c)
            counts = _register(c, "family-goals-halves", "counts")
            goals = _register(c, "poisson-test", "goals")
            counts_version = _version(c, counts, "1.0.0/family@fc1234567890")
            goals_version = _version(c, goals, "forecast-test")
            _forecast(c, fid, counts_version, "family-goals-halves")
            _forecast(c, fid, goals_version, "poisson-test")
            c.commit()

        command.downgrade(_cfg(), "0092")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before
            assert c.execute(f"SELECT count(*) FROM {REGISTRY} WHERE family = 'counts'").fetchone() == (0,), "the models of counts are gone"
            assert c.execute("SELECT count(*) FROM models.model_versions WHERE id = %s", (counts_version,)).fetchone() == (0,)
            assert c.execute("SELECT count(*) FROM models.match_forecasts WHERE model_version_id = %s", (counts_version,)).fetchone() == (0,)
            assert c.execute("SELECT count(*) FROM models.model_versions WHERE id = %s", (goals_version,)).fetchone() == (1,), \
                "and nothing of any other model"
            assert c.execute("SELECT count(*) FROM models.match_forecasts WHERE model_version_id = %s", (goals_version,)).fetchone() == (2,)
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0092",)
            with pytest.raises(errors.CheckViolation):
                _register(c, "family-goals-halves", "counts")  # the old constraint is back
            c.rollback()
            old_comment = c.execute("SELECT col_description(%s::regclass, attnum) FROM pg_attribute WHERE attrelid = %s::regclass "
                                    "AND attname = 'family'", (REGISTRY, REGISTRY)).fetchone()
            assert old_comment == (None,), "and the column has the comment it had: none"

        command.upgrade(_cfg(), "0093")  # and applies again
        with psycopg.connect(dsn) as c:
            _register(c, "family-goals-halves", "counts")
            c.rollback()
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
