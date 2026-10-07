"""SQL for the auth schema. No business rule lives here - only reads and writes."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

Row = dict[str, Any]
Conn = psycopg.Connection[Any]

USER_COLUMNS = ("u.id, u.email, u.display_name, u.password_hash, u.role, u.status, u.language, u.timezone, "
                "u.created_at, u.updated_at, u.last_login_at, u.password_changed_at, u.failed_logins, "
                "u.locked_until, u.locked_until > now() AS is_locked, u.must_change_password, u.mfa_required, "
                "u.totp_secret, u.totp_enabled_at, u.totp_last_step, "
                "(SELECT count(*) FROM auth.recovery_codes r WHERE r.user_id = u.id AND r.used_at IS NULL)::int "
                "AS recovery_codes_left")

SESSION_STAGES = ("mfa", "enroll", "password", "full")


def _one(conn: Conn, sql: str, params: tuple[Any, ...] | dict[str, Any]) -> Row | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row is not None else None


def _all(conn: Conn, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[Row]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


# ── accounts ─────────────────────────────────────────────────────────────────────────

def user_by_email(conn: Conn, email: str) -> Row | None:
    return _one(conn, f"SELECT {USER_COLUMNS} FROM auth.users u WHERE u.email = %s", (email,))


def user_by_id(conn: Conn, user_id: int, *, for_update: bool = False) -> Row | None:
    lock = " FOR UPDATE OF u" if for_update else ""
    return _one(conn, f"SELECT {USER_COLUMNS} FROM auth.users u WHERE u.id = %s{lock}", (user_id,))


def insert_user(conn: Conn, *, email: str, display_name: str, password_hash: str, role: str,
                language: str, timezone: str, must_change_password: bool = False) -> Row:
    row = _one(conn, """
        INSERT INTO auth.users AS u (email, display_name, password_hash, role, language, timezone,
                                     must_change_password)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (email, display_name, password_hash, role, language, timezone, must_change_password))
    assert row is not None
    user = user_by_id(conn, int(row["id"]))
    assert user is not None
    return user


UPDATABLE = {"display_name", "role", "status", "language", "timezone", "password_hash", "must_change_password",
             "mfa_required"}


def update_user(conn: Conn, user_id: int, fields: dict[str, Any]) -> Row | None:
    sets = [k for k in fields if k in UPDATABLE]
    if not sets:
        return user_by_id(conn, user_id)
    assignments = ", ".join(f"{k} = %({k})s" for k in sets)
    extra = ", password_changed_at = now()" if "password_hash" in sets else ""
    params = {k: fields[k] for k in sets} | {"id": user_id}
    cur = conn.execute(f"UPDATE auth.users AS u SET {assignments}, updated_at = now(){extra} WHERE u.id = %(id)s",
                       params)
    if cur.rowcount == 0:
        return None
    return user_by_id(conn, user_id)


def mark_login(conn: Conn, user_id: int) -> None:
    conn.execute("UPDATE auth.users SET last_login_at = now(), failed_logins = 0, locked_until = NULL "
                 "WHERE id = %s", (user_id,))


def record_failure(conn: Conn, user_id: int, *, threshold: int, lock_minutes: int, max_minutes: int) -> Row:
    """One more consecutive failure. From the threshold on, each failure (re)locks the account: lock_minutes, then
    doubling with every further block of `threshold` failures, never more than max_minutes. Returns the counters."""
    row = _one(conn, """
        UPDATE auth.users SET failed_logins = failed_logins + 1,
               locked_until = CASE
                 WHEN failed_logins + 1 >= %(t)s THEN now() + make_interval(mins => LEAST(%(max)s,
                      %(m)s * power(2, LEAST(10, (failed_logins + 1 - %(t)s) / %(t)s))::int))
                 ELSE locked_until END
        WHERE id = %(id)s
        RETURNING failed_logins, locked_until, locked_until > now() AS is_locked
    """, {"t": threshold, "m": lock_minutes, "max": max_minutes, "id": user_id})
    assert row is not None
    return row


def unlock(conn: Conn, user_id: int) -> None:
    conn.execute("UPDATE auth.users SET failed_logins = 0, locked_until = NULL, updated_at = now() WHERE id = %s",
                 (user_id,))


def set_totp(conn: Conn, user_id: int, sealed_secret: bytes, step: int) -> None:
    conn.execute("UPDATE auth.users SET totp_secret = %s, totp_enabled_at = now(), totp_last_step = %s, "
                 "updated_at = now() WHERE id = %s", (sealed_secret, step, user_id))


def accept_totp_step(conn: Conn, user_id: int, step: int) -> bool:
    """Record the step of an accepted code - only if it is newer than the last one (no replay, even under a race)."""
    cur = conn.execute("UPDATE auth.users SET totp_last_step = %s WHERE id = %s "
                       "AND (totp_last_step IS NULL OR totp_last_step < %s)", (step, user_id, step))
    return cur.rowcount == 1


def clear_totp(conn: Conn, user_id: int) -> None:
    conn.execute("UPDATE auth.users SET totp_secret = NULL, totp_enabled_at = NULL, totp_last_step = NULL, "
                 "updated_at = now() WHERE id = %s", (user_id,))
    conn.execute("DELETE FROM auth.recovery_codes WHERE user_id = %s", (user_id,))


def replace_recovery_codes(conn: Conn, user_id: int, hashes: list[str]) -> None:
    conn.execute("DELETE FROM auth.recovery_codes WHERE user_id = %s", (user_id,))
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO auth.recovery_codes (user_id, code_hash) VALUES (%s, %s)",
                        [(user_id, h) for h in hashes])


def use_recovery_code(conn: Conn, user_id: int, code_hash: str) -> bool:
    cur = conn.execute("UPDATE auth.recovery_codes SET used_at = now() "
                       "WHERE user_id = %s AND code_hash = %s AND used_at IS NULL", (user_id, code_hash))
    return cur.rowcount == 1


def list_users(conn: Conn) -> list[Row]:
    return _all(conn, f"""
        SELECT {USER_COLUMNS},
               (SELECT count(*) FROM auth.sessions s
                 WHERE s.user_id = u.id AND s.revoked_at IS NULL AND s.expires_at > now()
                   AND s.stage = 'full')::int AS active_sessions
        FROM auth.users u ORDER BY u.created_at, u.id
    """)


def count_active_super_admins(conn: Conn, *, excluding: int | None = None) -> int:
    row = _one(conn, "SELECT count(*)::int AS n FROM auth.users WHERE role = 'SUPER_ADMIN' AND status = 'active' "
                     "AND (%s::bigint IS NULL OR id <> %s)", (excluding, excluding))
    return int(row["n"]) if row else 0


def role_exists(conn: Conn, role: str) -> bool:
    return _one(conn, "SELECT 1 AS x FROM auth.roles WHERE key = %s", (role,)) is not None


# ── sessions ─────────────────────────────────────────────────────────────────────────

def insert_session(conn: Conn, *, session_id: str, user_id: int, ttl_minutes: int, stage: str,
                   user_agent: str | None, ip: str | None, mfa_verified: bool = False) -> Row:
    assert stage in SESSION_STAGES
    row = _one(conn, """
        INSERT INTO auth.sessions (id, user_id, expires_at, user_agent, ip, stage, mfa_verified_at)
        VALUES (%s, %s, now() + make_interval(mins => %s), %s, %s, %s, CASE WHEN %s THEN now() END)
        RETURNING id, user_id, created_at, expires_at, stage
    """, (session_id, user_id, ttl_minutes, user_agent, ip, stage, mfa_verified))
    assert row is not None
    return row


def session_principal(conn: Conn, session_id: str, *, idle_hours: int, admin_idle_hours: int,
                      touch_minutes: int) -> Row | None:
    """The live session and its user, or None. Read-only: safe on the API's read-only connection."""
    return _one(conn, """
        SELECT s.id AS session_id, s.expires_at, s.last_seen_at, s.stage, s.mfa_attempts,
               s.last_seen_at < now() - make_interval(mins => %s) AS needs_touch,
               u.id, u.email, u.display_name, u.role, u.status, u.language, u.timezone, u.mfa_required,
               u.must_change_password, u.totp_enabled_at IS NOT NULL AS mfa_enabled,
               (SELECT count(*) FROM auth.recovery_codes r WHERE r.user_id = u.id AND r.used_at IS NULL)::int
                 AS recovery_codes_left
        FROM auth.sessions s JOIN auth.users u ON u.id = s.user_id
        WHERE s.id = %s AND s.revoked_at IS NULL AND s.expires_at > now()
          AND s.last_seen_at > now() - make_interval(hours => CASE WHEN u.role = 'SUPER_ADMIN' THEN %s ELSE %s END)
          AND u.status = 'active'
    """, (touch_minutes, session_id, admin_idle_hours, idle_hours))


def session_for_update(conn: Conn, session_id: str) -> Row | None:
    return _one(conn, """
        SELECT s.id, s.user_id, s.stage, s.mfa_attempts, s.pending_totp_secret, s.expires_at
        FROM auth.sessions s
        WHERE s.id = %s AND s.revoked_at IS NULL AND s.expires_at > now()
        FOR UPDATE
    """, (session_id,))


def bump_mfa_attempts(conn: Conn, session_id: str) -> int:
    row = _one(conn, "UPDATE auth.sessions SET mfa_attempts = mfa_attempts + 1 WHERE id = %s "
                     "RETURNING mfa_attempts", (session_id,))
    return int(row["mfa_attempts"]) if row else 0


def set_pending_secret(conn: Conn, session_id: str, sealed: bytes | None) -> None:
    conn.execute("UPDATE auth.sessions SET pending_totp_secret = %s WHERE id = %s", (sealed, session_id))


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


def revoke_user_session_by_prefix(conn: Conn, user_id: int, prefix: str, reason: str) -> int:
    cur = conn.execute("UPDATE auth.sessions SET revoked_at = now(), revoked_reason = %s "
                       "WHERE user_id = %s AND revoked_at IS NULL AND left(id, %s) = %s",
                       (reason, user_id, len(prefix), prefix))
    return cur.rowcount


def list_sessions(conn: Conn, user_id: int) -> list[Row]:
    return _all(conn, """
        SELECT left(s.id, 16) AS id, s.created_at, s.last_seen_at, s.expires_at, s.ip, s.user_agent, s.stage,
               s.mfa_verified_at IS NOT NULL AS mfa_verified, s.id AS full_id
        FROM auth.sessions s
        WHERE s.user_id = %s AND s.revoked_at IS NULL AND s.expires_at > now()
        ORDER BY s.last_seen_at DESC
    """, (user_id,))


# ── audit ────────────────────────────────────────────────────────────────────────────

def record_event(conn: Conn, action: str, *, actor_user_id: int | None = None, target_user_id: int | None = None,
                 email: str | None = None, ip: str | None = None, detail: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO auth.audit_events (action, actor_user_id, target_user_id, email, ip, detail) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (action, actor_user_id, target_user_id, (email or None) and email[:254], (ip or None) and ip[:64],
         Jsonb(detail or {})),
    )


def list_events(conn: Conn, *, limit: int, offset: int, action: str | None = None,
                target_user_id: int | None = None) -> list[Row]:
    return _all(conn, """
        SELECT e.id, e.at, e.action, e.email, e.ip, e.detail,
               a.email AS actor_email, t.email AS target_email
        FROM auth.audit_events e
        LEFT JOIN auth.users a ON a.id = e.actor_user_id
        LEFT JOIN auth.users t ON t.id = e.target_user_id
        WHERE (%s::text IS NULL OR e.action = %s) AND (%s::bigint IS NULL OR e.target_user_id = %s)
        ORDER BY e.at DESC, e.id DESC LIMIT %s OFFSET %s
    """, (action, action, target_user_id, target_user_id, limit, offset))


def count_events(conn: Conn, *, action: str | None = None, target_user_id: int | None = None) -> int:
    row = _one(conn, "SELECT count(*)::int AS n FROM auth.audit_events WHERE (%s::text IS NULL OR action = %s) "
                     "AND (%s::bigint IS NULL OR target_user_id = %s)",
               (action, action, target_user_id, target_user_id))
    return int(row["n"]) if row else 0


ACCESS_ACTIONS = ("login.succeeded", "login.failed", "login.refused", "login.locked", "mfa.verified", "mfa.failed",
                  "mfa.recovery_code_used", "logout", "password.changed", "session.revoked", "mfa.enrolled")


def access_history(conn: Conn, user_id: int, *, limit: int) -> list[Row]:
    return _all(conn, """
        SELECT e.at, e.action, e.ip, e.detail->>'user_agent' AS user_agent, e.detail->>'reason' AS reason
        FROM auth.audit_events e
        WHERE e.target_user_id = %s AND e.action = ANY(%s)
        ORDER BY e.at DESC, e.id DESC LIMIT %s
    """, (user_id, list(ACCESS_ACTIONS), limit))
