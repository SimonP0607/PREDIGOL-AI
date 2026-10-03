"""SQL for the auth schema. No business rule lives here - only reads and writes."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

Row = dict[str, Any]
Conn = psycopg.Connection[Any]

USER_COLUMNS = ("u.id, u.email, u.display_name, u.password_hash, u.role, u.status, u.language, u.timezone, "
                "u.created_at, u.updated_at, u.last_login_at, u.password_changed_at")


def _one(conn: Conn, sql: str, params: tuple[Any, ...] | dict[str, Any]) -> Row | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row is not None else None


def _all(conn: Conn, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[Row]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def user_by_email(conn: Conn, email: str) -> Row | None:
    return _one(conn, f"SELECT {USER_COLUMNS} FROM auth.users u WHERE u.email = %s", (email,))


def user_by_id(conn: Conn, user_id: int) -> Row | None:
    return _one(conn, f"SELECT {USER_COLUMNS} FROM auth.users u WHERE u.id = %s", (user_id,))


def insert_user(conn: Conn, *, email: str, display_name: str, password_hash: str, role: str,
                language: str, timezone: str) -> Row:
    row = _one(conn, f"""
        INSERT INTO auth.users AS u (email, display_name, password_hash, role, language, timezone)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING {USER_COLUMNS}
    """, (email, display_name, password_hash, role, language, timezone))
    assert row is not None
    return row


def update_user(conn: Conn, user_id: int, fields: dict[str, Any]) -> Row | None:
    allowed = {"display_name", "role", "status", "language", "timezone", "password_hash"}
    sets = [k for k in fields if k in allowed]
    if not sets:
        return user_by_id(conn, user_id)
    assignments = ", ".join(f"{k} = %({k})s" for k in sets)
    extra = ", password_changed_at = now()" if "password_hash" in sets else ""
    params = {k: fields[k] for k in sets} | {"id": user_id}
    return _one(conn, f"UPDATE auth.users AS u SET {assignments}, updated_at = now(){extra} "
                      f"WHERE u.id = %(id)s RETURNING {USER_COLUMNS}", params)


def mark_login(conn: Conn, user_id: int) -> None:
    conn.execute("UPDATE auth.users SET last_login_at = now() WHERE id = %s", (user_id,))


def list_users(conn: Conn) -> list[Row]:
    return _all(conn, f"""
        SELECT {USER_COLUMNS},
               (SELECT count(*) FROM auth.sessions s
                 WHERE s.user_id = u.id AND s.revoked_at IS NULL AND s.expires_at > now())::int AS active_sessions
        FROM auth.users u ORDER BY u.created_at, u.id
    """)


def count_active_super_admins(conn: Conn, *, excluding: int | None = None) -> int:
    row = _one(conn, "SELECT count(*)::int AS n FROM auth.users WHERE role = 'SUPER_ADMIN' AND status = 'active' "
                     "AND (%s::bigint IS NULL OR id <> %s)", (excluding, excluding))
    return int(row["n"]) if row else 0


def role_exists(conn: Conn, role: str) -> bool:
    return _one(conn, "SELECT 1 AS x FROM auth.roles WHERE key = %s", (role,)) is not None


def insert_session(conn: Conn, *, session_id: str, user_id: int, ttl_hours: int,
                   user_agent: str | None, ip: str | None) -> Row:
    row = _one(conn, """
        INSERT INTO auth.sessions (id, user_id, expires_at, user_agent, ip)
        VALUES (%s, %s, now() + make_interval(hours => %s), %s, %s)
        RETURNING id, user_id, created_at, expires_at
    """, (session_id, user_id, ttl_hours, user_agent, ip))
    assert row is not None
    return row


def session_principal(conn: Conn, session_id: str, *, idle_hours: int, touch_minutes: int) -> Row | None:
    """The live session and its user, or None. Read-only: safe on the API's read-only connection."""
    return _one(conn, """
        SELECT s.id AS session_id, s.expires_at, s.last_seen_at,
               s.last_seen_at < now() - make_interval(mins => %s) AS needs_touch,
               u.id, u.email, u.display_name, u.role, u.status, u.language, u.timezone
        FROM auth.sessions s JOIN auth.users u ON u.id = s.user_id
        WHERE s.id = %s AND s.revoked_at IS NULL AND s.expires_at > now()
          AND s.last_seen_at > now() - make_interval(hours => %s)
          AND u.status = 'active'
    """, (touch_minutes, session_id, idle_hours))


def touch_session(conn: Conn, session_id: str) -> None:
    conn.execute("UPDATE auth.sessions SET last_seen_at = now() WHERE id = %s AND revoked_at IS NULL",
                 (session_id,))


def revoke_session(conn: Conn, session_id: str, reason: str) -> int:
    cur = conn.execute("UPDATE auth.sessions SET revoked_at = now(), revoked_reason = %s "
                       "WHERE id = %s AND revoked_at IS NULL", (reason, session_id))
    return cur.rowcount


def revoke_user_sessions(conn: Conn, user_id: int, reason: str, *, keep: str | None = None) -> int:
    cur = conn.execute("UPDATE auth.sessions SET revoked_at = now(), revoked_reason = %s "
                       "WHERE user_id = %s AND revoked_at IS NULL AND (%s::text IS NULL OR id <> %s)",
                       (reason, user_id, keep, keep))
    return cur.rowcount


def record_event(conn: Conn, action: str, *, actor_user_id: int | None = None, target_user_id: int | None = None,
                 email: str | None = None, ip: str | None = None, detail: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO auth.audit_events (action, actor_user_id, target_user_id, email, ip, detail) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (action, actor_user_id, target_user_id, (email or None) and email[:254], (ip or None) and ip[:64],
         Jsonb(detail or {})),
    )


def list_events(conn: Conn, *, limit: int, offset: int, action: str | None = None) -> list[Row]:
    return _all(conn, """
        SELECT e.id, e.at, e.action, e.email, e.ip, e.detail,
               a.email AS actor_email, t.email AS target_email
        FROM auth.audit_events e
        LEFT JOIN auth.users a ON a.id = e.actor_user_id
        LEFT JOIN auth.users t ON t.id = e.target_user_id
        WHERE (%s::text IS NULL OR e.action = %s)
        ORDER BY e.at DESC, e.id DESC LIMIT %s OFFSET %s
    """, (action, action, limit, offset))


def count_events(conn: Conn, *, action: str | None = None) -> int:
    row = _one(conn, "SELECT count(*)::int AS n FROM auth.audit_events WHERE (%s::text IS NULL OR action = %s)",
               (action, action))
    return int(row["n"]) if row else 0
