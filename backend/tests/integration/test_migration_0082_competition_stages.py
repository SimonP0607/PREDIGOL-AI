"""Migration 0082 (stages, ties and the stage / tie / leg of a fixture): additive, non-blocking, and reversible.

Deploying must change nothing the system does: the migration only ADDS two tables and three nullable columns, the fixtures
that exist keep every value they had (their ``updated_at`` included) and read NULL in the new columns. Run on a scratch
database at revision 0081 that already holds a fixture, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0082"
NEW_TABLES = ("core.competition_stages", "core.ties")
NEW_COLUMNS = ("stage_id", "leg", "tie_id")


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _exists(c: psycopg.Connection[Any], name: str) -> bool:
    row = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


def _shape(c: psycopg.Connection[Any]) -> dict[str, Any]:
    """What exists that the migration must not change: the columns (but the three it adds) and the fixtures themselves."""
    cols = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'analytics') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    kept = [r for r in cols if f"{r[0]}.{r[1]}" not in NEW_TABLES
            and not (r[0] == "core" and r[1] == "fixtures" and r[2] in NEW_COLUMNS)]
    fixtures = c.execute("SELECT id, provider_fixture_id, round, status_short, updated_at FROM core.fixtures "
                         "ORDER BY id").fetchall()
    return {"columns": kept, "fixtures": fixtures}


def test_0082_adds_two_tables_and_three_null_columns_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0081")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, t) for t in NEW_TABLES)
            competition = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                                    "competition_type) VALUES (1, 'Cup', 'cup', 'club', 'domestic_cup') RETURNING id"
                                    ).fetchone()
            assert competition is not None
            season = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2025) "
                               "RETURNING id", (competition[0],)).fetchone()
            home = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (1, 'A') RETURNING id").fetchone()
            away = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (2, 'B') RETURNING id").fetchone()
            assert season is not None and home is not None and away is not None
            c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                      "away_team_id, kickoff_at, round, updated_at) VALUES (1, %s, %s, %s, '2026-05-20 19:00Z', "
                      "'Final', '2026-05-01 10:00Z')", (season[0], home[0], away[0]))
            c.commit()
            before = _shape(c)

        command.upgrade(_cfg(), "0082")
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, t) for t in NEW_TABLES)
            assert _shape(c) == before, "nothing that existed was changed, the fixture's updated_at included"
            row = c.execute("SELECT stage_id, leg, tie_id FROM core.fixtures").fetchone()
            assert row == (None, None, None), "no stage is invented by the migration: building is a separate, visible step"
            for table in NEW_TABLES:
                assert c.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
            columns = {r[0]: (r[1], r[2]) for r in c.execute(
                "SELECT column_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = 'core' AND table_name = 'fixtures' AND column_name = ANY(%s)",
                (list(NEW_COLUMNS),)).fetchall()}
            assert columns == dict.fromkeys(NEW_COLUMNS, ("YES", None)), "nullable and without a default (instant on a live table)"
            unvalidated = c.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'core.fixtures'::regclass "
                                    "AND NOT convalidated").fetchall()
            assert unvalidated == [], "the foreign keys were added NOT VALID and validated in the same revision"
            indexes: dict[str, str] = dict(c.execute(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'core' "
                "AND indexname IN ('fixtures_stage_id', 'fixtures_tie_id', 'ties_pair')").fetchall())
            assert set(indexes) == {"fixtures_stage_id", "fixtures_tie_id", "ties_pair"}
            assert "WHERE (stage_id IS NOT NULL)" in indexes["fixtures_stage_id"]
            assert "WHERE (tie_id IS NOT NULL)" in indexes["fixtures_tie_id"]
            assert "UNIQUE" in indexes["ties_pair"] and "LEAST" in indexes["ties_pair"]

            # the stage / tie / leg of a fixture can be set, and the tables refuse what the readers could not mean
            stage = c.execute(
                "INSERT INTO core.competition_stages (competition_season_id, stage, ordinal, phase, base_stage, kind, role, "
                "rule, numbered, round_key, teams, fixtures, first_kickoff_at, last_kickoff_at, tie_format, ties, "
                "stages_version, ties_version, build_hash) VALUES (%s, 'Final', 1, 'Final', 'Final', 'knockout', 'final', "
                "'knockout_word', false, 'final', 2, 1, '2026-05-20 19:00Z', '2026-05-20 19:00Z', 'single', 1, "
                "'stages-1', 'ties-2', 'abc') RETURNING id", (season[0],)).fetchone()
            assert stage is not None
            tie = c.execute("INSERT INTO core.ties (stage_id, team_a_id, team_b_id, format, status, legs, played, "
                            "aggregate_a, aggregate_b, winner_team_id, decided_by, version) "
                            "VALUES (%s, %s, %s, 'single', 'decided', 1, 1, 2, 1, %s, 'normal_time', 'ties-2') RETURNING id",
                            (stage[0], home[0], away[0], home[0])).fetchone()
            assert tie is not None
            c.execute("UPDATE core.fixtures SET stage_id = %s, tie_id = %s, leg = 1", (stage[0], tie[0]))
            assert c.execute("SELECT updated_at FROM core.fixtures").fetchone() == (before["fixtures"][0][4],), (
                "writing the three columns leaves updated_at alone: it is how other jobs see a fixture change")
            c.commit()

            outsider = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (3, 'C') RETURNING id").fetchone()
            assert outsider is not None
            c.commit()
            # (statement, the constraint that must refuse it): a test that only says "something refused it" can pass for the wrong reason
            refused = {
                "a winner that is not in the pair": (
                    f"UPDATE core.ties SET winner_team_id = {outsider[0]}", "ties_winner_in_pair"),
                "a decided tie without a winner": (
                    "UPDATE core.ties SET winner_team_id = NULL, decided_by = NULL", "ties_decided_iff_winner"),
                "a winner while the tie is open": ("UPDATE core.ties SET status = 'in_progress'", "ties_decided_iff_winner"),
                "a way of deciding without a winner": (
                    "UPDATE core.ties SET status = 'unresolved', winner_team_id = NULL", "ties_decided_by_needs_winner"),
                "half an aggregate": ("UPDATE core.ties SET aggregate_b = NULL", "ties_aggregate_pair"),
                "half a shoot-out": ("UPDATE core.ties SET shootout_a = 4", "ties_shootout_pair"),
                "a tie against itself": ("UPDATE core.ties SET team_b_id = team_a_id", "ties_distinct_sides"),
                "an unknown way of deciding": ("UPDATE core.ties SET decided_by = 'coin_toss'", "ties_decided_by_check"),
                "leg zero": ("UPDATE core.fixtures SET leg = 0", "fixtures_leg_check"),
                "a stage that does not exist": ("UPDATE core.fixtures SET stage_id = 999999", "fixtures_stage_fk"),
                "a tie that does not exist": ("UPDATE core.fixtures SET tie_id = 999999", "fixtures_tie_fk"),
                "the same pair twice in a stage (either way round)": (
                    "INSERT INTO core.ties (stage_id, team_a_id, team_b_id, format, status, legs, played, version) "
                    "SELECT stage_id, team_b_id, team_a_id, 'single', 'scheduled', 1, 0, 'ties-2' FROM core.ties", "ties_pair"),
                "a stage kind nobody reads": ("UPDATE core.competition_stages SET kind = 'semi'", "competition_stages_kind_check"),
                "a stage that ends before it starts": (
                    "UPDATE core.competition_stages SET last_kickoff_at = first_kickoff_at - interval '1 day'",
                    "competition_stages_kickoffs_in_order"),
                "the same stage twice in a season": (
                    "INSERT INTO core.competition_stages (competition_season_id, stage, ordinal, phase, base_stage, kind, "
                    "role, rule, numbered, fixtures, first_kickoff_at, last_kickoff_at, stages_version, ties_version, "
                    "build_hash) SELECT competition_season_id, stage, 2, phase, base_stage, kind, role, rule, numbered, "
                    "fixtures, first_kickoff_at, last_kickoff_at, stages_version, ties_version, build_hash "
                    "FROM core.competition_stages",
                    "competition_stages_stage_key"),
            }
            for what, (sql, constraint) in refused.items():
                with pytest.raises(psycopg.errors.IntegrityError) as caught:
                    c.execute(sql)
                assert caught.value.diag.constraint_name == constraint, f"{what}: refused by {caught.value.diag.constraint_name}"
                c.rollback()

            # deleting a stage or a tie leaves the fixture, with the pointer cleared (the fixture is not ours to delete)
            c.execute("DELETE FROM core.competition_stages")
            assert c.execute("SELECT count(*) FROM core.ties").fetchone() == (0,), "the ties go with their stage"
            assert c.execute("SELECT stage_id, tie_id FROM core.fixtures").fetchone() == (None, None)
            assert c.execute("SELECT count(*) FROM core.fixtures").fetchone() == (1,)
            c.rollback()

        command.downgrade(_cfg(), "0081")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, t) for t in NEW_TABLES)
            names = {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns "
                                            "WHERE table_schema = 'core' AND table_name = 'fixtures'").fetchall()}
            assert not names & set(NEW_COLUMNS)
            assert _shape(c) == before

        command.upgrade(_cfg(), "0082")
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, t) for t in NEW_TABLES)
            assert c.execute("SELECT stage_id, leg, tie_id FROM core.fixtures").fetchone() == (None, None, None)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
