"""SQL for the product API. Plain rows out; no interpretation.

Every query is a static string with bound parameters. Where a query has to
vary (sort direction), the variants are separate constants chosen by a
validated enum - user input never reaches the SQL text.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row

Row = dict[str, Any]
Conn = psycopg.Connection[Any]


def fetch_all(conn: Conn, sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> list[Row]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def fetch_one(conn: Conn, sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Row | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        r = cur.fetchone()
        return dict(r) if r is not None else None


def fetch_value(conn: Conn, sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> Any:
    r = fetch_one(conn, sql, params)
    return next(iter(r.values())) if r else None
