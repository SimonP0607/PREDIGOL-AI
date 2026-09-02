"""Small helpers shared by the schema invariant tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest

# The PostgreSQL error classes that mean "the database refused this".
REFUSALS = (
    psycopg.errors.CheckViolation,
    psycopg.errors.NotNullViolation,
    psycopg.errors.UniqueViolation,
    psycopg.errors.ForeignKeyViolation,
    psycopg.errors.ExclusionViolation,
)


@contextmanager
def must_be_rejected(conn: psycopg.Connection, reason: str) -> Iterator[psycopg.Cursor]:
    """Assert the enclosed statement is refused by a database constraint.

    A test that passed because of a typo (wrong column name, wrong type) would
    be worthless, so anything that is NOT an integrity refusal is re-raised as
    a failure with its real cause.
    """
    try:
        with conn.transaction(force_rollback=True), conn.cursor() as cur:
            yield cur
    except REFUSALS:
        return
    except psycopg.Error as exc:
        pytest.fail(f"{reason}: refused for the WRONG reason -> {exc.__class__.__name__}: {exc}")
    pytest.fail(f"{reason}: the database ACCEPTED it. The invariant is gone.")


@contextmanager
def must_be_accepted(conn: psycopg.Connection) -> Iterator[psycopg.Cursor]:
    """Run the enclosed statements and roll them back; they must not raise."""
    with conn.transaction(force_rollback=True), conn.cursor() as cur:
        yield cur
