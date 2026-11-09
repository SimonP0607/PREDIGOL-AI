"""Migration 0130 (IA-022): ``ai.chronicle_reviews`` - additive, append-only, reversible, and nothing else moves.

The upgrade adds one table with its unique index and its trigger; it has no foreign key to a table the worker writes all the time (the lesson
of 0076, 0100 and 0110). The downgrade drops it and goes up again. Its own scratch database (``<FBI_TEST_DB>_m0130``)."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.script import ScriptDirectory

from tests.integration.conftest import ADMIN_URL, TEST_DB, _dsn
from tests.integration.test_migration_0111 import _cfg

pytestmark = pytest.mark.integration

SCRATCH = f"{TEST_DB}_m0130"


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


def test_0130_adds_one_table_without_foreign_keys_and_goes_down_and_up_again() -> None:
    with scratch_at("0129") as dsn:
        with psycopg.connect(dsn) as c:
            before = schema(c)
        command.upgrade(_cfg(), "0130")
        with psycopg.connect(dsn) as c:
            after = schema(c)
            added = {t for _, t, *_ in after["columns"]} - {t for _, t, *_ in before["columns"]}
            assert added == {"chronicle_reviews"}
            assert [r for r in after["columns"] if r[1] != "chronicle_reviews"] == before["columns"], "no column of another table moved"
            assert set(before["constraints"]) <= set(after["constraints"]), "no constraint was dropped or rewritten"
            assert not [r for r in after["constraints"] if r[0] == "ai.chronicle_reviews" and "FOREIGN KEY" in r[2]]
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0130",)
            assert c.execute("SELECT count(*) FROM pg_trigger WHERE tgrelid = 'ai.chronicle_reviews'::regclass AND NOT tgisinternal").fetchone() == (1,)
        command.downgrade(_cfg(), "0129")
        with psycopg.connect(dsn) as c:
            assert schema(c) == before
            assert c.execute("SELECT to_regclass('ai.chronicle_reviews')").fetchone() == (None,)
        command.upgrade(_cfg(), "0130")
        with psycopg.connect(dsn) as c:
            assert schema(c) == after


def test_the_chain_of_the_revisions_has_this_migration_after_0129_and_one_head() -> None:
    script = ScriptDirectory.from_config(_cfg())
    revision = script.get_revision("0130")
    assert revision is not None and revision.down_revision == "0129" and re.fullmatch(r"\d{4}", revision.revision)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert "0130" in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}, heads
