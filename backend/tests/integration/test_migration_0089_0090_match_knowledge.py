"""Migrations 0089 (what each line of the events is) and 0090 (Match Knowledge): additive, empty and reversible (plan F7).

Deploying must change nothing the system does: 0089 adds one table, 0090 one table and one view; nothing that existed is altered - least of
all ``core.fixture_events``, whose triggers (revision 0061 keeps the history of what the provider said about a finished match) must be
exactly the ones it had - no row is written, and going back leaves the database as it came. Run on a scratch database at revision 0088, the
way production does."""

from __future__ import annotations

import os
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0089_0090"
KINDS = "core.fixture_event_kinds"
KNOWLEDGE = "intel.match_knowledge"
LATEST = "intel.match_knowledge_latest"
EVENTS = "core.fixture_events"
OWN = {KINDS, KNOWLEDGE, LATEST}


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _exists(c: psycopg.Connection[Any], name: str) -> bool:
    row = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    """Every column of every table and view the migrations must leave alone (all but their own three)."""
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'market', 'models', 'intel', 'picks', 'raw', 'audit') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if f"{r[0]}.{r[1]}" not in OWN]


def _triggers(c: psycopg.Connection[Any], table: str) -> set[str]:
    return {r[0] for r in c.execute("SELECT tgname FROM pg_trigger WHERE tgrelid = %s::regclass AND NOT tgisinternal", (table,)).fetchall()}


def _indexes(c: psycopg.Connection[Any], schema: str, table: str) -> set[str]:
    return {r[0] for r in c.execute("SELECT indexname FROM pg_indexes WHERE schemaname = %s AND tablename = %s", (schema, table)).fetchall()}


def _comment(c: psycopg.Connection[Any], name: str) -> str | None:
    row = c.execute("SELECT obj_description(%s::regclass)", (name,)).fetchone()
    return None if row is None else row[0]


def test_0089_and_0090_add_three_objects_and_nothing_else_and_come_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0088")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, name) for name in OWN)
            before = _shape(c)
            events_triggers = _triggers(c, EVENTS)
            events_indexes = _indexes(c, "core", "fixture_events")
        assert events_triggers, "the provider's events keep the history of a finished match (revision 0061): this test would be blind without it"

        # ── 0089: what each line of the events is ─────────────────────────────────────────────────────────────────────────
        command.upgrade(_cfg(), "0089")
        with psycopg.connect(dsn) as c:
            assert _exists(c, KINDS) and not _exists(c, KNOWLEDGE) and not _exists(c, LATEST)
            assert _shape(c) == before, "nothing that existed was changed - core.fixture_events has not one column more"
            assert _triggers(c, EVENTS) == events_triggers, "and its triggers are the ones it had: a classification does not touch the audit of the provider"
            assert _indexes(c, "core", "fixture_events") == events_indexes
            assert c.execute(f"SELECT count(*) FROM {KINDS}").fetchone() == (0,), "the migration writes no row: it is rebuilt by the builder"
            assert _indexes(c, "core", "fixture_event_kinds") == {"fixture_event_kinds_pkey"}
            assert _triggers(c, KINDS) == set(), "a derived table: the builder rewrites the rows of a match, it is not append-only"
            kinds_fks = c.execute("SELECT count(*) FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'", (KINDS,)).fetchone()
            assert kinds_fks == (0,), "no foreign key: it would need a lock on tables that fixtures_sync keeps in a write transaction (revisions 0085, 0086)"
            assert _comment(c, KINDS)
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0089",)

        # ── 0090: Match Knowledge ─────────────────────────────────────────────────────────────────────────────────────────
        command.upgrade(_cfg(), "0090")
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, name) for name in OWN)
            assert _shape(c) == before
            assert _triggers(c, EVENTS) == events_triggers
            for name in (KNOWLEDGE, LATEST):
                assert c.execute(f"SELECT count(*) FROM {name}").fetchone() == (0,), "the migration writes no row"
            assert _indexes(c, "intel", "match_knowledge") == {"match_knowledge_pkey", "match_knowledge_chain_key", "match_knowledge_one_successor"}
            unique = c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'u'",
                               (KNOWLEDGE,)).fetchall()
            assert unique == [("UNIQUE (fixture_id, version, id)",)], "what a build can name as the one it replaced"
            successor = c.execute("SELECT indexdef FROM pg_indexes WHERE schemaname = 'intel' AND indexname = 'match_knowledge_one_successor'").fetchone()
            assert successor is not None and "UNIQUE" in successor[0] and "COALESCE(supersedes, (0)::bigint)" in successor[0], (
                "a build is replaced once: two builders that read the same newest build cannot both add the next one")
            assert _triggers(c, KNOWLEDGE) == {"match_knowledge_append_only"}, "a build is never edited or deleted afterwards"
            fks = c.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = %s::regclass AND contype = 'f'", (KNOWLEDGE,)).fetchall()
            assert fks == [("FOREIGN KEY (fixture_id, version, supersedes) REFERENCES intel.match_knowledge(fixture_id, version, id)",)], (
                "it refers to itself and to nothing else: a key to core.fixtures would wait on fixtures_sync's long transaction")
            for name in (KNOWLEDGE, LATEST):
                assert _comment(c, name), f"{name} says what it is"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0090",)

        # ── and back ──────────────────────────────────────────────────────────────────────────────────────────────────────
        command.downgrade(_cfg(), "0089")
        with psycopg.connect(dsn) as c:
            assert _exists(c, KINDS) and not _exists(c, KNOWLEDGE) and not _exists(c, LATEST)
            assert _shape(c) == before
        command.downgrade(_cfg(), "0088")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, name) for name in OWN)
            assert _shape(c) == before, "and it leaves as it came"
            assert _triggers(c, EVENTS) == events_triggers

        command.upgrade(_cfg(), "0090")  # and applies again
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, name) for name in OWN)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()
