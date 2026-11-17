"""Migration 0144 (AD-H03/H04, IA-075/IA-076): new tables and views only - no column of any existing table changes - and going
back drops exactly what was added. Run on a scratch database at revision 0141."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0144"
ADDED = {"coach_career_corrections", "coach_careers_audited", "venue_geo_loads", "venue_geo", "fixture_venue_links",
         "venue_review_queue", "venue_review_decisions", "venue_review_open", "venue_geo_live", "fixture_venue_resolved"}


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if not (r[0] == "core" and r[1] in ADDED)]


def _core_relations(c: psycopg.Connection[Any]) -> set[str]:
    return {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'core'")}


def test_0144_adds_only_new_relations_and_goes_back_clean(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0143")
        with psycopg.connect(dsn, autocommit=True) as c:
            before, rel_before = _shape(c), _core_relations(c)
        command.upgrade(_cfg(), "0144")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before, "not a column more or less in any existing table"
            assert _core_relations(c) - rel_before == ADDED
            assert c.execute("SELECT count(*) FROM pg_trigger WHERE tgname LIKE '%_append_only' AND tgrelid::regclass::text "
                             "LIKE 'core.%%' AND tgfoid = 'core.coaches_venues_guard'::regproc").fetchone() == (5,)
        command.downgrade(_cfg(), "0143")
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before and _core_relations(c) == rel_before
            assert c.execute("SELECT to_regproc('core.coaches_venues_guard')").fetchone() == (None,)
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
