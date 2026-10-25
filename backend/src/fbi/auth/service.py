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

from fbi.auth import account_mail, crypto, passwords, store, throttle, tokens, totp
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


def _who(principal: Principal) -> dict[str, Any]:
    """The account of a principal as the e-mails of an account need it (fbi.auth.account_mail)."""
    return {"id": principal.user_id, "email": principal.email}


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
        # A browser and system this account has not signed in with before: it is told (plan UX, A7).
        account_mail.notify_new_device(conn, user, session_id=str(session["id"]), user_agent=user_agent)
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
    cfg = auth_settings()
    refusal: AuthError | None = None
    result: tuple[str, Principal] | None = None
    counted = False
    # A refusal is recorded and COMMITTED before it is raised: raising inside the block would
    # roll the audit row (and the failure count) back with everything else.
    # The client's own window first: it is the same for every address, and costs no database work.
    if throttle.BY_CLIENT.blocked(client):
        raise AuthError(429, "too_many_attempts", retry_after=throttle.BY_CLIENT.retry_after(client))
    with write_connection() as conn:
        # The address first, by the same rule whether or not it has an account (R12; plan UX, A1): its streak is in
        # the database, read before the account is looked at - one decision at a time per address - so the answer
        # depends on the address alone, whichever API process answers, and after a restart. A refusal while locked
        # writes nothing: the attempts of a locked address cannot grow the trail.
        store.lock_address(conn, address)
        state = store.address_streak(conn, address)
        wait = _wait(state, cfg)
        if wait:
            refusal = AuthError(429, "too_many_attempts", retry_after=wait)
        else:
            user = store.user_by_email(conn, address) if EMAIL_RE.match(address) else None
            if user is None:
                passwords.burn_verification_time(password)
                refusal = _count_failure(conn, state, cfg, address=address, user_id=None, ip=ip,
                                         action="login.failed", detail={"reason": "unknown_email"})
                counted = True
            elif not passwords.verify_password(user["password_hash"], password):
                refusal = _count_failure(conn, state, cfg, address=address, user_id=int(user["id"]), ip=ip,
                                         action="login.failed", detail={"reason": "wrong_password"})
                counted = True
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
                    result = _open_session(conn, user, stage=stage, ip=ip, user_agent=user_agent,
                                           mfa_verified=False)
    if refusal is not None:
        if counted:
            throttle.BY_CLIENT.fail(client)
        raise refusal
    assert result is not None
    log.info("auth.login", user_id=result[1].user_id, role=result[1].role, stage=result[1].stage)
    return result


def _wait(state: dict[str, Any], cfg: Any) -> int:
    """Seconds the address of `state` (store.address_streak) must still wait; 0 when it may try."""
    return throttle.wait_seconds(state["streak"], state["last_at"], state["now"], threshold=cfg.lock_threshold,
                                 minutes=cfg.lock_minutes, max_minutes=cfg.lock_max_minutes)


def _count_failure(conn: psycopg.Connection[Any], state: dict[str, Any], cfg: Any, *, address: str,
                   user_id: int | None, ip: str | None, action: str, detail: dict[str, Any]) -> AuthError:
    """One more failure for the address (and its account, when it has one): recorded in the audit trail, where the
    next request - in any API process - reads the streak. The failure that reaches the threshold answers 429 with the
    real wait (plan UX, A1: until A1 it answered 401 and only the next attempt learned of the lock), for an address
    with or without an account alike."""
    streak = int(state["streak"]) + 1
    minutes = throttle.lock_minutes(streak, threshold=cfg.lock_threshold, minutes=cfg.lock_minutes,
                                    max_minutes=cfg.lock_max_minutes)
    store.record_event(conn, action, target_user_id=user_id, email=address, ip=ip, detail={**detail, "streak": streak})
    if user_id is not None:
        store.set_failures(conn, user_id, streak=streak, lock_minutes=minutes)
    if minutes:
        store.record_event(conn, "login.locked", target_user_id=user_id, email=address, ip=ip,
                           detail={"streak": streak, "minutes": minutes})
        return AuthError(429, "too_many_attempts", retry_after=minutes * 60)
    return AuthError(401, "invalid_credentials")


def _lock_streak_of(conn: psycopg.Connection[Any], email: str) -> None:
    """The lock of an address's sign-in streak (store.lock_address), taken FIRST by every transaction that reads or
    writes the streak or the account's lock: a sign-in holds it while it touches the account's row, so a transaction
    that locked the row first and asked for this lock after could deadlock with a sign-in in flight - PostgreSQL
    aborts one of them, and a wrong code aborted that way is never counted (third review of A1). Taking it twice in a
    transaction is harmless."""
    store.lock_address(conn, normalize_email(email))


def _staged_session(conn: psycopg.Connection[Any], principal: Principal, *stages: str) -> dict[str, Any]:
    s = store.session_for_update(conn, principal.session_id)
    if s is None:
        raise AuthError(401, "unauthenticated")
    if s["stage"] not in stages:
        raise AuthError(409, "wrong_stage")
    return s


def _wrong_code(conn: psycopg.Connection[Any], principal: Principal, *, kind: str, ip: str | None) -> AuthError:
    """Count a wrong code against the staged session AND the account's streak (the same one a wrong password adds
    to: store.address_streak); revoke the session when either is spent."""
    cfg = auth_settings()
    address = normalize_email(principal.email)
    store.lock_address(conn, address)  # already held: every caller takes it first (_lock_streak_of)
    attempts = store.bump_mfa_attempts(conn, principal.session_id)
    streak = int(store.address_streak(conn, address)["streak"]) + 1
    minutes = throttle.lock_minutes(streak, threshold=cfg.lock_threshold, minutes=cfg.lock_minutes,
                                    max_minutes=cfg.lock_max_minutes)
    counters = store.set_failures(conn, principal.user_id, streak=streak, lock_minutes=minutes)
    store.record_event(conn, "mfa.failed", target_user_id=principal.user_id, email=address, ip=ip,
                       detail={"kind": kind, "attempts": attempts, "streak": streak})
    if minutes:
        store.record_event(conn, "login.locked", target_user_id=principal.user_id, email=address, ip=ip,
                           detail={"streak": streak, "minutes": minutes})
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
        _lock_streak_of(conn, principal.email)
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
        _lock_streak_of(conn, principal.email)
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
            account_mail.notify_change(conn, _who(principal), "mfa_on")
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
        _lock_streak_of(conn, principal.email)
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
            account_mail.notify_change(conn, _who(principal), "mfa_off")
    if refusal is not None:
        raise refusal


def regenerate_recovery_codes(principal: Principal, *, password: str, code: str | None,
                              ip: str | None) -> list[str]:
    refusal: AuthError | None = None
    codes: list[str] = []
    with write_connection() as conn:
        _lock_streak_of(conn, principal.email)
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
            account_mail.notify_change(conn, _who(principal), "recovery_codes")
    if refusal is not None:
        raise refusal
    return codes


def reauthenticate(principal: Principal, *, password: str, code: str | None, ip: str | None, action: str,
                   per_day: int | None = None) -> None:
    """The account's own password once more - and its second factor's code when it has one - before an action that
    hands over or ends the account's data (plan UX, A4: the export and the deletion request; plan de seguridad, S5).
    A wrong password or code counts like one at sign-in. ``per_day`` caps how often the action runs in 24 hours
    (counted in the audit trail, so the two API processes share it). The action is recorded under its own name."""
    refusal: AuthError | None = None
    with write_connection() as conn:
        _lock_streak_of(conn, principal.email)
        user = store.user_by_id(conn, principal.user_id, for_update=True)
        if user is None or user.get("status") != "active":
            raise AuthError(401, "unauthenticated")
        if per_day is not None:
            row = conn.execute("SELECT count(*) FROM auth.audit_events WHERE action = %s AND target_user_id = %s "
                               "AND at > now() - interval '24 hours'", (action, principal.user_id)).fetchone()
            if row is not None and int(row[0]) >= per_day:
                raise AuthError(429, "daily_limit", retry_after=3600)
        refusal = _check_password_and_code(conn, principal, user, password=password, code=code, ip=ip,
                                           action=action)
        if refusal is None:
            store.record_event(conn, action, actor_user_id=principal.user_id, target_user_id=principal.user_id,
                               ip=ip)
    if refusal is not None:
        raise refusal


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
    """The one rule (fbi.auth.passwords, R11), for this account: its address and name, its second factor (12
    characters instead of 15), and never the password it has now."""
    problems = passwords.password_problems(new_password, email=user["email"], name=user.get("display_name"),
                                           has_mfa=user.get("totp_enabled_at") is not None)
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
                # A recovery or unlock link asked for before the change no longer works (plan UX, A7).
                tokens.revoke_open(conn, principal.user_id, ("reset", "unlock"), "password_changed")
                store.record_event(conn, "password.changed", actor_user_id=principal.user_id,
                                   target_user_id=principal.user_id, ip=ip,
                                   detail={"other_sessions_revoked": revoked})
                account_mail.notify_change(conn, user, "password")
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
            tokens.revoke_open(conn, principal.user_id, ("reset", "unlock"), "password_changed")
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
    cfg = session_settings()
    rows = store.list_sessions(conn, principal.user_id, idle_hours=cfg.idle_hours,
                               admin_idle_hours=cfg.admin_idle_hours)
    out = []
    for r in rows:
        current = r.pop("full_id") == principal.session_id
        out.append(r | {"current": current})
    return out


SESSION_PREFIX = re.compile(r"^[0-9a-f]{16}$")


def _confirm_identity(conn: psycopg.Connection[Any], principal: Principal, *, password: str | None,
                      code: str | None, ip: str | None, action: str) -> AuthError | None:
    """The account's password, or a code of its second factor - either is enough (ASVS 7.5.2; R25 of the security
    plan): ending the other sessions of an account must not be one stolen session's to do. None when it holds; a wrong
    password is recorded, a wrong code counts like one at sign-in."""
    user = store.user_by_id(conn, principal.user_id, for_update=True)
    if user is None or user["status"] != "active":
        return AuthError(401, "unauthenticated")
    if password:
        if passwords.verify_password(user["password_hash"], password):
            return None
        store.record_event(conn, f"{action}_refused", actor_user_id=principal.user_id,
                           target_user_id=principal.user_id, ip=ip, detail={"reason": "wrong_password"})
        return AuthError(403, "wrong_password")
    if code and user["totp_secret"] is not None:
        try:
            secret = crypto.open_totp(principal.user_id, bytes(user["totp_secret"]))
        except crypto.KeyUnavailableError:
            return AuthError(503, "mfa_unavailable")
        step = totp.matching_step(secret, code, last_step=user["totp_last_step"])
        if step is not None and store.accept_totp_step(conn, principal.user_id, step):
            return None
        return _wrong_code(conn, principal, kind=action, ip=ip)
    return AuthError(422, "identity_required")


def revoke_my_session(principal: Principal, session_prefix: str, *, ip: str | None, password: str | None = None,
                      code: str | None = None) -> bool:
    """True when it was this browser's own session (the caller then clears the cookie): that one is signing out and
    asks for nothing; another one asks for the password or a code (``_confirm_identity``)."""
    if not SESSION_PREFIX.match(session_prefix):
        raise AuthError(422, "invalid_session_id")
    own = principal.session_id.startswith(session_prefix)
    refusal: AuthError | None = None
    with write_connection() as conn:
        _lock_streak_of(conn, principal.email)
        if not own:
            refusal = _confirm_identity(conn, principal, password=password, code=code, ip=ip, action="session.revoke")
        if refusal is None:
            n = store.revoke_user_session_by_prefix(conn, principal.user_id, session_prefix, "revoked_by_user")
            if n == 0:
                raise AuthError(404, "session_not_found")
            store.record_event(conn, "session.revoked", actor_user_id=principal.user_id,
                               target_user_id=principal.user_id, ip=ip, detail={"session": session_prefix})
    if refusal is not None:
        raise refusal
    return own


def revoke_my_other_sessions(principal: Principal, *, ip: str | None, password: str | None = None,
                             code: str | None = None) -> int:
    """Every other session of the account ends, once the password or a code confirms who asks."""
    refusal: AuthError | None = None
    n = 0
    with write_connection() as conn:
        _lock_streak_of(conn, principal.email)
        refusal = _confirm_identity(conn, principal, password=password, code=code, ip=ip, action="session.revoke")
        if refusal is None:
            n = store.revoke_user_sessions(conn, principal.user_id, "revoked_by_user", keep=principal.session_id)
            store.record_event(conn, "session.revoked", actor_user_id=principal.user_id,
                               target_user_id=principal.user_id, ip=ip, detail={"others": n})
    if refusal is not None:
        raise refusal
    return n


def my_access_history(conn: psycopg.Connection[Any], principal: Principal, *, limit: int) -> list[dict[str, Any]]:
    return store.access_history(conn, principal.user_id, limit=limit)


# ── accounts (Admin Console) ─────────────────────────────────────────────────────────

def list_users(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    cfg = session_settings()
    return store.list_users(conn, idle_hours=cfg.idle_hours, admin_idle_hours=cfg.admin_idle_hours)


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
    name = (display_name or address.split("@", 1)[0]).strip()[:80] or address
    problems = passwords.password_problems(password, email=address, name=name)
    if problems:
        raise AuthError(422, "weak_password", problems=problems)
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
    """The operator's backup (plan UX, A7: the temporary password stays as the way when an e-mail cannot be used): an
    invited account it gives a password to becomes active and its invitation links stop working."""
    address = normalize_email(email)
    with write_connection() as conn:
        _lock_streak_of(conn, address)
        user = store.user_by_email(conn, address)
        if user is None:
            raise AuthError(404, "user_not_found")
        if user["status"] == "deleted":
            raise AuthError(409, "account_deleted")
        problems = passwords.password_problems(password, email=address, name=user["display_name"],
                                               has_mfa=user["totp_enabled_at"] is not None)
        if problems:
            raise AuthError(422, "weak_password", problems=problems)
        fields: dict[str, Any] = {"password_hash": passwords.hash_password(password),
                                  "must_change_password": must_change}
        if user["status"] == "invited":
            fields["status"] = "active"
            tokens.revoke_open(conn, int(user["id"]), ("invite",), "superseded")
        row = store.update_user(conn, int(user["id"]), fields)
        store.unlock(conn, int(user["id"]))
        store.revoke_user_sessions(conn, int(user["id"]), "password_reset")
        tokens.revoke_open(conn, int(user["id"]), ("reset", "unlock"), "password_changed")
        store.record_event(conn, "password.reset", target_user_id=user["id"], email=address,
                           detail={"by": "command_line", "must_change": must_change,
                                   "activated": user["status"] == "invited"})
    assert row is not None
    return row


def _target(conn: psycopg.Connection[Any], user_id: int) -> dict[str, Any]:
    target = store.user_by_id(conn, user_id, for_update=True)
    if target is None:
        raise AuthError(404, "user_not_found")
    if target["status"] == "deleted":
        raise AuthError(409, "account_deleted")  # anonymised (plan UX, A7): nothing about it changes any more
    return target


def _streak_target(conn: psycopg.Connection[Any], user_id: int) -> dict[str, Any]:
    """The account an action that ends its sign-in streak works on (an unlock, a password reset): the lock of its
    address first, then its row - the order of a sign-in, so the action waits for a failure in flight instead of
    being undone by it (third review of A1: a failure that read the streak before an unlock and wrote after it locked
    the account again)."""
    found = store.user_by_id(conn, user_id)
    if found is None:
        raise AuthError(404, "user_not_found")
    _lock_streak_of(conn, str(found["email"]))
    return _target(conn, user_id)


def update_user(actor: Principal, user_id: int, *, role: str | None = None, status: str | None = None,
                mfa_required: bool | None = None, ip: str | None = None) -> dict[str, Any]:
    if role is not None and not is_role(role):
        raise AuthError(422, "invalid_role")
    if status is not None and status not in ("active", "disabled"):
        raise AuthError(422, "invalid_status")
    with write_connection() as conn:
        target = _target(conn, user_id)
        if target["status"] == "invited" and (
                (role is not None and role != target["role"]) or (status is not None and status != target["status"])):
            # An invitation is resent, given a temporary password or withdrawn (anonymised) - plan UX, A7.
            raise AuthError(409, "account_invited")
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
    next sign-in. Unlocks it and ends its sessions. An invited account becomes active with it - the backup when the
    invitation's e-mail cannot be used (plan UX, A7) - and its invitation links stop working."""
    generated = password is None
    temporary = crypto.new_temporary_password() if password is None else password
    with write_connection() as conn:
        target = _streak_target(conn, user_id)
        problems = passwords.password_problems(temporary, email=target["email"], name=target["display_name"],
                                               has_mfa=target["totp_enabled_at"] is not None)
        if problems:
            raise AuthError(422, "weak_password", problems=problems)
        invited = target["status"] == "invited"
        fields: dict[str, Any] = {"password_hash": passwords.hash_password(temporary), "must_change_password": True}
        if invited:
            fields["status"] = "active"
            tokens.revoke_open(conn, user_id, ("invite",), "superseded")
        row = store.update_user(conn, user_id, fields)
        store.unlock(conn, user_id)
        revoked = store.revoke_user_sessions(conn, user_id, "password_reset")
        tokens.revoke_open(conn, user_id, ("reset", "unlock"), "password_changed")
        store.record_event(conn, "password.reset", actor_user_id=actor.user_id, target_user_id=user_id,
                           email=normalize_email(str(target["email"])), ip=ip,
                           detail={"by": "admin", "generated": generated, "sessions_revoked": revoked,
                                   "activated": invited})
        if not invited:
            account_mail.notify_change(conn, target, "password_admin")
    assert row is not None
    return row, (temporary if generated else None)


def admin_reset_mfa(actor: Principal, user_id: int, *, ip: str | None) -> dict[str, Any]:
    """For a lost phone: the second factor and the recovery codes go; the account sets a new one up at its next
    sign-in when its role requires one. Ends its sessions."""
    with write_connection() as conn:
        target = _target(conn, user_id)
        had = target["totp_enabled_at"] is not None
        store.clear_totp(conn, user_id)
        revoked = store.revoke_user_sessions(conn, user_id, "mfa_reset")
        store.record_event(conn, "mfa.reset", actor_user_id=actor.user_id, target_user_id=user_id, ip=ip,
                           detail={"sessions_revoked": revoked})
        if had:
            account_mail.notify_change(conn, target, "mfa_reset")
        row = store.user_by_id(conn, user_id)
    assert row is not None
    return row


def admin_unlock(actor: Principal, user_id: int, *, ip: str | None) -> dict[str, Any]:
    with write_connection() as conn:
        target = _streak_target(conn, user_id)
        store.unlock(conn, user_id)
        # With its address, as every row a streak is made of: store.address_streak reads them by address.
        store.record_event(conn, "user.unlocked", actor_user_id=actor.user_id, target_user_id=user_id,
                           email=normalize_email(str(target["email"])), ip=ip,
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
    cfg = session_settings()
    rows = store.list_sessions(conn, user_id, idle_hours=cfg.idle_hours,
                               admin_idle_hours=cfg.admin_idle_hours)
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
