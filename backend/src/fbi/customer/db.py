"""The writable connection for the customer's own data (the ``customer`` schema) - nothing else is written through
it. Reads go through the API's read-only connection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from fbi.core.config import settings


class CustomerError(ValueError):
    """A request the rules refuse: ``status`` and ``code`` are stable for the API and the UI."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@contextmanager
def write_connection() -> Iterator[psycopg.Connection[Any]]:
    """Commits on a clean exit, rolls back on an exception. Every statement is bounded."""
    conn = psycopg.connect(settings.database.psycopg_url, connect_timeout=3,
                           options="-c statement_timeout=5000 -c TimeZone=UTC")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
