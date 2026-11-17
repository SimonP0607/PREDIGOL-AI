"""Migration 0157 (IA-109 / IA-110): three append-only tables, on a scratch database at the revision below it; their rules hold in the
database (a parlay of four legs, a first settlement that supersedes, a firm field on a first settlement are refused); going back drops them
and leaves the rest as it was."""

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
SCRATCH = f"{TEST_DB}_m0157"
BELOW = "0156"


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
                     "WHERE table_schema IN ('intel', 'picks', 'core') ORDER BY 1, 2, 3").fetchall()


def test_0157_up_its_rules_and_back() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = shape(c)
        command.upgrade(_cfg(), "0157")
        with psycopg.connect(dsn, autocommit=True) as c:
            comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                             "VALUES (39, 'L', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
            assert comp is not None
            season = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id",
                               (comp[0],)).fetchone()
            h = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (1, 'A') RETURNING id").fetchone()
            a = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (2, 'B') RETURNING id").fetchone()
            assert season is not None and h is not None and a is not None
            fx = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                           "VALUES (1, %s, %s, %s, now()) RETURNING id", (season[0], h[0], a[0])).fetchone()
            assert fx is not None
            key = f"w-test|{fx[0]}|OU|Over|2.50"
            ok = c.execute("INSERT INTO intel.selection_settlements (chain_key, writer, fixture_id, market_key, selection, line, kind, result, "
                           "rule_version, known_at, tracker_version) VALUES (%s, 'w-test', %s, 'OU', 'Over', 2.5, 'primera', 'win', 'settle-v4', "
                           "now(), 'selection-settle-v1') RETURNING id", (key, fx[0])).fetchone()
            assert ok is not None
            for bad in (
                ("primera", ok[0], None), ("correccion", None, None), ("primera", None, 0.5),
            ):
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute("INSERT INTO intel.selection_settlements (chain_key, writer, fixture_id, market_key, selection, line, kind, "
                              "supersedes_id, result, close_p_fair, rule_version, known_at, tracker_version) VALUES (%s, 'w-test', %s, 'OU', "
                              "'Over', 2.5, %s, %s, 'win', %s, 'settle-v4', now(), 'selection-settle-v1')", (key, fx[0], *bad))
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute("INSERT INTO intel.selection_settlements (chain_key, writer, fixture_id, market_key, selection, line, kind, result, "
                          "rule_version, known_at, tracker_version) VALUES (%s, 'w-test', %s, 'OU', 'Over', 2.5, 'primera', 'loss', "
                          "'settle-v4', now(), 'selection-settle-v1')", (key, fx[0]))
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO intel.selection_settlements (chain_key, writer, fixture_id, market_key, selection, line, kind, result, "
                          "rule_version, known_at, tracker_version) VALUES ('w-test|x', 'w-test', %s, 'OU', 'Over', 2.5, 'primera', 'win', "
                          "'settle-v4', now(), 'selection-settle-v1')", (fx[0],))
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("UPDATE intel.selection_settlements SET result = 'loss' WHERE id = %s", (ok[0],))
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("DELETE FROM intel.selection_settlements WHERE id = %s", (ok[0],))
            for legs, cap in ((4, 3), (3, 4), (1, 3)):
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute("INSERT INTO intel.parlays_v6 (writer, rule_version, kind, day, outcome, max_legs, n_legs, n_candidates, "
                              "window_from, window_to, combined_odds, p_joint, p_joint_low, known_at) VALUES ('w-test', 'parlay-v6', 'daily', "
                              "'2026-11-20', 'built', %s, %s, 5, now(), now() + interval '1 day', 5.0, 0.2, 0.18, now())", (cap, legs))
            c.execute("INSERT INTO intel.parlays_v6 (writer, rule_version, kind, day, outcome, none_reason, max_legs, n_legs, n_candidates, "
                      "window_from, window_to, known_at) VALUES ('w-test', 'parlay-v6', 'daily', '2026-11-20', 'none', 'un_solo_candidato', "
                      "3, 0, 1, now(), now() + interval '1 day', now())")
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute("INSERT INTO intel.parlays_v6 (writer, rule_version, kind, day, outcome, none_reason, max_legs, n_legs, "
                          "n_candidates, window_from, window_to, known_at) VALUES ('w-test', 'parlay-v6', 'daily', '2026-11-20', 'none', "
                          "'sin_candidatos', 3, 0, 0, now(), now() + interval '1 day', now())")
            assert c.execute("SELECT count(*) FROM picks.parlays").fetchone() == (0,)
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert shape(c) == before
