"""Migration 0158 (IA-112, AD-K01): ``intel.selection_evaluations``, append-only, on a scratch database at the revision below it; its
checks refuse an evaluation decided after kick-off, a hit that is not a full result, a verdict that does not fit the result and a second
evaluation of the same selection and version; going back is clean."""

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
SCRATCH = f"{TEST_DB}_m0158"
BELOW = "0157"


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


ROW = ("INSERT INTO intel.selection_evaluations (version, layer, decision_source, decision_id, fixture_id, family, taken, market_key, "
       "selection, line, kickoff_at, decided_at, settled_at, result, p_judged, seal, p_market, odds, p_close, clv, hit, log_loss, brier, "
       "market_log_loss, market_brier, price_quality, verdict, evidence_held, evidence_contradicted, evidence_unevaluable, parity, "
       "detail, input_hash) VALUES ('eval-sel-v1', 'decision-v1', 'intel.decisions', %s, %s, 'core', false, 'OU', 'Over', 2.5, "
       "'2026-11-20 20:00+00', %s::timestamptz, '2026-11-20 23:00+00', %s, 0.55, 'calibrada', 0.5, 2.05, 0.5, 0.025, %s, %s, %s, "
       "0.693147, 0.25, 'GOOD', %s, 0, 0, 0, 'igual', '{}', repeat('a', 64))")


def test_0158_adds_one_append_only_table_and_goes_back_clean() -> None:
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
        command.upgrade(_cfg(), "0158")
        with psycopg.connect(dsn) as c:
            added = sorted(set(shape(c)) - set(before))
            assert {(r[0], r[1]) for r in added} == {("intel", "selection_evaluations")}
            c.execute(ROW, (1, fx[0], "2026-11-20 17:00+00", "win", 1, 0.597837, 0.2025, "MERECIDO"))
            c.commit()
            for sql in ("UPDATE intel.selection_evaluations SET verdict = 'ERROR'", "DELETE FROM intel.selection_evaluations"):
                with pytest.raises(psycopg.Error):
                    c.execute(sql)
                c.rollback()
            for args in ((2, fx[0], "2026-11-20 20:30+00", "win", 1, 0.597837, 0.2025, "MERECIDO"),   # decided after kick-off
                         (3, fx[0], "2026-11-20 17:00+00", "half_win", 1, 0.597837, 0.2025, "MERECIDO"),  # a hit on a half result
                         (4, fx[0], "2026-11-20 17:00+00", "void", None, None, None, "MERECIDO"),  # a void that is not NULO
                         (1, fx[0], "2026-11-20 17:00+00", "win", 1, 0.597837, 0.2025, "MERECIDO")):  # the same selection again
                with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.UniqueViolation)):
                    c.execute(ROW, args)
                c.rollback()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert shape(c) == before
