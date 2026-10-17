"""Sign-in, sessions, the second factor, preferences and account management.

Every decision about who may do what is made here or in ``roles``; the API layer only
translates HTTP to these calls. Errors carry a machine-readable code the frontend
translates - never a sentence in one language.

Signing in is a short sequence of STAGES, each a session of its own:

    password ──▶ mfa (a code from the authenticator, or a recovery code)
             ──▶ enroll (set the authenticator up, when the role or the account requires one)
             ──▶ password (choose a new one, after an administrator's reset or a new account)
             ──▶ full (the product)

A staged session can do nothing but finish its stage (10 minutes, 5 wrong codes). Finishing one ISSUES A NEW
session and revokes the old one, so a token seen before the second factor is worthless after it.

Failures - a wrong password or a wrong code - count against the ACCOUNT, in the database, across every API
process: lock_threshold in a row lock it for lock_minutes, doubling while the streak goes on. Only a fully
completed sign-in resets the streak (a right password alone does not: otherwise an attacker holding the password
could try codes forever, five per session).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from zoneinfo import available_timezones

import psycopg
import structlog

from fbi.auth import crypto, passwords, store, throttle, tokens, totp
from fbi.auth.db import write_connection
from fbi.auth.roles import Permission, Role, is_role, permissions_for
from fbi.auth.settings import auth_settings, session_settings

log = structlog.get_logger("auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LANGUAGES = ("es", "en")
STAGE_REFUSALS = {"mfa": "mfa_required", "enroll": "mfa_enrollment_required",
                  "password": "password_change_required"}
"""What a staged session gets from every route that needs a full one: the code tells the page which step is
missing."""


class AuthError(Exception):
    """An expected refusal: a status, a code the UI translates, and nothing secret."""

    def __init__(self, status: int, code: str, *, retry_after: int | None = None,
                 problems: list[str] | None = None, extra: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.retry_after = retry_after
        self.problems = problems or []
        self.extra = extra or {}


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
    stage: str = "full"
    mfa_enabled: bool = False
    mfa_required: bool = False
    must_change_password: bool = False
    recovery_codes_left: int = 0

    def can(self, permission: Permission) -> bool:
        return self.stage == "full" and permission in self.permissions

    @property
    def is_super_admin(self) -> bool:
        return self.role == Role.SUPER_ADMIN

    @property
    def is_full(self) -> bool:
        return self.stage == "full"


@dataclass(frozen=True, slots=True)
class Enrollment:
    secret: str
    otpauth_uri: str
    qr_svg: str
    issuer: str
    account: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(available_timezones())


def valid_timezone(name: str) -> bool:
    return name == "UTC" or name in _zones()


def mfa_required_for(user: dict[str, Any]) -> bool:
    return bool(user.get("mfa_required")) or user.get("role") in auth_settings().required_roles()


def _ua(user_agent: str | None) -> str | None:
    return (user_agent or "")[:300] or None


def _ip(ip: str | None) -> str | None:
    return (ip or "")[:64] or None


def _principal(user: dict[str, Any], session_id: str, expires_at: datetime, stage: str) -> Principal:
    return Principal(
        user_id=int(user["id"]), email=user["email"], display_name=user["display_name"], role=user["role"],
        language=user["language"], timezone=user["timezone"], session_id=session_id,
        session_expires_at=expires_at,
        permissions=permissions_for(user["role"]) if stage == "full" else frozenset(),
        stage=stage, mfa_enabled=bool(user.get("mfa_enabled", user.get("totp_enabled_at") is not None)),
        mfa_required=mfa_required_for(user), must_change_password=bool(user.get("must_change_password")),
        recovery_codes_left=int(user.get("recovery_codes_left") or 0),
    )


def _next_stage(user: dict[str, Any], *, mfa_done: bool) -> str:
    enabled = user.get("totp_enabled_at") is not None
    if enabled and not mfa_done:
        return "mfa"
    if mfa_required_for(user) and not enabled:
        return "enroll"
    if user.get("must_change_password"):
        return "password"
    return "full"


def _ttl_minutes(user: dict[str, Any], stage: str) -> int:
    cfg = session_settings()
    if stage != "full":
        return cfg.staged_minutes
    hours = cfg.admin_ttl_hours if user["role"] == Role.SUPER_ADMIN else cfg.ttl_hours
    return hours * 60


def _retry_after(locked_until: datetime | None) -> int:
    if locked_until is None:
        return 60
    return max(1, int((locked_until - datetime.now(UTC)).total_seconds()) + 1)


def _open_session(conn: psycopg.Connection[Any], user: dict[str, Any], *, stage: str, ip: str | None,
                  user_agent: str | None, mfa_verified: bool) -> tuple[str, Principal]:
    token = tokens.new_token()
    session = store.insert_session(conn, session_id=tokens.token_id(token), user_id=int(user["id"]),
                                   ttl_minutes=_ttl_minutes(user, stage), stage=stage, user_agent=_ua(user_agent),
                                   ip=_ip(ip), mfa_verified=mfa_verified)
    if stage == "full":
        store.mark_login(conn, int(user["id"]))
        store.record_event(conn, "login.succeeded", actor_user_id=user["id"], target_user_id=user["id"],
                           email=user["email"], ip=ip,
                           detail={"user_agent": (user_agent or "")[:200], "second_factor": mfa_verified})
    fresh = store.user_by_id(conn, int(user["id"]))
    assert fresh is not None
    return token, _principal(fresh, session["id"], session["expires_at"], stage)


def _advance(conn: psycopg.Connection[Any], user_id: int, old_session_id: str, *, mfa_done: bool,
             ip: str | None, user_agent: str | None) -> tuple[str, Principal]:
    """Close a finished stage and open the next one - a NEW token every time."""
    user = store.user_by_id(conn, user_id)
    assert user is not None
    stage = _next_stage(user, mfa_done=mfa_done)
    store.revoke_session(conn, old_session_id, "stage_completed")
    return _open_session(conn, user, stage=stage, ip=ip, user_agent=user_agent,
                         mfa_verified=mfa_done and user.get("totp_enabled_at") is not None)


# ── signing in ───────────────────────────────────────────────────────────────────────

def login(email: str, password: str, *, ip: str | None, user_agent: str | None) -> tuple[str, Principal]:
    """The cookie token and who it belongs to. A staged principal when a second factor, an enrolment or a new
    password is still owed. The token is shown to nobody else."""
    address = normalize_email(email)
    client = ip or "unknown"
    for window, key in ((throttle.BY_EMAIL, address), (throttle.BY_CLIENT, client)):
        if window.blocked(key):
            raise AuthError(429, "too_many_attempts", retry_after=window.retry_after(key))
    cfg = auth_settings()
    refusal: AuthError | None = None
    result: tuple[str, Principal] | None = None
    # A refusal is recorded and COMMITTED before it is raised: raising inside the block would
    # roll the audit row (and the failure count) back with everything else.
    with write_connection() as conn:
        user = store.user_by_email(conn, address) if EMAIL_RE.match(address) else None
        if user is None:
            passwords.burn_verification_time(password)
            store.record_event(conn, "login.failed", email=address, ip=ip, detail={"reason": "unknown_email"})
            refusal = AuthError(401, "invalid_credentials")
        elif user["is_locked"]:
            passwords.burn_verification_time(password)
            store.record_event(conn, "login.refused", target_user_id=user["id"], email=address, ip=ip,
                               detail={"reason": "locked"})
            refusal = AuthError(429, "too_many_attempts", retry_after=_retry_after(user["locked_until"]))
        elif not passwords.verify_password(user["password_hash"], password):
            counters = store.record_failure(conn, int(user["id"]), threshold=cfg.lock_threshold,
                                            lock_minutes=cfg.lock_minutes, max_minutes=cfg.lock_max_minutes)
            store.record_event(conn, "login.failed", target_user_id=user["id"], email=address, ip=ip,
                               detail={"reason": "wrong_password", "streak": counters["failed_logins"]})
            if counters["is_locked"]:
                store.record_event(conn, "login.locked", target_user_id=user["id"], email=address, ip=ip,
                                   detail={"streak": counters["failed_logins"],
                                           "until": counters["locked_until"].isoformat()})
            refusal = AuthError(401, "invalid_credentials")
        elif user["status"] != "active":
            store.record_event(conn, "login.refused", target_user_id=user["id"], email=address, ip=ip,
                               detail={"reason": "disabled"})
            refusal = AuthError(403, "account_disabled")
        else:
            if passwords.needs_rehash(user["password_hash"]):
                store.update_user(conn, int(user["id"]), {"password_hash": passwords.hash_password(password)})
            stage = _next_stage(user, mfa_done=False)
            if stage != "full":
                store.record_event(conn, "login.password_ok", target_user_id=user["id"], email=address, ip=ip,
                                   detail={"next": stage, "user_agent": (user_agent or "")[:200]})
            if stage == "enroll" and not crypto.key_available():
                refusal = AuthError(503, "mfa_unavailable")
            else:
                result = _open_session(conn, user, stage=stage, ip=ip, user_agent=user_agent, mfa_verified=False)
    if refusal is not None:
        if refusal.code == "invalid_credentials":
            _failed(address, client)
        raise refusal
    assert result is not None
    throttle.BY_EMAIL.clear(address)
    log.info("auth.login", user_id=result[1].user_id, role=result[1].role, stage=result[1].stage)
    return result


def _failed(address: str, client: str) -> None:
    throttle.BY_EMAIL.fail(address)
    throttle.BY_CLIENT.fail(client)


def _staged_session(conn: psycopg.Connection[Any], principal: Principal, *stages: str) -> dict[str, Any]:
    s = store.session_for_update(conn, principal.session_id)
    if s is None:
        raise AuthError(401, "unauthenticated")
    if s["stage"] not in stages:
        raise AuthError(409, "wrong_stage")
    return s


def _wrong_code(conn: psycopg.Connection[Any], principal: Principal, *, kind: str, ip: str | None) -> AuthError:
    """Count a wrong code against the staged session AND the account; revoke the session when either is spent."""
    cfg = auth_settings()
    attempts = store.bump_mfa_attempts(conn, principal.session_id)
    counters = store.record_failure(conn, principal.user_id, threshold=cfg.lock_threshold,
                                    lock_minutes=cfg.lock_minutes, max_minutes=cfg.lock_max_minutes)
    store.record_event(conn, "mfa.failed", target_user_id=principal.user_id, email=principal.email, ip=ip,
                       detail={"kind": kind, "attempts": attempts, "streak": counters["failed_logins"]})
    if counters["is_locked"]:
        store.record_event(conn, "login.locked", target_user_id=principal.user_id, email=principal.email, ip=ip,
                           detail={"streak": counters["failed_logins"],
                                   "until": counters["locked_until"].isoformat()})
    if attempts >= cfg.mfa_max_attempts or counters["is_locked"]:
        if principal.stage != "full":
            store.revoke_session(conn, principal.session_id, "mfa_attempts_exhausted")
        return AuthError(429, "too_many_attempts", retry_after=_retry_after(counters["locked_until"]))
    return AuthError(401, "invalid_code", extra={"attempts_left": cfg.mfa_max_attempts - attempts})


def verify_mfa(principal: Principal, *, code: str | None, recovery_code: str | None, ip: str | None,
               user_agent: str | None) -> tuple[str, Principal]:
    """Second step of signing in: a code from the authenticator, or one of the recovery codes."""
    if not code and not recovery_code:
        raise AuthError(422, "code_missing")
    refusal: AuthError | None = None
    result: tuple[str, Principal] | None = None
    with write_connection() as conn:
        _staged_session(conn, principal, "mfa")
        user = store.user_by_id(conn, principal.user_id, for_update=True)
        if user is None or user["status"] != "active":
            raise AuthError(401, "unauthenticated")
        if user["is_locked"]:
            store.revoke_session(conn, principal.session_id, "locked")
            refusal = AuthError(429, "too_many_attempts", retry_after=_retry_after(user["locked_until"]))
        elif user["totp_secret"] is None:
            raise AuthError(409, "wrong_stage")
        else:
            try:
                secret = crypto.open_totp(principal.user_id, bytes(user["totp_secret"]))
            except crypto.KeyUnavailableError as exc:
                log.error("auth.mfa_key", error=str(exc))
                raise AuthError(503, "mfa_unavailable") from exc
            ok = False
            kind = "totp" if code else "recovery_code"
            if code:
                step = totp.matching_step(secret, code, last_step=user["totp_last_step"])
                ok = step is not None and store.accept_totp_step(conn, principal.user_id, step)
            elif recovery_code:
                ok = store.use_recovery_code(conn, principal.user_id,
                                             crypto.hash_recovery_code(principal.user_id, recovery_code))
            if not ok:
                refusal = _wrong_code(conn, principal, kind=kind, ip=ip)
            else:
                store.record_event(conn, "mfa.verified", actor_user_id=principal.user_id,
                                   target_user_id=principal.user_id, ip=ip, detail={"kind": kind})
                if kind == "recovery_code":
                    left = int(user["recovery_codes_left"]) - 1
                    store.record_event(conn, "mfa.recovery_code_used", actor_user_id=principal.user_id,
                                       target_user_id=principal.user_id, ip=ip, detail={"left": left})
                result = _advance(conn, principal.user_id, principal.session_id, mfa_done=True, ip=ip,
                                  user_agent=user_agent)
    if refusal is not None:
        raise refusal
    assert result is not None
    return result


def start_enrollment(principal: Principal, *, password: str | None, ip: str | None) -> Enrollment:
    """A new authenticator secret, kept on this session until a code proves the app has it. From a full session
    (enrolling voluntarily, or replacing a lost phone after a reset) the password is asked again."""
    if not crypto.key_available():
        raise AuthError(503, "mfa_unavailable")
    refusal: AuthError | None = None
    secret = totp.new_secret()
    with write_connection() as conn:
        _staged_session(conn, principal, "enroll", "full")
        user = store.user_by_id(conn, principal.user_id)
        if user is None:
            raise AuthError(401, "unauthenticated")
        if principal.stage == "full":
            if user["totp_enabled_at"] is not None:
                raise AuthError(409, "mfa_already_enabled")
            if not password or not passwords.verify_password(user["password_hash"], password):
                store.record_event(conn, "mfa.enroll_refused", actor_user_id=principal.user_id,
                                   target_user_id=principal.user_id, ip=ip, detail={"reason": "wrong_password"})
                refusal = AuthError(403, "wrong_password")
        if refusal is None:
            store.set_pending_secret(conn, principal.session_id, crypto.seal_totp(principal.user_id, secret))
            store.record_event(conn, "mfa.enroll_started", actor_user_id=principal.user_id,
                               target_user_id=principal.user_id, ip=ip)
    if refusal is not None:
        raise refusal
    issuer = auth_settings().mfa_issuer
    uri = totp.provisioning_uri(secret, account=principal.email, issuer=issuer)
    return Enrollment(secret=totp.grouped(totp.b32(secret)), otpauth_uri=uri, qr_svg=totp.qr_svg_data_uri(uri),
                      issuer=issuer, account=principal.email)


def _new_recovery_codes(conn: psycopg.Connection[Any], user_id: int) -> list[str]:
    codes = [crypto.new_recovery_code() for _ in range(auth_settings().recovery_codes)]
    store.replace_recovery_codes(conn, user_id, [crypto.hash_recovery_code(user_id, c) for c in codes])
    return codes


def confirm_enrollment(principal: Principal, *, code: str, ip: str | None,
                       user_agent: str | None) -> tuple[list[str], tuple[str, Principal] | None]:
    """The first code from the app turns the second factor on and returns the recovery codes - shown ONCE. A
    staged session moves to its next stage (a new token); a full one stays as it is."""
    refusal: AuthError | None = None
    codes: list[str] = []
    advanced: tuple[str, Principal] | None = None
    with write_connection() as conn:
        s = _staged_session(conn, principal, "enroll", "full")
        if s["pending_totp_secret"] is None:
            raise AuthError(409, "enrollment_not_started")
        try:
            secret = crypto.open_totp(principal.user_id, bytes(s["pending_totp_secret"]))
        except crypto.KeyUnavailableError as exc:
            raise AuthError(503, "mfa_unavailable") from exc
        step = totp.matching_step(secret, code, last_step=None)
        if step is None:
            refusal = _wrong_code(conn, principal, kind="enroll", ip=ip)
        else:
            store.set_totp(conn, principal.user_id, bytes(s["pending_totp_secret"]), step)
            store.set_pending_secret(conn, principal.session_id, None)
            codes = _new_recovery_codes(conn, principal.user_id)
            store.record_event(conn, "mfa.enrolled", actor_user_id=principal.user_id,
                               target_user_id=principal.user_id, ip=ip, detail={"recovery_codes": len(codes)})
            if principal.stage == "enroll":
                advanced = _advance(conn, principal.user_id, principal.session_id, mfa_done=True, ip=ip,
                                    user_agent=user_agent)
            else:
                # Every OTHER session of the account predates the second factor: end them.
                store.revoke_user_sessions(conn, principal.user_id, "second_factor_enabled",
                                           keep=principal.session_id)
    if refusal is not None:
        raise refusal
    return codes, advanced


def _check_password_and_code(conn: psycopg.Connection[Any], principal: Principal, user: dict[str, Any], *,
                             password: str, code: str | None, ip: str | None, action: str) -> AuthError | None:
    if not passwords.verify_password(user["password_hash"], password):
        store.record_event(conn, f"{action}_refused", actor_user_id=principal.user_id,
                           target_user_id=principal.user_id, ip=ip, detail={"reason": "wrong_password"})
        return AuthError(403, "wrong_password")
    if user["totp_secret"] is not None:
        try:
            secret = crypto.open_totp(principal.user_id, bytes(user["totp_secret"]))
        except crypto.KeyUnavailableError as exc:
            raise AuthError(503, "mfa_unavailable") from exc
        step = totp.matching_step(secret, code or "", last_step=user["totp_last_step"])
        if step is None or not store.accept_totp_step(conn, principal.user_id, step):
            return _wrong_code(conn, principal, kind=action, ip=ip)
    return None


def disable_mfa(principal: Principal, *, password: str, code: str | None, ip: str | None) -> None:
    refusal: AuthError | None = None
    with write_connection() as conn:
        user = store.user_by_id(conn, principal.user_id, for_update=True)
        if user is None:
            raise AuthError(401, "unauthenticated")
        if user["totp_enabled_at"] is None:
            raise AuthError(409, "mfa_not_enabled")
        if mfa_required_for(user):
            raise AuthError(409, "mfa_required_by_policy")
        refusal = _check_password_and_code(conn, principal, user, password=password, code=code, ip=ip,
                                           action="mfa.disable")
        if refusal is None:
            store.clear_totp(conn, principal.user_id)
            store.record_event(conn, "mfa.disabled", actor_user_id=principal.user_id,
                               target_user_id=principal.user_id, ip=ip)
    if refusal is not None:
        raise refusal


def regenerate_recovery_codes(principal: Principal, *, password: str, code: str | None,
                              ip: str | None) -> list[str]:
    refusal: AuthError | None = None
    codes: list[str] = []
    with write_connection() as conn:
        user = store.user_by_id(conn, principal.user_id, for_update=True)
        if user is None:
            raise AuthError(401, "unauthenticated")
        if user["totp_enabled_at"] is None:
            raise AuthError(409, "mfa_not_enabled")
        refusal = _check_password_and_code(conn, principal, user, password=password, code=code, ip=ip,
                                           action="mfa.recovery_codes")
        if refusal is None:
            codes = _new_recovery_codes(conn, principal.user_id)
            store.record_event(conn, "mfa.recovery_codes_renewed", actor_user_id=principal.user_id,
                               target_user_id=principal.user_id, ip=ip, detail={"count": len(codes)})
    if refusal is not None:
        raise refusal
    return codes


def principal_from_token(conn: psycopg.Connection[Any], token: str | None) -> Principal | None:
    """Who a cookie belongs to, on the request's read-only connection. None: nobody."""
    if not tokens.looks_like_token(token):
        return None
    assert token is not None
    cfg = session_settings()
    sid = tokens.token_id(token)
    row = store.session_principal(conn, sid, idle_hours=cfg.idle_hours, admin_idle_hours=cfg.admin_idle_hours,
                                  touch_minutes=cfg.touch_minutes)
    if row is None:
        return None
    if row["needs_touch"]:
        try:
            with write_connection() as wconn:
                store.touch_session(wconn, sid)
        except psycopg.Error as exc:  # a missed touch shortens nothing that matters
            log.warning("auth.touch_failed", error=exc.__class__.__name__)
    return _principal(row, sid, row["expires_at"], row["stage"])


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


def _new_password_problems(user: dict[str, Any], new_password: str) -> list[str]:
    problems = passwords.password_problems(new_password, email=user["email"])
    if not problems and passwords.verify_password(user["password_hash"], new_password):
        problems.append("password_reused")
    return problems


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
            problems = _new_password_problems(user, new_password)
            if problems:
                refusal = AuthError(422, "weak_password", problems=problems)
            else:
                store.update_user(conn, principal.user_id, {"password_hash": passwords.hash_password(new_password),
                                                            "must_change_password": False})
                revoked = store.revoke_user_sessions(conn, principal.user_id, "password_changed",
                                                     keep=principal.session_id)
                store.record_event(conn, "password.changed", actor_user_id=principal.user_id,
                                   target_user_id=principal.user_id, ip=ip,
                                   detail={"other_sessions_revoked": revoked})
    if refusal is not None:
        raise refusal


def set_required_password(principal: Principal, *, new_password: str, ip: str | None,
                          user_agent: str | None) -> tuple[str, Principal]:
    """The 'password' stage: the account was created or reset by an administrator and signs in once with that
    temporary password; it continues only with a password of its own."""
    refusal: AuthError | None = None
    result: tuple[str, Principal] | None = None
    with write_connection() as conn:
        _staged_session(conn, principal, "password")
        user = store.user_by_id(conn, principal.user_id, for_update=True)
        if user is None:
            raise AuthError(401, "unauthenticated")
        problems = _new_password_problems(user, new_password)
        if problems:
            refusal = AuthError(422, "weak_password", problems=problems)
        else:
            store.update_user(conn, principal.user_id, {"password_hash": passwords.hash_password(new_password),
                                                        "must_change_password": False})
            store.revoke_user_sessions(conn, principal.user_id, "password_changed", keep=principal.session_id)
            store.record_event(conn, "password.changed", actor_user_id=principal.user_id,
                               target_user_id=principal.user_id, ip=ip, detail={"reason": "required"})
            result = _advance(conn, principal.user_id, principal.session_id, mfa_done=True, ip=ip,
                              user_agent=user_agent)
    if refusal is not None:
        raise refusal
    assert result is not None
    return result


# ── one's own sessions and sign-in history ───────────────────────────────────────────

def my_sessions(conn: psycopg.Connection[Any], principal: Principal) -> list[dict[str, Any]]:
    rows = store.list_sessions(conn, principal.user_id)
    out = []
    for r in rows:
        current = r.pop("full_id") == principal.session_id
        out.append(r | {"current": current})
    return out


SESSION_PREFIX = re.compile(r"^[0-9a-f]{16}$")


def revoke_my_session(principal: Principal, session_prefix: str, *, ip: str | None) -> bool:
    """True when it was this browser's own session (the caller then clears the cookie)."""
    if not SESSION_PREFIX.match(session_prefix):
        raise AuthError(422, "invalid_session_id")
    with write_connection() as conn:
        n = store.revoke_user_session_by_prefix(conn, principal.user_id, session_prefix, "revoked_by_user")
        if n == 0:
            raise AuthError(404, "session_not_found")
        store.record_event(conn, "session.revoked", actor_user_id=principal.user_id,
                           target_user_id=principal.user_id, ip=ip, detail={"session": session_prefix})
    return principal.session_id.startswith(session_prefix)


def revoke_my_other_sessions(principal: Principal, *, ip: str | None) -> int:
    with write_connection() as conn:
        n = store.revoke_user_sessions(conn, principal.user_id, "revoked_by_user", keep=principal.session_id)
        store.record_event(conn, "session.revoked", actor_user_id=principal.user_id,
                           target_user_id=principal.user_id, ip=ip, detail={"others": n})
    return n


def my_access_history(conn: psycopg.Connection[Any], principal: Principal, *, limit: int) -> list[dict[str, Any]]:
    return store.access_history(conn, principal.user_id, limit=limit)


# ── accounts (Admin Console) ─────────────────────────────────────────────────────────

def list_users(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    return store.list_users(conn)


def create_user(actor: Principal, *, email: str, display_name: str | None, role: str, password: str,
                language: str = "es", timezone: str = "UTC", ip: str | None = None,
                must_change_password: bool = True, mfa_required: bool = False) -> dict[str, Any]:
    """An account created from the Admin Console signs in once with this password and then must choose its own
    (unless the owner says otherwise)."""
    row = _create_user(actor.user_id, email=email, display_name=display_name, role=role, password=password,
                       language=language, timezone=timezone, ip=ip, must_change_password=must_change_password)
    if mfa_required:
        with write_connection() as conn:
            updated = store.update_user(conn, int(row["id"]), {"mfa_required": True})
            assert updated is not None
            row = updated
    return row


def _create_user(actor_user_id: int | None, *, email: str, display_name: str | None, role: str, password: str,
                 language: str, timezone: str, ip: str | None, must_change_password: bool = False) -> dict[str, Any]:
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
                                language=language, timezone=timezone, must_change_password=must_change_password)
        store.record_event(conn, "user.created", actor_user_id=actor_user_id, target_user_id=row["id"],
                           email=address, ip=ip, detail={"role": role, "must_change_password": must_change_password})
    return row


def create_user_unattended(*, email: str, display_name: str | None, role: str, password: str,
                           language: str = "es", timezone: str = "UTC",
                           must_change_password: bool = False) -> dict[str, Any]:
    """For the operator's command line, where no one is signed in."""
    return _create_user(None, email=email, display_name=display_name, role=role, password=password,
                        language=language, timezone=timezone, ip=None, must_change_password=must_change_password)


def set_password_unattended(*, email: str, password: str, must_change: bool = False) -> dict[str, Any]:
    address = normalize_email(email)
    problems = passwords.password_problems(password, email=address)
    if problems:
        raise AuthError(422, "weak_password", problems=problems)
    with write_connection() as conn:
        user = store.user_by_email(conn, address)
        if user is None:
            raise AuthError(404, "user_not_found")
        row = store.update_user(conn, int(user["id"]), {"password_hash": passwords.hash_password(password),
                                                         "must_change_password": must_change})
        store.unlock(conn, int(user["id"]))
        store.revoke_user_sessions(conn, int(user["id"]), "password_reset")
        store.record_event(conn, "password.reset", target_user_id=user["id"], email=address,
                           detail={"by": "command_line", "must_change": must_change})
    assert row is not None
    return row


def _target(conn: psycopg.Connection[Any], user_id: int) -> dict[str, Any]:
    target = store.user_by_id(conn, user_id, for_update=True)
    if target is None:
        raise AuthError(404, "user_not_found")
    return target


def update_user(actor: Principal, user_id: int, *, role: str | None = None, status: str | None = None,
                mfa_required: bool | None = None, ip: str | None = None) -> dict[str, Any]:
    if role is not None and not is_role(role):
        raise AuthError(422, "invalid_role")
    if status is not None and status not in ("active", "disabled"):
        raise AuthError(422, "invalid_status")
    with write_connection() as conn:
        target = _target(conn, user_id)
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
        if mfa_required is not None and mfa_required != target["mfa_required"]:
            fields["mfa_required"] = mfa_required
        if not fields:
            return target
        row = store.update_user(conn, user_id, fields)
        assert row is not None
        if "role" in fields:
            store.record_event(conn, "user.role_changed", actor_user_id=actor.user_id, target_user_id=user_id,
                               ip=ip, detail={"from": target["role"], "to": fields["role"]})
            # New permissions apply to new sessions only: end the old ones.
            store.revoke_user_sessions(conn, user_id, "role_changed")
        if "status" in fields:
            store.record_event(conn, "user.status_changed", actor_user_id=actor.user_id, target_user_id=user_id,
                               ip=ip, detail={"from": target["status"], "to": fields["status"]})
            if fields["status"] == "disabled":
                store.revoke_user_sessions(conn, user_id, "account_disabled")
        if "mfa_required" in fields:
            store.record_event(conn, "user.mfa_requirement_changed", actor_user_id=actor.user_id,
                               target_user_id=user_id, ip=ip, detail={"required": fields["mfa_required"]})
            if fields["mfa_required"] and row["totp_enabled_at"] is None:
                store.revoke_user_sessions(conn, user_id, "mfa_required")
    return row


def admin_reset_password(actor: Principal, user_id: int, *, password: str | None,
                         ip: str | None) -> tuple[dict[str, Any], str | None]:
    """A temporary password (the owner's, or a generated one returned ONCE): the account must choose its own at the
    next sign-in. Unlocks it and ends its sessions."""
    generated = password is None
    temporary = crypto.new_temporary_password() if password is None else password
    with write_connection() as conn:
        target = _target(conn, user_id)
        problems = passwords.password_problems(temporary, email=target["email"])
        if problems:
            raise AuthError(422, "weak_password", problems=problems)
        row = store.update_user(conn, user_id, {"password_hash": passwords.hash_password(temporary),
                                                "must_change_password": True})
        store.unlock(conn, user_id)
        revoked = store.revoke_user_sessions(conn, user_id, "password_reset")
        store.record_event(conn, "password.reset", actor_user_id=actor.user_id, target_user_id=user_id, ip=ip,
                           detail={"by": "admin", "generated": generated, "sessions_revoked": revoked})
    assert row is not None
    return row, (temporary if generated else None)


def admin_reset_mfa(actor: Principal, user_id: int, *, ip: str | None) -> dict[str, Any]:
    """For a lost phone: the second factor and the recovery codes go; the account sets a new one up at its next
    sign-in when its role requires one. Ends its sessions."""
    with write_connection() as conn:
        _target(conn, user_id)
        store.clear_totp(conn, user_id)
        revoked = store.revoke_user_sessions(conn, user_id, "mfa_reset")
        store.record_event(conn, "mfa.reset", actor_user_id=actor.user_id, target_user_id=user_id, ip=ip,
                           detail={"sessions_revoked": revoked})
        row = store.user_by_id(conn, user_id)
    assert row is not None
    return row


def admin_unlock(actor: Principal, user_id: int, *, ip: str | None) -> dict[str, Any]:
    with write_connection() as conn:
        target = _target(conn, user_id)
        store.unlock(conn, user_id)
        store.record_event(conn, "user.unlocked", actor_user_id=actor.user_id, target_user_id=user_id, ip=ip,
                           detail={"streak": target["failed_logins"]})
        row = store.user_by_id(conn, user_id)
    assert row is not None
    return row


def admin_revoke_sessions(actor: Principal, user_id: int, *, ip: str | None) -> int:
    with write_connection() as conn:
        _target(conn, user_id)
        keep = actor.session_id if user_id == actor.user_id else None
        n = store.revoke_user_sessions(conn, user_id, "revoked_by_admin", keep=keep)
        store.record_event(conn, "session.revoked", actor_user_id=actor.user_id, target_user_id=user_id, ip=ip,
                           detail={"by": "admin", "count": n})
    return n


def admin_user_sessions(conn: psycopg.Connection[Any], user_id: int) -> list[dict[str, Any]]:
    rows = store.list_sessions(conn, user_id)
    return [{k: v for k, v in r.items() if k != "full_id"} | {"current": False} for r in rows]


def audit_events(conn: psycopg.Connection[Any], *, limit: int, offset: int, action: str | None,
                 target_user_id: int | None = None) -> tuple[list[dict[str, Any]], int]:
    return (store.list_events(conn, limit=limit, offset=offset, action=action, target_user_id=target_user_id),
            store.count_events(conn, action=action, target_user_id=target_user_id))


def record_admin_write(actor_user_id: int, *, method: str, path: str, status: int, ip: str | None,
                       request_id: str) -> None:
    """Every state-changing Admin Console request, whatever it changed: who, what, when and how it ended."""
    with write_connection() as conn:
        store.record_event(conn, "admin.write", actor_user_id=actor_user_id, ip=ip,
                           detail={"method": method, "path": path[:200], "status": status,
                                   "request_id": request_id})
