"""Migration 0181 (RP-2.1): the forecast table learns what its figure rests on, adds nothing else, rewrites no row, and comes back out."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration

SCRATCH = "fbi_test_m0181"
NEW = ("figure_label", "cal_method", "cal_intercept", "cal_w_model", "cal_w_market")
CHECKS = ("match_forecasts_figure_label_values", "match_forecasts_cal_method_values", "match_forecasts_label_is_coherent")


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _columns(c: psycopg.Connection[Any]) -> set[str]:
    return {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns "
                                    "WHERE table_schema = 'models' AND table_name = 'match_forecasts'").fetchall()}


def _checks(c: psycopg.Connection[Any]) -> dict[str, bool]:
    return {r[0]: bool(r[1]) for r in c.execute("SELECT conname, convalidated FROM pg_constraint WHERE conrelid = 'models.match_forecasts'::regclass "
                                                 "AND conname = ANY(%s)", (list(CHECKS),)).fetchall()}


def test_0181_adds_five_nullable_columns_and_three_checks_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0180")
        with psycopg.connect(dsn) as c:
            before = _columns(c)
            assert not set(NEW) & before and not _checks(c)

        command.upgrade(_cfg(), "0181")
        with psycopg.connect(dsn) as c:
            assert _columns(c) == before | set(NEW), "five columns and nothing else"
            nullable = {r[0]: r[1] for r in c.execute("SELECT column_name, is_nullable FROM information_schema.columns "
                                                       "WHERE table_schema = 'models' AND table_name = 'match_forecasts' "
                                                       "AND column_name = ANY(%s)", (list(NEW),)).fetchall()}
            assert set(nullable.values()) == {"YES"}, "a row written before has none of them"
            assert _checks(c) == dict.fromkeys(CHECKS, False), "enforced for new rows, no old row scanned"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0181",)

        command.downgrade(_cfg(), "0180")
        with psycopg.connect(dsn) as c:
            assert _columns(c) == before and not _checks(c), "it leaves as it came"

        command.upgrade(_cfg(), "0181")  # and applies again
        with psycopg.connect(dsn) as c:
            assert set(NEW) <= _columns(c)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
