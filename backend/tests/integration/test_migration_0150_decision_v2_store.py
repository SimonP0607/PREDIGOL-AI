"""Migration 0150 (IA-093, AD-D01): decision-v2's two append-only tables, on a scratch database at the revision below it; the cycle's
``source`` accepts a table name with digits; going back leaves the schema as it was and ``intel.decisions`` untouched."""

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
SCRATCH = f"{TEST_DB}_m0150"
BELOW = "0149"


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


def source_check(c: psycopg.Connection[Any]) -> str:
    row = c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'selection_lifecycle_source_check'").fetchone()
    assert row is not None
    return str(row[0])


MOMENT = ("INSERT INTO intel.decision_v2_moments (fixture_id, trigger, evaluation, evaluation_version, known_at, kickoff_at, "
          "mirrored_version, config_key, config, candidates, decided, world_hash, writer_version) VALUES "
          "(%s, %s, %s, %s, %s::timestamptz, %s::timestamptz, %s, 'decision-v2.1|book', '{}', 3, 2, repeat('a', 64), "
          "'decision-v2-shadow-v1') RETURNING id")


def test_0150_adds_two_append_only_tables_widens_the_cycles_source_and_goes_back_clean() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = shape(c)
            check_before = source_check(c)
            season = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                               "VALUES (39, 'L', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
            assert season is not None
            s = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id",
                          (season[0],)).fetchone()
            h = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (1, 'A') RETURNING id").fetchone()
            a = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (2, 'B') RETURNING id").fetchone()
            assert s is not None and h is not None and a is not None
            fx = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                           "VALUES (77, %s, %s, %s, '2026-11-20 20:00+00') RETURNING id", (s[0], h[0], a[0])).fetchone()
            assert fx is not None
            c.commit()
        command.upgrade(_cfg(), "0150")
        with psycopg.connect(dsn) as c:
            added = sorted(set(shape(c)) - set(before))
            assert {r[1] for r in added} == {"decisions_v2", "decision_v2_moments"} and {r[0] for r in added} == {"intel"}
            assert set(before) <= set(shape(c)), "nothing else of the schema moves"
            assert "a-z0-9_" in source_check(c) and source_check(c) != check_before
            fid = int(fx[0])
            m = c.execute(MOMENT, (fid, "E1", "E1", 1, "2026-11-20 07:00+00", "2026-11-20 20:00+00", None)).fetchone()
            assert m is not None
            row = c.execute(
                "INSERT INTO intel.decisions_v2 (moment_id, chain_key, fixture_id, family, market_key, selection, line, model, known_at, "
                "kickoff_at, trigger, evaluation, evaluation_version, checkpoint, state, reason, codes, version, rules, config_key, "
                "probability_source, p_model, price_source, price_at, model_cutoff, context_status, inputs, evidence, decision, input_hash) "
                "VALUES (%s, 'decision-v2.1|book|core|x', %s, 'core', 'OU', 'Over', 2.5, 'dixon_coles', '2026-11-20 07:00+00', "
                "'2026-11-20 20:00+00', 'E1', 'E1', 1, 'T-24h', 'ABSTAIN', 'not_calibrated', '{not_calibrated}', 'decision-v2', "
                "'decision-v2.1', 'decision-v2.1|book', 'common', 0.55, 'book', '2026-11-20 06:00+00', '2026-11-20 05:00+00', 'FULL', "
                "'{}', '{}', '{}', repeat('b', 64)) RETURNING id", (m[0], fid)).fetchone()
            assert row is not None
            c.commit()
            for sql in ("UPDATE intel.decisions_v2 SET state = 'RECOMMENDED'", "DELETE FROM intel.decisions_v2",
                        "UPDATE intel.decision_v2_moments SET decided = 0", "DELETE FROM intel.decision_v2_moments"):
                with pytest.raises(psycopg.Error):
                    c.execute(sql)
                c.rollback()
            bad = [
                (MOMENT, (fid, "E1", "E1", 1, "2026-11-20 21:00+00", "2026-11-20 20:00+00", None)),       # after kick-off
                (MOMENT, (fid, "mirror", None, None, "2026-11-20 07:00+00", "2026-11-20 20:00+00", None)),  # a mirror names its layer
                (MOMENT, (fid, "E4", "E1", 1, "2026-11-20 19:45+00", "2026-11-20 20:00+00", None)),       # E4 is evaluation E4
            ]
            for sql, args in bad:
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute(sql, args)
                c.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):  # a price later than the moment
                c.execute(
                    "INSERT INTO intel.decisions_v2 (moment_id, chain_key, fixture_id, family, market_key, selection, line, model, known_at, "
                    "kickoff_at, trigger, checkpoint, state, reason, codes, version, rules, config_key, probability_source, p_model, "
                    "price_source, price_at, context_status, inputs, evidence, decision, input_hash) VALUES (%s, 'decision-v2.1|book|y', "
                    "%s, 'core', 'OU', 'Over', 2.5, 'm', '2026-11-20 07:00+00', '2026-11-20 20:00+00', 'mirror', 'T-12h', 'WATCH', 'x', "
                    "'{}', 'decision-v2', 'decision-v2.1', 'k', 'own', 0.5, 'book', '2026-11-20 08:00+00', 'FULL', '{}', '{}', '{}', "
                    "repeat('c', 64))", (m[0], fid))
            c.rollback()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert shape(c) == before
            assert source_check(c).split(" NOT VALID")[0] == check_before
