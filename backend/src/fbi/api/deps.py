"""Request-scoped dependencies."""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Iterator
from typing import Any

import psycopg
from fastapi import HTTPException
from psycopg.rows import tuple_row
from psycopg_pool import ConnectionPool, PoolTimeout

from fbi.core.config import settings

READ_ONLY_OPTIONS = "-c default_transaction_read_only=on -c statement_timeout=10000 -c TimeZone=UTC"


def read_only_connection() -> psycopg.Connection[Any]:
    """A connection whose every transaction is READ ONLY.

    Rows come back as tuples, which the quality and health modules expect;
    the API repositories ask for dict rows per cursor.

    Enforced by the server, not by convention: an INSERT reaching it fails
    with "cannot execute INSERT in a read-only transaction". The product API
    has no business writing, and this makes that a property rather than a
    promise.
    """
    return psycopg.connect(settings.database.psycopg_url, connect_timeout=3, options=READ_ONLY_OPTIONS)


# One pool per process and database URL (uvicorn runs several processes). FBI_API_DB_POOL_MAX bounds the queries
# one process runs at once - the rest wait up to FBI_API_DB_POOL_TIMEOUT seconds, then get a 503 - and 0 turns
# pooling off (a connection per request, as before). The rehearsal of 7 Oct 2026 found the unpooled API opening
# a connection per request: 200 users exhausted max_connections (1,129 answers 503) on top of saturating the CPU.
_POOLS: dict[str, ConnectionPool[psycopg.Connection[Any]]] = {}
_POOLS_LOCK = threading.Lock()


def _reset(conn: psycopg.Connection[Any]) -> None:
    conn.row_factory = tuple_row  # as a fresh connection: whatever a request set does not leak into the next


def read_pool() -> ConnectionPool[psycopg.Connection[Any]] | None:
    size = int(os.environ.get("FBI_API_DB_POOL_MAX", "8"))
    if size <= 0:
        return None
    url = settings.database.psycopg_url
    pool = _POOLS.get(url)
    if pool is None:
        with _POOLS_LOCK:
            pool = _POOLS.get(url)
            if pool is None:
                pool = ConnectionPool(
                    url, min_size=min(size, int(os.environ.get("FBI_API_DB_POOL_MIN", "1"))), max_size=size,
                    timeout=float(os.environ.get("FBI_API_DB_POOL_TIMEOUT", "10")), max_idle=300.0,
                    max_lifetime=3600.0, kwargs={"connect_timeout": 3, "options": READ_ONLY_OPTIONS},
                    reset=_reset, name="api-read", open=True,
                )
                _POOLS[url] = pool
    return pool


def close_pools() -> None:
    with _POOLS_LOCK:
        for pool in _POOLS.values():
            pool.close()
        _POOLS.clear()


def get_db() -> Iterator[psycopg.Connection[Any]]:
    pool = read_pool()
    try:
        conn = read_only_connection() if pool is None else pool.getconn()
    except PoolTimeout as exc:
        raise HTTPException(status_code=503, detail="database busy") from exc
    except psycopg.OperationalError as exc:
        # The class name only: the message can carry the host and user.
        raise HTTPException(status_code=503, detail=f"database unavailable ({exc.__class__.__name__})") from exc
    try:
        yield conn
    finally:
        with contextlib.suppress(psycopg.Error):  # a broken connection: the pool checks it and replaces it
            conn.rollback()
        if pool is None:
            conn.close()
        else:
            pool.putconn(conn)


def public_mode() -> bool:
    """True on the client-facing deployment (FBI_API_PUBLIC=1): picks are limited to qualified ones."""
    return os.environ.get("FBI_API_PUBLIC", "").strip().lower() in {"1", "true", "yes"}
