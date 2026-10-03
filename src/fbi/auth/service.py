"""Sign-in, sessions, preferences and account management.

Every decision about who may do what is made here or in ``roles``; the API layer only
translates HTTP to these calls. Errors carry a machine-readable code the frontend
translates - never a sentence in one language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any
from zoneinfo import available_timezones

import psycopg
import structlog

from fbi.auth import passwords, store, throttle, tokens
from fbi.auth.db import write_connection
from fbi.auth.roles import Permission, Role, is_role, permissions_for
from fbi.auth.settings import session_settings

log = structlog.get_logger("auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LANGUAGES = ("es", "en")


class AuthError(Exception):
    """An expected refusal: a status, a code the UI translates, and nothing secret."""

    def __init__(self, status: int, code: str, *, retry_after: int | None = None,
                 problems: list[str] | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.retry_after = retry_after
        self.problems = problems or []


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: int
    email: str
    display_name: str
    role: str
    language: str
    timezone: str
    session_id: str
    session_expires_at: datetime
    permissions: frozenset[Permission]

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    @property
    def is_super_admin(self) -> bool:
        return self.role == Role.SUPER_ADMIN


def normalize_email(email: str) -> str:
    return email.strip().lower()


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(available_timezones())


def valid_timezone(name: str) -> bool:
    return name == "UTC" or name in _zones()


def _principal(row: dict[str, Any], session_id: str, expires_at: datetime) -> Principal:
    return Principal(
        user_id=int(row["id"]), email=row["email"], display_name=row["display_name"], role=row["role"],
        language=row["language"], timezone=row["timezone"], session_id=session_id,
        session_expires_at=expires_at, permissions=permissions_for(row["role"]),
    )


def login(email: str, password: str, *, ip: str | None, user_agent: str | None) -> tuple[str, Principal]:
    """Returns the cookie token and who it belongs to. The token is shown to nobody else."""
    address = normalize_email(email)
    client = ip or "unknown"
    for window, key in ((throttle.BY_EMAIL, address), (throttle.BY_CLIENT, client)):
        if window.blocked(key):
            raise AuthError(429, "too_many_attempts", retry_after=window.retry_after(key))
    cfg = session_settings()
    refusal: AuthError | None = None
    # A refusal is recorded and COMMITTED before it is raised: raising inside the block would
    # roll the audit row back with everything else.
    with write_connection() as conn:
        user = store.user_by_email(conn, address) if EMAIL_RE.match(address) else None
        if user is None:
            passwords.burn_verification_time(password)
            store.record_event(conn, "login.failed", email=address, ip=ip, detail={"reason": "unknown_email"})
            refusal = AuthError(401, "invalid_credentials")
        elif not passwords.verify_password(user["password_hash"], password):
            store.record_event(conn, "login.failed", target_user_id=user["id"], email=address, ip=ip,
                               detail={"reason": "wrong_password"})
            refusal = AuthError(401, "invalid_credentials")
        elif user["status"] != "active":
            store.record_event(conn, "login.refused", target_user_id=user["id"], email=address, ip=ip,
                               detail={"reason": "disabled"})
            refusal = AuthError(403, "account_disabled")
        else:
            if passwords.needs_rehash(user["password_hash"]):
                store.update_user(conn, int(user["id"]), {"password_hash": passwords.hash_password(password)})
            token = tokens.new_token()
            session = store.insert_session(conn, session_id=tokens.token_id(token), user_id=int(user["id"]),
                                           ttl_hours=cfg.ttl_hours, user_agent=(user_agent or "")[:300] or None,
                                           ip=(ip or "")[:64] or None)
            store.mark_login(conn, int(user["id"]))
            store.record_event(conn, "login.succeeded", actor_user_id=user["id"], target_user_id=user["id"],
                               email=address, ip=ip)
    if refusal is not None:
        if refusal.code == "invalid_credentials":
            _failed(address, client)
        raise refusal
    assert user is not None
    throttle.BY_EMAIL.clear(address)
    log.info("auth.login", user_id=user["id"], role=user["role"])
    return token, _principal(user, session["id"], session["expires_at"])


def _failed(address: str, client: str) -> None:
    throttle.BY_EMAIL.fail(address)
    throttle.BY_CLIENT.fail(client)


def principal_from_token(conn: psycopg.Connection[Any], token: str | None) -> Principal | None:
    """Who a cookie belongs to, on the request's read-only connection. None: nobody."""
    if not tokens.looks_like_token(token):
        return None
    assert token is not None
    cfg = session_settings()
    sid = tokens.token_id(token)
    row = store.session_principal(conn, sid, idle_hours=cfg.idle_hours, touch_minutes=cfg.touch_minutes)
    if row is None:
        return None
    if row["needs_touch"]:
        try:
            with write_connection() as wconn:
                store.touch_session(wconn, sid)
        except psycopg.Error as exc:  # a missed touch shortens nothing that matters
            log.warning("auth.touch_failed", error=exc.__class__.__name__)
    return _principal(row, sid, row["expires_at"])


def logout(principal: Principal, *, ip: str | None) -> None:
    with write_connection() as conn:
        store.revoke_session(conn, principal.session_id, "logout")
        store.record_event(conn, "logout", actor_user_id=principal.user_id, target_user_id=principal.user_id,
                           ip=ip)


def update_preferences(principal: Principal, *, language: str | None = None, timezone: str | None = None,
                       display_name: str | None = None) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if language is not None:
        if language not in LANGUAGES:
            raise AuthError(422, "invalid_language")
        fields["language"] = language
    if timezone is not None:
        if not valid_timezone(timezone):
            raise AuthError(422, "invalid_timezone")
        fields["timezone"] = timezone
    if display_name is not None:
        name = display_name.strip()
        if not 1 <= len(name) <= 80:
            raise AuthError(422, "invalid_display_name")
        fields["display_name"] = name
    with write_connection() as conn:
        row = store.update_user(conn, principal.user_id, fields)
        if row is None:
            raise AuthError(404, "user_not_found")
        if fields:
            store.record_event(conn, "preferences.updated", actor_user_id=principal.user_id,
                               target_user_id=principal.user_id, detail={"fields": sorted(fields)})
    return row


def change_password(principal: Principal, *, current_password: str, new_password: str, ip: str | None) -> None:
    refusal: AuthError | None = None
    with write_connection() as conn:
        user = store.user_by_id(conn, principal.user_id)
        if user is None:
            raise AuthError(404, "user_not_found")
        if not passwords.verify_password(user["password_hash"], current_password):
            store.record_event(conn, "password.change_refused", actor_user_id=principal.user_id,
                               target_user_id=principal.user_id, ip=ip, detail={"reason": "wrong_password"})
            refusal = AuthError(403, "wrong_password")
        else:
            problems = passwords.password_problems(new_password, email=user["email"])
            if problems:
                refusal = AuthError(422, "weak_password", problems=problems)
            else:
                store.update_user(conn, principal.user_id, {"password_hash": passwords.hash_password(new_password)})
                revoked = store.revoke_user_sessions(conn, principal.user_id, "password_changed",
                                                     keep=principal.session_id)
                store.record_event(conn, "password.changed", actor_user_id=principal.user_id,
                                   target_user_id=principal.user_id, ip=ip,
                                   detail={"other_sessions_revoked": revoked})
    if refusal is not None:
        raise refusal


# ── accounts (Admin Console) ─────────────────────────────────────────────────────────

def list_users(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return store.list_users(conn)


def create_user(actor: Principal, *, email: str, display_name: str | None, role: str, password: str,
                language: str = "es", timezone: str = "UTC", ip: str | None = None) -> dict[str, Any]:
    """Also used by scripts/create_user.py with a synthetic actor-less call (actor may be None there)."""
    return _create_user(actor.user_id, email=email, display_name=display_name, role=role, password=password,
                        language=language, timezone=timezone, ip=ip)


def _create_user(actor_user_id: int | None, *, email: str, display_name: str | None, role: str, password: str,
                 language: str, timezone: str, ip: str | None) -> dict[str, Any]:
    address = normalize_email(email)
    if not EMAIL_RE.match(address) or len(address) > 254:
        raise AuthError(422, "invalid_email")
    if not is_role(role):
        raise AuthError(422, "invalid_role")
    if language not in LANGUAGES:
        raise AuthError(422, "invalid_language")
    if not valid_timezone(timezone):
        raise AuthError(422, "invalid_timezone")
    problems = passwords.password_problems(password, email=address)
    if problems:
        raise AuthError(422, "weak_password", problems=problems)
    name = (display_name or address.split("@", 1)[0]).strip()[:80] or address
    with write_connection() as conn:
        if store.user_by_email(conn, address) is not None:
            raise AuthError(409, "email_taken")
        row = store.insert_user(conn, email=address, display_name=name,
                                password_hash=passwords.hash_password(password), role=role,
                                language=language, timezone=timezone)
        store.record_event(conn, "user.created", actor_user_id=actor_user_id, target_user_id=row["id"],
                           email=address, ip=ip, detail={"role": role})
    return row


def create_user_unattended(*, email: str, display_name: str | None, role: str, password: str,
                           language: str = "es", timezone: str = "UTC") -> dict[str, Any]:
    """For the operator's command line, where no one is signed in."""
    return _create_user(None, email=email, display_name=display_name, role=role, password=password,
                        language=language, timezone=timezone, ip=None)


def set_password_unattended(*, email: str, password: str) -> dict[str, Any]:
    address = normalize_email(email)
    problems = passwords.password_problems(password, email=address)
    if problems:
        raise AuthError(422, "weak_password", problems=problems)
    with write_connection() as conn:
        user = store.user_by_email(conn, address)
        if user is None:
            raise AuthError(404, "user_not_found")
        row = store.update_user(conn, int(user["id"]), {"password_hash": passwords.hash_password(password)})
        store.revoke_user_sessions(conn, int(user["id"]), "password_reset")
        store.record_event(conn, "password.reset", target_user_id=user["id"], email=address,
                           detail={"by": "command_line"})
    assert row is not None
    return row


def update_user(actor: Principal, user_id: int, *, role: str | None = None, status: str | None = None,
                ip: str | None = None) -> dict[str, Any]:
    if role is not None and not is_role(role):
        raise AuthError(422, "invalid_role")
    if status is not None and status not in ("active", "disabled"):
        raise AuthError(422, "invalid_status")
    with write_connection() as conn:
        target = store.user_by_id(conn, user_id)
        if target is None:
            raise AuthError(404, "user_not_found")
        loses_admin = target["role"] == Role.SUPER_ADMIN and target["status"] == "active" and (
            (role is not None and role != Role.SUPER_ADMIN) or status == "disabled")
        if user_id == actor.user_id and status == "disabled":
            raise AuthError(409, "cannot_disable_self")
        if loses_admin and store.count_active_super_admins(conn, excluding=user_id) == 0:
            raise AuthError(409, "last_super_admin")
        fields: dict[str, Any] = {}
        if role is not None and role != target["role"]:
            fields["role"] = role
        if status is not None and status != target["status"]:
            fields["status"] = status
        if not fields:
            return target
        row = store.update_user(conn, user_id, fields)
        assert row is not None
        if "role" in fields:
            store.record_event(conn, "user.role_changed", actor_user_id=actor.user_id, target_user_id=user_id,
                               ip=ip, detail={"from": target["role"], "to": fields["role"]})
        if "status" in fields:
            store.record_event(conn, "user.status_changed", actor_user_id=actor.user_id, target_user_id=user_id,
                               ip=ip, detail={"from": target["status"], "to": fields["status"]})
            if fields["status"] == "disabled":
                store.revoke_user_sessions(conn, user_id, "account_disabled")
    return row


def audit_events(conn: psycopg.Connection[Any], *, limit: int, offset: int,
                 action: str | None) -> tuple[list[dict[str, Any]], int]:
    return store.list_events(conn, limit=limit, offset=offset, action=action), store.count_events(conn, action=action)
