"""Small helpers shared by the schema invariant tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

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
def must_be_rejected_saying(conn: psycopg.Connection, needle: str) -> Iterator[psycopg.Cursor]:
    """Like ``must_be_rejected``, but the refusal must SAY the expected thing.

    Where several constraints could plausibly fire on the same statement, a test
    that only asserts "something refused it" can pass for the wrong reason and
    keep passing after the invariant it was written for has gone.
    """
    try:
        with conn.transaction(force_rollback=True), conn.cursor() as cur:
            yield cur
    except REFUSALS as exc:
        assert needle in str(exc), f"refused, but not for {needle!r}: {exc}"
        return
    except psycopg.Error as exc:
        pytest.fail(f"{needle}: refused for the WRONG reason -> {exc.__class__.__name__}: {exc}")
    pytest.fail(f"{needle}: the database ACCEPTED it. The invariant is gone.")


@contextmanager
def must_be_accepted(conn: psycopg.Connection) -> Iterator[psycopg.Cursor]:
    """Run the enclosed statements and roll them back; they must not raise."""
    with conn.transaction(force_rollback=True), conn.cursor() as cur:
        yield cur


def row(cur: psycopg.Cursor) -> tuple[Any, ...]:
    """fetchone() that fails with "the query returned no row" instead of
    "NoneType is not subscriptable" three frames later."""
    fetched = cur.fetchone()
    assert fetched is not None, "the query returned no row"
    return tuple(fetched)


def scalar(cur: psycopg.Cursor) -> Any:
    """First column of the single row the query must have returned."""
    return row(cur)[0]
