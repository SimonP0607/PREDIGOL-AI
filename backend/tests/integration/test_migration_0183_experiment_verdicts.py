"""Migration 0183 (RP-8.1): the store of verdicts appears (append-only, with its view), a hypothesis may be ARCHIVED, no row is rewritten, and it all comes back out."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration

SCRATCH = "fbi_test_m0183"
FP = "a" * 64
VERDICT = ("INSERT INTO analytics.experiment_verdicts (experiment, protocol_version, protocol_fingerprint, verdict, reason, n, mean, low, high, computed_at, "
           "recorded_by) VALUES ('EXP-E1', 'proto-exp-e1-v1', %s, 'exito', 'una razón suficientemente larga', 1200, -0.002, -0.005, 0.001, now(), 'system')")
HYPOTHESIS = ("INSERT INTO analytics.research_hypotheses (proposed_by, title, hypothesis, rationale, evidence, created_at, status, decided_at) "
              "VALUES ('owner', 'una hipótesis', 'h', 'r', '{}'::jsonb, now(), %s, "
              "CASE WHEN %s = 'PROPOSED' THEN NULL ELSE now() END)")


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _ok(c: psycopg.Connection[Any], sql: str, *params: Any) -> bool:
    try:
        with c.transaction():
            c.execute(sql, params)
            raise _UndoError
    except _UndoError:
        return True
    except (psycopg.errors.CheckViolation, psycopg.errors.UndefinedTable):
        return False


class _UndoError(Exception):
    pass


def test_0183_adds_the_store_and_the_state_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0182")
        with psycopg.connect(dsn) as c:
            assert not _ok(c, HYPOTHESIS, "ARCHIVED", "ARCHIVED"), "before: no such state"
            assert _ok(c, HYPOTHESIS, "PROPOSED", "PROPOSED")
            c.execute(HYPOTHESIS, ("DONE", "DONE"))
            c.commit()

        command.upgrade(_cfg(), "0183")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0183",)
            assert c.execute("SELECT count(*) FROM analytics.research_hypotheses").fetchone() == (1,), "no row was rewritten or added"
            assert _ok(c, HYPOTHESIS, "ARCHIVED", "ARCHIVED")
            assert not _ok(c, HYPOTHESIS, "LOST", "LOST")
            assert _ok(c, VERDICT, FP)
            assert not _ok(c, VERDICT, "not-a-fingerprint"), "the fingerprint is 64 hex"
            assert not _ok(c, VERDICT.replace("'EXP-E1'", "'E1'"), FP), "an experiment of the plan"
            assert not _ok(c, VERDICT.replace("'exito'", "'ganó'"), FP), "one of the three verdicts"
            assert not _ok(c, VERDICT.replace("'una razón suficientemente larga'", "'corta'"), FP), "with its reason"
            assert not _ok(c, VERDICT.replace("-0.005, 0.001", "0.001, -0.005"), FP), "interval in order"
            assert c.execute("SELECT count(*) FROM analytics.experiment_verdicts_latest").fetchone() == (0,)

        command.downgrade(_cfg(), "0182")
        with psycopg.connect(dsn) as c:
            assert c.execute("SELECT to_regclass('analytics.experiment_verdicts'), to_regclass('analytics.experiment_verdicts_latest')").fetchone() == (None, None)
            assert not _ok(c, HYPOTHESIS, "ARCHIVED", "ARCHIVED"), "it leaves as it came"
            assert c.execute("SELECT count(*) FROM analytics.research_hypotheses").fetchone() == (1,)

        command.upgrade(_cfg(), "0183")  # and applies again
        with psycopg.connect(dsn) as c:
            assert _ok(c, VERDICT, FP)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


def test_the_chain_has_this_migration_after_0182_and_one_head() -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_cfg())
    assert script.get_revision("0183").down_revision == "0182"
    assert len(script.get_heads()) == 1
