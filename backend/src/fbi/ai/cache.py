"""The research cache: a search, a page or a story answered once, reused until it expires.

Keys are scoped (fixture, team, player, url, story, search). TTLs are short for what changes before a
match (a search: hours) and long for what does not (a page already read: days). A cache row is not a
record - what a page taught is stored as evidence (``ai.evidence``) - so refreshing it is an overwrite.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

SCOPES = frozenset({"fixture", "team", "player", "url", "story", "search"})


def get(conn: psycopg.Connection[Any], scope: str, key: str, *, at: datetime) -> dict[str, Any] | None:
    if scope not in SCOPES:
        raise ValueError(f"unknown cache scope {scope!r}")
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("UPDATE ai.research_cache SET hits = hits + 1, last_hit_at = %s WHERE scope = %s AND key = %s "
                    "AND expires_at > %s RETURNING payload", (at, scope, key[:500], at))
        row = cur.fetchone()
    return None if row is None else dict(row[0])


def put(conn: psycopg.Connection[Any], scope: str, key: str, payload: dict[str, Any], *, at: datetime,
        ttl: timedelta) -> None:
    if scope not in SCOPES:
        raise ValueError(f"unknown cache scope {scope!r}")
    body = json.dumps(payload, sort_keys=True, default=str)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO ai.research_cache (scope, key, fetched_at, expires_at, content_hash, payload) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (scope, key) DO UPDATE SET fetched_at = EXCLUDED.fetched_at, "
                    "expires_at = EXCLUDED.expires_at, content_hash = EXCLUDED.content_hash, payload = EXCLUDED.payload",
                    (scope, key[:500], at, at + ttl, hashlib.sha256(body.encode()).hexdigest(), Jsonb(json.loads(body))))


def purge_expired(conn: psycopg.Connection[Any], *, at: datetime, keep: timedelta = timedelta(days=14)) -> int:
    """Expired cache rows older than ``keep`` (a cache, not history)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("DELETE FROM ai.research_cache WHERE expires_at < %s", (at - keep,))
        return max(cur.rowcount, 0)
