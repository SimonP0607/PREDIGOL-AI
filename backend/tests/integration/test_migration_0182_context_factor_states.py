"""Migration 0182 (RP-4.5): the registry of context factors accepts the two measured states, keeps refusing a validation without a person, rewrites no row and
comes back out."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration

SCRATCH = "fbi_test_m0182"
GOOD = {"factor": "rest_congestion", "version": "v1", "experiment": "x", "result": {"a": 1}}
INSERT = ("INSERT INTO intel.context_factors (factor, version, status, decided_at, decided_by, who, reason, evidence, previous_id) "
          "VALUES ('rest_congestion', 'v1', %s, now(), %s, %s, 'a reason that is long enough', %s, NULL)")


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _accepts(c: psycopg.Connection[Any], status: str, by: str, who: str | None, evidence: dict[str, Any]) -> bool:
    try:
        with c.transaction():
            c.execute(INSERT, (status, by, who, Jsonb(evidence)))
            raise _UndoError
    except _UndoError:
        return True
    except psycopg.errors.CheckViolation:
        return False


class _UndoError(Exception):
    pass


def test_0182_widens_the_states_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0181")
        with psycopg.connect(dsn) as c:
            assert not _accepts(c, "TESTED_NO_EFFECT", "system", None, GOOD), "before: only two states"
            assert _accepts(c, "VALIDATED", "owner", "Simon", GOOD)
            c.execute("INSERT INTO intel.context_factors (factor, version, status, decided_by, reason) "
                      "VALUES ('h2h_weighted', 'v1', 'DESCRIPTIVE', 'system', 'born descriptive, as always')")
            c.commit()

        command.upgrade(_cfg(), "0182")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0182",)
            assert c.execute("SELECT count(*) FROM intel.context_factors").fetchone() == (1,), "no row was rewritten or added"
            for status in ("TESTED_NO_EFFECT", "TESTED_EFFECT"):
                assert _accepts(c, status, "system", None, GOOD), f"{status} may be written by the system"
                assert _accepts(c, status, "owner", "Simon", GOOD)
                assert not _accepts(c, status, "system", None, {k: v for k, v in GOOD.items() if k != "experiment"}), "it cites its experiment"
                assert not _accepts(c, status, "system", None, GOOD | {"result": {}}), "and a result that says something"
                assert not _accepts(c, status, "system", None, GOOD | {"version": "v2"}), "about this version"
            assert not _accepts(c, "VALIDATED", "system", None, GOOD), "a validation still needs a person"
            assert _accepts(c, "VALIDATED", "owner", "Simon", GOOD)
            assert not _accepts(c, "PROVEN", "owner", "Simon", GOOD)

        command.downgrade(_cfg(), "0181")
        with psycopg.connect(dsn) as c:
            assert not _accepts(c, "TESTED_NO_EFFECT", "system", None, GOOD), "it leaves as it came"
            assert c.execute("SELECT count(*) FROM intel.context_factors").fetchone() == (1,)

        command.upgrade(_cfg(), "0182")  # and applies again
        with psycopg.connect(dsn) as c:
            assert _accepts(c, "TESTED_EFFECT", "system", None, GOOD)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
