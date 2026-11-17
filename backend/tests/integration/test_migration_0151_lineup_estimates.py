"""Migration 0151 (IA-094, AD-D04): ``intel.lineup_estimates``, append-only, on a scratch database at the revision below it; its checks
refuse an estimate after kick-off, a confirmed absence that starts and a health detail it has no column for; going back is clean."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, TEST_DB, _dsn

pytestmark = pytest.mark.integration
SCRATCH = f"{TEST_DB}_m0151"
BELOW = "0150"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


@contextmanager
def scratch() -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), BELOW)
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


def shape(c: psycopg.Connection[Any]) -> list[Any]:
    return c.execute("SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
                     "WHERE table_schema IN ('intel', 'ai', 'core') ORDER BY 1, 2, 3").fetchall()


ROW = ("INSERT INTO intel.lineup_estimates (fixture_id, team_id, provider_player_id, evaluation, known_at, kickoff_at, position, p_start, "
       "p_play, expected_minutes, basis, sample, seal, lineup_confirmed, history_matches, start_model_samples, start_model_fitted, version, "
       "model, input_hash) VALUES (%s, %s, 99, 'E1', %s::timestamptz, '2026-11-20 20:00+00', 'M', %s, %s, 60, %s, 10, 'sin_calibrar', false, "
       "12, 600, true, 'lineup-estimate-v1', 'player-engine-v1', repeat('a', 64))")


def test_0151_adds_one_append_only_table_and_goes_back_clean() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = shape(c)
            comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                             "VALUES (39, 'L', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
            assert comp is not None
            s = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp[0],)).fetchone()
            h = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (1, 'A') RETURNING id").fetchone()
            a = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (2, 'B') RETURNING id").fetchone()
            assert s is not None and h is not None and a is not None
            fx = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                           "VALUES (77, %s, %s, %s, '2026-11-20 20:00+00') RETURNING id", (s[0], h[0], a[0])).fetchone()
            assert fx is not None
            c.commit()
        command.upgrade(_cfg(), "0151")
        with psycopg.connect(dsn) as c:
            added = sorted(set(shape(c)) - set(before))
            assert {(r[0], r[1]) for r in added} == {("intel", "lineup_estimates")}
            assert not [r for r in added if r[2] in ("reason", "injury", "medical", "diagnosis", "claim")], "no health detail has a column"
            c.execute(ROW, (fx[0], h[0], "2026-11-20 07:00+00", 0.8, 0.85, "minutos_recientes"))
            c.commit()
            for sql in ("UPDATE intel.lineup_estimates SET p_start = 1", "DELETE FROM intel.lineup_estimates"):
                with pytest.raises(psycopg.Error):
                    c.execute(sql)
                c.rollback()
            for args in ((fx[0], h[0], "2026-11-20 21:00+00", 0.8, 0.85, "minutos_recientes"),   # after kick-off
                         (fx[0], a[0], "2026-11-20 07:00+00", 0.4, 0.4, "baja_confirmada"),       # a confirmed absence that starts
                         (fx[0], a[0], "2026-11-20 07:00+00", 0.6, 0.5, "minutos_recientes"),     # plays less than he starts
                         (fx[0], a[0], "2026-11-20 07:00+00", 0.6, 0.7, "a_guess")):              # a basis that is not one
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute(ROW, args)
                c.rollback()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert shape(c) == before
