"""Request-scoped dependencies."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
from fastapi import HTTPException

from fbi.core.config import settings


def read_only_connection() -> psycopg.Connection[Any]:
    """A connection whose every transaction is READ ONLY.

    Rows come back as tuples, which the quality and health modules expect;
    the API repositories ask for dict rows per cursor.

    Enforced by the server, not by convention: an INSERT reaching it fails
    with "cannot execute INSERT in a read-only transaction". The product API
    has no business writing, and this makes that a property rather than a
    promise.
    """
    return psycopg.connect(
        settings.database.psycopg_url,
        connect_timeout=3,
        options="-c default_transaction_read_only=on -c statement_timeout=10000 -c TimeZone=UTC",
    )


def get_db() -> Iterator[psycopg.Connection[Any]]:
    try:
        conn = read_only_connection()
    except psycopg.OperationalError as exc:
        # The class name only: the message can carry the host and user.
        raise HTTPException(status_code=503, detail=f"database unavailable ({exc.__class__.__name__})") from exc
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def public_mode() -> bool:
    """True on the client-facing deployment (FBI_API_PUBLIC=1): picks are limited to qualified ones."""
    return os.environ.get("FBI_API_PUBLIC", "").strip().lower() in {"1", "true", "yes"}
