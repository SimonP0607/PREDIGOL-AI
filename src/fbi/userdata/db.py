"""The writable connection for a user's own records (picks.user_picks, picks.user_parlays and
their legs) - nothing else is written through it."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg

from fbi.core.config import settings


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
