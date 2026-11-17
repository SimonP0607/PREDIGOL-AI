"""Migration 0139 (IA-062 and IA-063): five new append-only tables in ``ai`` - and nothing else. ``ai.sources`` stays as it was, with its
rows; going back drops the five. Run on a scratch database at the revision below it, the way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0139"
BELOW = "0138"
NEW = {"source_registry_versions", "source_registry", "domain_rules", "source_signoffs", "source_policy_log"}


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                     "WHERE table_schema IN ('ai', 'auth', 'core', 'market', 'models', 'intel', 'picks', 'raw', 'audit', 'customer') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if not (r[0] == "ai" and r[1] in NEW)]


def test_0139_adds_the_registry_tables_keeps_ai_sources_and_goes_back_clean(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
            c.execute("INSERT INTO ai.sources (domain, tier, added_by, added_at) VALUES ('marca.com', 'media', 'seed', now())")
        command.upgrade(_cfg(), "0139")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less anywhere else"
            tables = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'ai'").fetchall()}
            assert tables >= NEW
            assert c.execute("SELECT domain, tier FROM ai.sources").fetchall() == [("marca.com", "media")], "ai.sources as it was"
            triggers = {r[0] for r in c.execute("SELECT event_object_table FROM information_schema.triggers WHERE trigger_schema = 'ai' "
                                                "AND trigger_name LIKE '%append_only'").fetchall()}
            assert triggers >= NEW, "all five append-only"
            c.execute("INSERT INTO ai.source_registry_versions (version, kind, file_name, file_sha256, rows, loaded_at, loaded_by) "
                      "VALUES ('dir-test-1', 'directory', 'x.json', repeat('a', 64), 0, now(), 'loader')")
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO ai.domain_rules (version, domain, domain_class, action) VALUES ('dir-test-1', 'tips.example.com', "
                          "'apuestas_o_pronosticos', 'none')")  # a betting domain is a block, never «none»
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before
            left = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'ai'").fetchall()}
            assert not (left & NEW)
            assert c.execute("SELECT domain FROM ai.sources").fetchall() == [("marca.com",)]
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
