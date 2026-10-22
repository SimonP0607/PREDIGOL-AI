"""Migration 0079 (``analytics.promoted_forecast_spec``) over a database that already holds backtest sessions.

Deploying must not change what production forecasts with. Until this revision the forecast read "the latest completed
backtest session"; the migration seeds the promotion history with exactly that session, extracted the same way, so the
spec in force the moment after the deploy is the spec in use the moment before. Run on a scratch database at revision
0078 with sessions in place, the way production is: a research-V2 session is the latest completed one, a failed and a
running session are newer still and must be ignored."""

from __future__ import annotations

import json
import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from fbi.predictions import spec as fs
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn
from tests.unit.test_forecast_spec import old_logic

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0079"

OLD_RULE = ("SELECT id, name, competition_ids, config, selection FROM analytics.backtest_sessions "
            "WHERE status = 'completed' ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 1")
"""The query ``current_spec`` ran before this revision, verbatim."""


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _session(c: psycopg.Connection, *, name: str, status: str, finished: str | None, config: dict[str, Any],
             selection: dict[str, Any], competitions: list[int]) -> int:
    row = c.execute(
        "INSERT INTO analytics.backtest_sessions (name, protocol, competition_ids, validation_season, test_season, "
        "test_from, test_to, config, selection, primary_baseline, n_targets, dataset_hash, code_version, status, "
        "finished_at) VALUES (%s,'walk_forward',%s,2023,2024,'2024-08-01','2025-05-31',%s,%s,'pinnacle/closing/shin',"
        "100,'h','c',%s,%s) RETURNING id",
        (name, competitions, json.dumps(config), json.dumps(selection), status, finished)).fetchone()
    assert row is not None
    return int(row[0])


def chosen(xi: float, penalty: float) -> dict[str, Any]:
    return {"chosen": {"xi": xi, "penalty": penalty}, "scores": [{"xi": 0.0, "penalty": 0.5, "ll": 1.0}]}


def test_0079_seeds_the_spec_production_already_uses_and_changes_nothing_else(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0078")
        with psycopg.connect(dsn) as c:
            official = _session(c, name="leagues-2025-wf", status="completed", finished="2026-09-20 08:00Z",
                                config={"history_days": 730, "config_hash": "a"}, competitions=[1, 2],
                                selection={"poisson": chosen(0.002, 1.0), "dixon_coles": chosen(0.0015, 2.0),
                                           "elo_ologit": {"chosen": {"k": 20}}})
            research = _session(c, name="research-v2-2024-20261012T080000Z", status="completed",
                                finished="2026-10-12 08:00Z", config={"config_hash": "b"},
                                competitions=[1, 2, 3],
                                selection={"poisson": chosen(0.003, 1.5), "dixon_coles": chosen(0.001, 3.0),
                                           "hgb": {"chosen": {"depth": 3}}})
            _session(c, name="research-v2-2024-20261019T080000Z", status="failed", finished="2026-10-19 09:00Z",
                     config={"history_days": 365}, competitions=[9],
                     selection={"poisson": chosen(0.9, 9.0), "dixon_coles": chosen(0.9, 9.0)})
            _session(c, name="research-v2-2024-20261020T080000Z", status="running", finished=None,
                     config={"history_days": 90}, competitions=[8],
                     selection={"poisson": chosen(0.8, 8.0), "dixon_coles": chosen(0.8, 8.0)})
            c.commit()
            in_use = c.execute(OLD_RULE).fetchone()
            assert in_use is not None and in_use[0] == research, "the research session is what production reads today"
            expected = old_logic(in_use[2], in_use[3], in_use[4], int(in_use[0]))
            sessions_before = c.execute("SELECT * FROM analytics.backtest_sessions ORDER BY id").fetchall()

        command.upgrade(_cfg(), "0079")
        with psycopg.connect(dsn) as c:
            rows = c.execute("SELECT session_id, promoted_by, reason, spec, previous_id, evidence "
                             "FROM analytics.promoted_forecast_spec").fetchall()
            assert len(rows) == 1
            session_id, by, reason, doc, previous_id, evidence = rows[0]
            assert (session_id, by, previous_id) == (research, "system", None)
            assert "already reading" in reason and evidence["seed"] is True
            assert evidence["session"] == "research-v2-2024-20261012T080000Z"
            assert doc == fs.snapshot([1, 2, 3], {"config_hash": "b"}, {
                "poisson": chosen(0.003, 1.5), "dixon_coles": chosen(0.001, 3.0)}), (
                "the SQL seed and the Python extraction agree value for value (the default window included)")
            assert doc["history_days"] == 730 and set(doc["goal"]) == {"poisson", "dixon_coles"}
            assert fs.current_spec(c) == expected, "after the deploy, the same spec as before it"
            assert c.execute("SELECT * FROM analytics.backtest_sessions ORDER BY id").fetchall() == sessions_before
            assert official != research

            # append-only, and a promoted session cannot be deleted from under its promotion
            for sql in ("UPDATE analytics.promoted_forecast_spec SET reason = 'edited after the fact, quietly'",
                        "DELETE FROM analytics.promoted_forecast_spec"):
                with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
                    c.execute(sql)
                c.rollback()
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                c.execute("DELETE FROM analytics.backtest_sessions WHERE id = %s", (research,))
            c.rollback()
            c.execute("DELETE FROM analytics.backtest_sessions WHERE id = %s", (official,))  # never promoted: free
            c.rollback()

            comment = c.execute("SELECT col_description('ai.pick_postmortems'::regclass, attnum) FROM pg_attribute "
                                "WHERE attrelid = 'ai.pick_postmortems'::regclass AND attname = 'clv'").fetchone()
            assert comment is not None and "PRICE MOVE" in comment[0] and "stored_clv" in comment[0]

        command.downgrade(_cfg(), "0078")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT to_regclass('analytics.promoted_forecast_spec')").fetchone() == (None,)
            assert c.execute("SELECT to_regprocedure('analytics.refuse_change()')").fetchone() == (None,)
            comment = c.execute("SELECT col_description('ai.pick_postmortems'::regclass, attnum) FROM pg_attribute "
                                "WHERE attrelid = 'ai.pick_postmortems'::regclass AND attname = 'clv'").fetchone()
            assert comment == (None,)
            assert c.execute("SELECT * FROM analytics.backtest_sessions ORDER BY id").fetchall() == sessions_before
            c.execute("DELETE FROM analytics.backtest_sessions")  # a database with no completed session at all
            c.commit()

        command.upgrade(_cfg(), "0079")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT count(*) FROM analytics.promoted_forecast_spec").fetchone() == (0,), (
                "no session, no seed")
            assert fs.current_spec(c) is None, "and the forecast says it has no spec instead of guessing one"
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
