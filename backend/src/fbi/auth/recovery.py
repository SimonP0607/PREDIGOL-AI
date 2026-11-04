"""Getting back in without the owner (plan UX, A7): a new password chosen through a link sent by e-mail, and the
unlock of a locked account through another.

* Asking for a link always gets the same answer, at once, whether or not the address has an account and whether or
  not a link was sent: the work - looking the account up, issuing the link, queueing its e-mail - runs after the
  answer has left (the router's background task), so not even the time of the answer depends on the account.
* The limits: per account, three links of a kind an hour (fbi.auth.tokens.PER_HOUR, counted in the database); per
  client, a short-lived hash of its IP - salted with a random value of this process, so it means nothing outside it
  and dies with it - kept only in this process's memory, never in a table (plan UX, section 17).
* A link that does not work gets one answer (410 ``link_invalid``), whatever the reason; one client's failed links
  are capped too.
* A new password ends every session of the account and lifts its lock; the second factor stays as it was, and an
  account that has one gives a code from its app (or a recovery code) before the new password is taken (R25 of the
  security plan: the link alone, from a stolen mailbox, never changes the password of an account with a second
  factor). A wrong code counts like one at sign-in; a link takes five wrong codes, then stops working - three links an
  hour make at most fifteen guesses an hour, while the account's own owner, locked out by its wait, can still finish.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

import psycopg
import structlog

from fbi.auth import account_mail, crypto, passwords, store, throttle, tokens, totp
from fbi.auth.db import write_connection
from fbi.auth.service import (
    EMAIL_RE,
    AuthError,
    _lock_streak_of,
    _new_password_problems,
    _wait,
    normalize_email,
)
from fbi.auth.settings import auth_settings

log = structlog.get_logger("auth.recovery")

_SALT = secrets.token_bytes(16)
REQUESTS = throttle.FailureWindow(max_failures=10, window_s=3600)
"""Links one client may ask for in an hour, whatever the addresses (the accounts' own cap is in the database)."""
LINK_TRIES = throttle.FailureWindow(max_failures=20, window_s=900)
"""Links that did not work one client may present in 15 minutes."""


def client_key(ip: str | None) -> str:
    """A short-lived hash of a client's address: meaningless outside this process, forgotten with it."""
    return hashlib.sha256(_SALT + (ip or "unknown").encode()).hexdigest()[:24]


def require_self_service() -> None:
    """Off (FBI_SELF_SERVICE=0), these routes do not exist."""
    if not tokens.self_service_enabled():
        raise AuthError(404, "not_found")


def accept_request(ip: str | None) -> None:
    """Before a request for a link is accepted: the switch and the client's hourly cap - the same for every address,
    so neither tells anything about accounts."""
    require_self_service()
    key = client_key(ip)
    if REQUESTS.blocked(key):
        raise AuthError(429, "too_many_attempts", retry_after=REQUESTS.retry_after(key))
    REQUESTS.fail(key)


def accept_link(ip: str | None) -> None:
    """Before a link is looked at: the switch and the client's cap of links that did not work."""
    require_self_service()
    key = client_key(ip)
    if LINK_TRIES.blocked(key):
        raise AuthError(429, "too_many_attempts", retry_after=LINK_TRIES.retry_after(key))


def link_invalid(ip: str | None) -> AuthError:
    LINK_TRIES.fail(client_key(ip))
    return AuthError(410, "link_invalid")


def reset_all() -> None:
    """The windows of this process (tests)."""
    for window in (REQUESTS, LINK_TRIES):
        with window._lock:
            window._hits.clear()


def _address(email: str) -> str | None:
    address = normalize_email(email)
    return address if EMAIL_RE.match(address) and len(address) <= 254 else None


# ── a new password ────────────────────────────────────────────────────────────────────

def request_reset(email: str, *, ip: str | None) -> None:
    """After the answer has left: a reset link for an active account (an invited one gets a new invitation instead - it
    has no password to forget), within its hourly cap. Never raises: nobody is waiting for it."""
    address = _address(email)
    if address is None:
        return
    try:
        with write_connection() as conn:
            user = store.user_by_email(conn, address)
            if user is None or user["status"] not in ("active", "invited"):
                return
            purpose: tokens.Purpose = "invite" if user["status"] == "invited" else "reset"
            grant = tokens.issue(conn, int(user["id"]), purpose)
            if grant is None:
                store.record_event(conn, "account.link_capped", target_user_id=user["id"], ip=ip,
                                   detail={"purpose": purpose})
                return
            account_mail.enqueue_link(conn, int(user["id"]), purpose, grant)
            store.record_event(conn, "password.reset_requested" if purpose == "reset" else "user.invitation_renewed",
                               actor_user_id=user["id"], target_user_id=user["id"], ip=ip,
                               detail={"grant": grant})
    except Exception as exc:  # logged without the address: the reader already has their answer
        log.error("recovery.request_failed", kind="reset", error=exc.__class__.__name__)


def check_reset(link: str, *, ip: str | None) -> dict[str, Any]:
    """Whether a reset link works, for which address (the page shows it, and the system's password manager saves the
    new password under it) and whether a code of the second factor will be asked."""
    accept_link(ip)
    with write_connection() as conn:
        row = tokens.find(conn, link, "reset")
        user = store.user_by_id(conn, int(row["user_id"])) if row is not None else None
    if row is None or user is None:
        raise link_invalid(ip)
    return {"email": row["email"], "mfa": user["totp_enabled_at"] is not None}


CODES_PER_LINK = 5
"""Wrong codes of the second factor a reset link takes before it stops working."""


def _second_factor(conn: psycopg.Connection[Any], user: dict[str, Any], *, grant: int, code: str | None,
                   recovery_code: str | None, ip: str | None) -> AuthError | None:
    """The code an account with a second factor gives before its password is reset; None when it is right (or the
    account has none). A wrong one counts against the address's streak, as at sign-in, and against the link: its
    fifth wrong code ends it."""
    if user["totp_secret"] is None:
        return None
    user_id, address = int(user["id"]), normalize_email(str(user["email"]))
    cfg = auth_settings()
    if not code and not recovery_code:
        return AuthError(422, "code_missing")
    try:
        secret = crypto.open_totp(user_id, bytes(user["totp_secret"]))
    except crypto.KeyUnavailableError as exc:
        log.error("recovery.mfa_key", error=str(exc))
        return AuthError(503, "mfa_unavailable")
    if code:
        kind = "totp"
        step = totp.matching_step(secret, code, last_step=user["totp_last_step"])
        ok = step is not None and store.accept_totp_step(conn, user_id, step)
    else:
        kind = "recovery_code"
        ok = store.use_recovery_code(conn, user_id, crypto.hash_recovery_code(user_id, recovery_code or ""))
    if ok:
        store.record_event(conn, "mfa.verified", actor_user_id=user_id, target_user_id=user_id, ip=ip,
                           detail={"kind": kind, "for": "password_reset"})
        return None
    streak = int(store.address_streak(conn, address)["streak"]) + 1
    minutes = throttle.lock_minutes(streak, threshold=cfg.lock_threshold, minutes=cfg.lock_minutes,
                                    max_minutes=cfg.lock_max_minutes)
    store.record_event(conn, "mfa.failed", target_user_id=user_id, email=address, ip=ip,
                       detail={"kind": kind, "for": "password_reset", "grant": grant, "streak": streak})
    store.set_failures(conn, user_id, streak=streak, lock_minutes=minutes)
    if minutes:
        store.record_event(conn, "login.locked", target_user_id=user_id, email=address, ip=ip,
                           detail={"streak": streak, "minutes": minutes})
    row = conn.execute("SELECT count(*) FROM auth.audit_events WHERE action = 'mfa.failed' AND target_user_id = %s "
                       "AND detail->>'grant' = %s", (user_id, str(grant))).fetchone()
    wrong = int(row[0]) if row else 0
    if wrong >= CODES_PER_LINK:
        tokens.revoke(conn, grant, "too_many_codes")
        return link_invalid(ip)
    return AuthError(401, "invalid_code", extra={"attempts_left": CODES_PER_LINK - wrong})


def reset_password(link: str, new_password: str, *, code: str | None = None, recovery_code: str | None = None,
                   ip: str | None) -> None:
    """The new password, once: every session of the account ends, its lock is lifted, its other recovery and unlock
    links stop working and it is told by e-mail. The second factor is not touched - and, when there is one, its code
    comes first."""
    accept_link(ip)
    refusal: AuthError | None = None
    with write_connection() as conn:
        row = tokens.find(conn, link, "reset")
        if row is None:
            refusal = link_invalid(ip)
        else:
            user_id = int(row["user_id"])
            _lock_streak_of(conn, str(row["email"]))
            user = store.user_by_id(conn, user_id, for_update=True)
            assert user is not None
            problems = _new_password_problems(user, new_password)
            if problems:
                refusal = AuthError(422, "weak_password", problems=problems)
            else:
                refusal = _second_factor(conn, user, grant=int(row["token_id"]), code=code,
                                         recovery_code=recovery_code, ip=ip)
            if refusal is None:
                store.update_user(conn, user_id, {"password_hash": passwords.hash_password(new_password),
                                                  "must_change_password": False})
                store.unlock(conn, user_id)
                revoked = store.revoke_user_sessions(conn, user_id, "password_reset")
                tokens.use(conn, int(row["token_id"]))
                tokens.revoke_open(conn, user_id, ("reset", "unlock"), "password_changed")
                # With its address, as every row a sign-in streak is made of: it ends the streak.
                store.record_event(conn, "password.reset", actor_user_id=user_id, target_user_id=user_id,
                                   email=normalize_email(str(user["email"])), ip=ip,
                                   detail={"by": "link", "sessions_revoked": revoked})
                account_mail.notify_change(conn, user, "password_reset")
    if refusal is not None:
        raise refusal


# ── unlocking ─────────────────────────────────────────────────────────────────────────

def request_unlock(email: str, *, ip: str | None) -> None:
    """After the answer has left: an unlock link for an active account whose address is locked right now, within its
    hourly cap. Never raises."""
    address = _address(email)
    if address is None:
        return
    try:
        with write_connection() as conn:
            user = store.user_by_email(conn, address)
            if user is None or user["status"] != "active":
                return
            if not _wait(store.address_streak(conn, address), auth_settings()):
                return
            grant = tokens.issue(conn, int(user["id"]), "unlock")
            if grant is None:
                store.record_event(conn, "account.link_capped", target_user_id=user["id"], ip=ip,
                                   detail={"purpose": "unlock"})
                return
            account_mail.enqueue_link(conn, int(user["id"]), "unlock", grant)
            store.record_event(conn, "user.unlock_requested", actor_user_id=user["id"], target_user_id=user["id"],
                               ip=ip, detail={"grant": grant})
    except Exception as exc:
        log.error("recovery.request_failed", kind="unlock", error=exc.__class__.__name__)


def unlock(link: str, *, ip: str | None) -> None:
    """The lock is lifted, once: the address's streak ends as when the owner unlocks it."""
    accept_link(ip)
    refusal: AuthError | None = None
    with write_connection() as conn:
        row = tokens.find(conn, link, "unlock")
        if row is None:
            refusal = link_invalid(ip)
        else:
            user_id = int(row["user_id"])
            _lock_streak_of(conn, str(row["email"]))
            user = store.user_by_id(conn, user_id, for_update=True)
            assert user is not None
            store.unlock(conn, user_id)
            tokens.use(conn, int(row["token_id"]))
            store.record_event(conn, "user.unlocked", actor_user_id=user_id, target_user_id=user_id,
                               email=normalize_email(str(user["email"])), ip=ip,
                               detail={"by": "link", "streak": user["failed_logins"]})
    if refusal is not None:
        raise refusal
