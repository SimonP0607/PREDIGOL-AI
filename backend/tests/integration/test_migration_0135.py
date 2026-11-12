"""Migration 0135 (IA-047): the replay bank's four tables - additive, append-only, reversible, and nothing else moves.

The upgrade adds ``ai.replay_bank_items``, ``ai.replay_runs``, ``ai.replay_results`` and ``ai.replay_assessments`` with their
indexes and triggers; the only foreign key is between two of them (a result names its bank item), none points at a table the worker
writes all the time (the lesson of 0076, 0100 and 0110). The downgrade drops them and goes up again. Its own scratch database
(``<FBI_TEST_DB>_m0135``)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from alembic import command

from tests.integration.conftest import ADMIN_URL, TEST_DB, _dsn
from tests.integration.test_migration_0111 import _cfg

pytestmark = pytest.mark.integration

SCRATCH = f"{TEST_DB}_m0135"
TABLES = {"replay_bank_items", "replay_runs", "replay_results", "replay_assessments"}


def _drop(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


@contextmanager
def scratch_at(revision: str) -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop(SCRATCH)
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), revision)
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop(SCRATCH)


def schema(c: psycopg.Connection[Any]) -> dict[str, list[Any]]:
    columns = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                        "FROM information_schema.columns WHERE table_schema = 'ai' ORDER BY 1, 2, ordinal_position").fetchall()
    constraints = c.execute("SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE connamespace = 'ai'::regnamespace ORDER BY 1, 2").fetchall()
    return {"columns": columns, "constraints": constraints}


def test_0135_adds_four_append_only_tables_and_goes_down_and_up_again() -> None:
    with scratch_at("0134") as dsn:
        with psycopg.connect(dsn) as c:
            before = schema(c)
        command.upgrade(_cfg(), "0135")
        with psycopg.connect(dsn) as c:
            after = schema(c)
            added = {t for _, t, *_ in after["columns"]} - {t for _, t, *_ in before["columns"]}
            assert added == TABLES
            assert [r for r in after["columns"] if r[1] not in TABLES] == before["columns"], "no column of another table moved"
            assert set(before["constraints"]) <= set(after["constraints"]), "no constraint was dropped or rewritten"
            foreign = [(t, d) for t, _, d in after["constraints"] if "FOREIGN KEY" in d and t.removeprefix("ai.") in TABLES]
            assert foreign == [("ai.replay_results", "FOREIGN KEY (bank_item_id) REFERENCES ai.replay_bank_items(id)")]
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0135",)
            for table in TABLES:
                assert c.execute(f"SELECT count(*) FROM pg_trigger WHERE tgrelid = 'ai.{table}'::regclass AND NOT tgisinternal").fetchone() == (1,)
        command.downgrade(_cfg(), "0134")
        with psycopg.connect(dsn) as c:
            assert schema(c) == before
            assert all(c.execute(f"SELECT to_regclass('ai.{t}')").fetchone() == (None,) for t in TABLES)
        command.upgrade(_cfg(), "0135")
        with psycopg.connect(dsn) as c:
            assert schema(c) == after
