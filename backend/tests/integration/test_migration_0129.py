"""Migration 0129 (plan Cuotas, BE-011): ``market.book_asks``, ``raw.provider_reported_quota`` and ``market.book_current.books`` -
additive, reversible, and nothing else moves.

The upgrade adds two tables and one nullable column without a default (no rewrite); a row of the book written by 0128 stays as it
was (``books`` NULL until the builder rewrites it). The downgrade drops the three and goes up again. Its own scratch database
(``<FBI_TEST_DB>_m0129``), so it never collides with the other migration tests."""

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

SCRATCH = f"{TEST_DB}_m0129"


def _drop(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                      (name,))
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
    """Every table's columns and every constraint of the schemas 0129 touches."""
    columns = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                        "FROM information_schema.columns WHERE table_schema IN ('market', 'raw') "
                        "ORDER BY 1, 2, ordinal_position").fetchall()
    constraints = c.execute("SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE connamespace IN ('market'::regnamespace, 'raw'::regnamespace) ORDER BY 1, 2").fetchall()
    return {"columns": columns, "constraints": constraints}


def test_0129_adds_two_tables_and_a_column_and_goes_down_and_up_again() -> None:
    with scratch_at("0128") as dsn:
        with psycopg.connect(dsn) as c:
            before = schema(c)
        command.upgrade(_cfg(), "0129")
        with psycopg.connect(dsn) as c:
            after = schema(c)
            added = {(t, n) for _, t, n, *_ in after["columns"]} - {(t, n) for _, t, n, *_ in before["columns"]}
            assert {t for t, _ in added} == {"book_asks", "provider_reported_quota", "book_current"}
            assert [n for t, n in sorted(added) if t == "book_current"] == ["books"]
            kept = [r for r in after["columns"] if (r[1], r[2]) not in added]
            assert kept == before["columns"], "no column of another table moved"
            assert set(before["constraints"]) <= set(after["constraints"]), "no constraint was dropped or rewritten"
            books = next(r for r in after["columns"] if r[1:3] == ("book_current", "books"))
            assert books[4] == "YES" and books[5] is None, "nullable, no default: no rewrite of the table"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0129",)
        command.downgrade(_cfg(), "0128")
        with psycopg.connect(dsn) as c:
            assert schema(c) == before
            assert c.execute("SELECT to_regclass('market.book_asks'), to_regclass('raw.provider_reported_quota')"
                             ).fetchone() == (None, None)
        command.upgrade(_cfg(), "0129")
        with psycopg.connect(dsn) as c:
            assert schema(c) == after


def test_the_chain_of_the_revisions_has_this_migration_after_0128_and_one_head() -> None:
    script = ScriptDirectory.from_config(_cfg())
    revision = script.get_revision("0129")
    assert revision is not None and revision.down_revision == "0128" and re.fullmatch(r"\d{4}", revision.revision)
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert "0129" in {r.revision for r in script.walk_revisions(base="base", head=heads[0])}, heads
