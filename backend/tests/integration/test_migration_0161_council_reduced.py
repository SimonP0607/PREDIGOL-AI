"""Migration 0161 (IA-124, AD-D10): ``ai.council_reduced``, append-only, on a scratch database at the revision below it; it adds one table and
nothing else, and going back is clean (the CHECKs themselves are held by ``test_council_reduced_shadow``)."""

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
SCRATCH = f"{TEST_DB}_m0161"
BELOW = "0160"


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


def test_0161_adds_one_append_only_table_and_goes_back_clean() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = shape(c)
        command.upgrade(_cfg(), "0161")
        with psycopg.connect(dsn) as c:
            after = shape(c)
            added = sorted({(s, t) for s, t, _, _ in after} - {(s, t) for s, t, _, _ in before})
            assert added == [("ai", "council_reduced")]
            assert [r for r in after if (r[0], r[1]) != ("ai", "council_reduced")] == before, "no other table moves"
            trigger = c.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = 'ai.council_reduced'::regclass AND NOT tgisinternal").fetchall()
            assert trigger == [("council_reduced_append_only",)]
            checks = {r[0] for r in c.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'ai.council_reduced'::regclass").fetchall()}
            assert {"council_reduced_only_lowers", "council_reduced_judge", "council_reduced_wanted", "council_reduced_material",
                    "council_reduced_before_kickoff", "council_reduced_once"} <= checks
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert shape(c) == before
        command.upgrade(_cfg(), "0161")
