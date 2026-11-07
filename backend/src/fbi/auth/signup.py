"""A person opens their own account (tramo 1 of the user's flow, UX-038): registration, the e-mail's confirmation and a
new confirmation link.

What this is, and what it is not. Registering makes an account that is ``pending``: it cannot sign in, has no
membership, no trial and no access to anything. Confirming the address (a one-use link, 24 hours, and the password the
person chose) makes it ``active``. Neither step gives access to PrediGol: that is the owner's act, later (the payment
request, UX-037 onwards). Four things stay apart: registered, e-mail confirmed, payment requested, payment verified.

* **A switch with locks.** ``FBI_SIGNUP``, born off: off, these routes do not exist (404). On, it opens only if what
  must stand behind an open door stands: the e-mail works (``FBI_SELF_SERVICE``), the consent gate is on with no text
  in draft, and the membership is enforced - otherwise an account without a period would see everything. ``locks()``
  names what is missing; the sign-in page asks ``is_open()``.
* **The same answer whatever the address.** Registering answers 202 whether the address is new, awaits confirmation
  or already has an account: a new one is created and sent its link, one awaiting confirmation is sent a new link, and
  an active one is told by e-mail that it already has an account. The nickname is checked first, for every address, so
  that its refusal says nothing about addresses.
* **Consent at the point of collection.** The four required consents are ticked on the form, each with the version of
  the text shown; they are written in the same transaction as the account (source ``signup``), with the version, the
  sha256 and the sentence, or neither exists.
* **Limits.** Per client, five registrations an hour (in memory, a salted hash of the IP, as recovery does); per day,
  ``FBI_SIGNUP_DAILY_CAP`` new accounts (default 100) - the door pauses itself, it does not need the owner awake.
* **Unconfirmed accounts do not pile up.** After seven days an account that never confirmed is closed (its row stays,
  as the consents point at it): ``purge_unconfirmed``, born in ``dry`` (``FBI_SIGNUP_PURGE``), run by the messenger.
* **Only what is needed.** The mobile number is for the owner's records and is never used to send anything. The
  account's name and nickname are the only free text; the nickname is unique (the owner's decision of 7 Nov 2026).
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

import structlog

from fbi.auth import account_mail, passwords, store, throttle, tokens
from fbi.auth.db import write_connection
from fbi.auth.recovery import accept_link, client_key, link_invalid
from fbi.auth.service import (
    EMAIL_RE,
    LANGUAGES,
    AuthError,
    Principal,
    _count_failure,
    _lock_streak_of,
    _next_stage,
    _open_session,
    _wait,
    normalize_email,
    valid_timezone,
)
from fbi.auth.settings import auth_settings
from fbi.customer import consents, legal, membership
from fbi.customer.db import CustomerError
from fbi.messaging import outbox

log = structlog.get_logger("auth.signup")

SWITCH = "FBI_SIGNUP"
DAILY_CAP_ENV = "FBI_SIGNUP_DAILY_CAP"
DEFAULT_DAILY_CAP = 100
PURGE_ENV = "FBI_SIGNUP_PURGE"
UNCONFIRMED_DAYS = 7
"""An account that never confirmed its address is closed after this many days."""

SIGNUPS = throttle.FailureWindow(max_failures=5, window_s=3600)
"""Registrations one client may attempt in an hour, whatever the addresses (every attempt counts)."""

DEFAULT_TIMEZONE = "America/Bogota"
RESERVED_NICKNAMES = frozenset({
    "admin", "administrador", "administrator", "soporte", "support", "ayuda", "help", "predigol", "predigolai",
    "root", "owner", "dueno", "moderador", "moderator", "staff", "equipo", "team", "oficial", "official", "sistema",
    "system", "bot", "ia", "ai", "null", "undefined", "picks", "pronosticos", "tipster", "servicio", "service",
})
"""Nicknames nobody can take (compared without case, accents, spaces, dots or hyphens): they would pass for the house."""

NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\u2019\-][^\W\d_]+)*$")
NICKNAME_RE = re.compile(r"^\w[\w .\-]{1,22}\w$")
COLOMBIAN_MOBILE_RE = re.compile(r"^\+573[0-9]{9}$")
E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")

PurgeMode = Literal["dry", "on", "off"]


# ── the switch and its locks ──────────────────────────────────────────────────────────

def enabled() -> bool:
    """FBI_SIGNUP, born off."""
    return os.environ.get(SWITCH, "0").strip().lower() in ("1", "true", "yes", "on")


def locks() -> list[str]:
    """What must stand behind an open door and does not (closed list of codes; empty: nothing is missing)."""
    missing: list[str] = []
    if not tokens.self_service_enabled():
        missing.append("email_off")
    if consents.gate_mode() != "on" or not consents.gate_enabled():
        missing.append("consent_gate_not_final")
    if not membership.enforced():
        missing.append("membership_not_enforced")
    return missing


def is_open() -> bool:
    return enabled() and not locks()


def require_open() -> None:
    if not is_open():
        raise AuthError(404, "not_found")


def daily_cap() -> int:
    raw = os.environ.get(DAILY_CAP_ENV, "").strip()
    return int(raw) if raw.isdigit() and 1 <= int(raw) <= 10000 else DEFAULT_DAILY_CAP


def purge_mode() -> PurgeMode:
    raw = os.environ.get(PURGE_ENV, "dry").strip().lower()
    if raw in ("on", "1", "true", "yes"):
        return "on"
    return "off" if raw in ("off", "0", "false", "no") else "dry"


def reset_all() -> None:
    """The windows of this process (tests)."""
    with SIGNUPS._lock:
        SIGNUPS._hits.clear()


def consent_boxes(locale: legal.Locale) -> list[dict[str, Any]]:
    """The boxes the form shows - the required purposes, each with the sentence the server will store, the document
    it points at and the version in force. The optional ones (statistics, the weekly summary) are the profile's, offered
    once the person is in: a registration asks only for what it must."""
    boxes: list[dict[str, Any]] = []
    for purpose in legal.PURPOSES:
        if not purpose.required:
            continue
        doc, sentence = legal.statement(purpose.kind, locale)
        boxes.append({"kind": purpose.kind, "document": purpose.document, "version": doc.version,
                      "sha256": doc.sha256, "statement": sentence, "required": True,
                      "withdrawable": purpose.withdrawable, "changes": None})
    return boxes


# ── what a person types ───────────────────────────────────────────────────────────────

def clean_name(raw: str) -> str | None:
    name = " ".join(raw.split())
    return name if 1 <= len(name) <= 60 and NAME_RE.match(name) else None


def normalize_phone(raw: str) -> str | None:
    """E.164 from what a person types. Without a country code a Colombian mobile (10 digits starting with 3) is
    assumed - the beta is Colombian; a number that starts with ``+57`` must be a mobile. None when it is not a phone."""
    text = re.sub(r"[\s().\-]", "", raw)
    if text.startswith("00"):
        text = "+" + text[2:]
    if not text.startswith("+"):
        if not re.fullmatch(r"3[0-9]{9}", text):
            return None
        text = "+57" + text
    if text.startswith("+57"):
        return text if COLOMBIAN_MOBILE_RE.match(text) else None
    return text if E164_RE.match(text) else None


def _fold(text: str) -> str:
    import unicodedata

    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[\s.\-_]", "", plain).casefold()


def clean_nickname(raw: str) -> str | None:
    nick = raw.strip()
    if not NICKNAME_RE.match(nick) or "@" in nick or _fold(nick) in RESERVED_NICKNAMES:
        return None
    return nick


@dataclass(frozen=True, slots=True)
class Registration:
    first_name: str
    last_name: str
    email: str
    phone: str
    nickname: str
    password: str
    language: str
    timezone: str
    decisions: Sequence[consents.Decision]


def validate(*, first_name: str, last_name: str, email: str, phone: str, nickname: str, password: str,
             language: str, timezone: str, decisions: Sequence[consents.Decision]) -> Registration:
    """What the form sent, checked and cleaned; raises AuthError (422) naming the first thing wrong - a code the page
    translates. The password is judged last and against the address and the nickname."""
    first, last = clean_name(first_name), clean_name(last_name)
    if first is None:
        raise AuthError(422, "invalid_first_name")
    if last is None:
        raise AuthError(422, "invalid_last_name")
    address = normalize_email(email)
    if not EMAIL_RE.match(address) or len(address) > 254:
        raise AuthError(422, "invalid_email")
    number = normalize_phone(phone)
    if number is None:
        raise AuthError(422, "invalid_phone")
    nick = clean_nickname(nickname)
    if nick is None:
        raise AuthError(422, "invalid_nickname")
    if language not in LANGUAGES:
        raise AuthError(422, "invalid_language")
    zone = timezone or DEFAULT_TIMEZONE
    if not valid_timezone(zone):
        raise AuthError(422, "invalid_timezone")
    required = {p.kind for p in legal.PURPOSES if p.required}
    granted = {d.kind for d in decisions if d.granted}
    if not required <= granted:
        raise AuthError(422, "consents_required", extra={"missing": sorted(required - granted)})
    try:
        consents.check_decisions(decisions)
    except CustomerError as exc:
        raise AuthError(exc.status, exc.code) from exc
    problems = passwords.password_problems(password, email=address, name=nick)
    if problems:
        raise AuthError(422, "weak_password", problems=problems)
    return Registration(first, last, address, number, nick, password, language, zone, tuple(decisions))


# ── registering ───────────────────────────────────────────────────────────────────────

def accept_registration(ip: str | None) -> None:
    """Before a registration is looked at: the switch with its locks and the client's hourly cap. Every attempt
    counts, whatever the address."""
    require_open()
    key = client_key(ip)
    if SIGNUPS.blocked(key):
        raise AuthError(429, "too_many_attempts", retry_after=SIGNUPS.retry_after(key))
    SIGNUPS.fail(key)


def _today_count(conn: Any) -> int:
    row = conn.execute("SELECT count(*) FROM auth.users WHERE origin = 'signup' "
                       "AND created_at > now() - interval '24 hours'").fetchone()
    return int(row[0]) if row else 0


def register(data: Registration, *, ip: str | None) -> None:
    """A new pending account with its consents and its confirmation link, or - for an address that already has
    something - the quiet equivalent. Raises only for what the person can fix: ``display_name_taken`` and the pause."""
    require_open()
    hashed = passwords.hash_password(data.password)  # the same work whether or not the address exists
    with write_connection() as conn:
        store.lock_address(conn, data.email)
        if store.display_name_taken(conn, data.nickname):
            raise AuthError(409, "display_name_taken")
        existing = store.user_by_email(conn, data.email)
        if existing is None:
            if _today_count(conn) >= daily_cap():
                store.record_event(conn, "signup.paused", ip=ip, detail={"cap": daily_cap()})
                raise AuthError(503, "signup_paused", retry_after=3600)
            try:
                row = store.insert_user(conn, email=data.email, display_name=data.nickname, password_hash=hashed,
                                        role="USER", language=data.language, timezone=data.timezone,
                                        status="pending", origin="signup", first_name=data.first_name,
                                        last_name=data.last_name, phone_e164=data.phone)
            except store.DisplayNameTakenError:
                raise AuthError(409, "display_name_taken") from None
            user_id = int(row["id"])
            consents.write_decisions(conn, user_id, data.decisions, locale=cast(legal.Locale, data.language),
                                     source="signup")
            grant = tokens.issue(conn, user_id, "verify")
            assert grant is not None  # a new account has asked for nothing yet
            account_mail.enqueue_link(conn, user_id, "verify", grant)
            store.record_event(conn, "user.registered", actor_user_id=user_id, target_user_id=user_id,
                               email=data.email, ip=ip, detail={"language": data.language, "grant": grant})
        elif existing["status"] == "pending":
            _send_new_link(conn, existing, ip=ip)
        elif existing["status"] in ("active", "invited"):
            outbox.enqueue(conn, user_id=int(existing["id"]), template="account_exists", params={},
                           dedup_key=f"account_exists:{existing['id']}:{datetime.now(UTC):%Y%m%d}")
            store.record_event(conn, "signup.already_registered", target_user_id=existing["id"], ip=ip)
    log.info("auth.signup", ok=True)


def _send_new_link(conn: Any, user: dict[str, Any], *, ip: str | None) -> None:
    grant = tokens.issue(conn, int(user["id"]), "verify")
    if grant is None:
        store.record_event(conn, "account.link_capped", target_user_id=user["id"], ip=ip,
                           detail={"purpose": "verify"})
        return
    account_mail.enqueue_link(conn, int(user["id"]), "verify", grant)
    store.record_event(conn, "signup.link_resent", actor_user_id=user["id"], target_user_id=user["id"], ip=ip,
                       detail={"grant": grant})


def resend(email: str, *, ip: str | None) -> None:
    """After the answer has left: a new confirmation link for an address awaiting it, within its hourly cap. Never
    raises: nobody is waiting for it."""
    address = normalize_email(email)
    if not EMAIL_RE.match(address) or len(address) > 254:
        return
    try:
        with write_connection() as conn:
            user = store.user_by_email(conn, address)
            if user is None or user["status"] != "pending":
                return
            _send_new_link(conn, user, ip=ip)
    except Exception as exc:
        log.error("signup.resend_failed", error=exc.__class__.__name__)


# ── confirming ────────────────────────────────────────────────────────────────────────

def check(link: str, *, ip: str | None) -> dict[str, Any]:
    """Whether a confirmation link works: the address and nickname, for the page to show."""
    accept_link(ip)
    with write_connection() as conn:
        row = tokens.find(conn, link, "verify")
    if row is None:
        raise link_invalid(ip)
    return {k: row[k] for k in ("email", "display_name", "language")}


def confirm(link: str, *, password: str, ip: str | None, user_agent: str | None) -> tuple[str, Principal]:
    """The address is proven and the password is given again: the account becomes active and signed in. It has no
    membership: what it can see is decided by the membership's rules, not by this."""
    accept_link(ip)
    cfg = auth_settings()
    refusal: AuthError | None = None
    result: tuple[str, Principal] | None = None
    with write_connection() as conn:
        row = tokens.find(conn, link, "verify")
        if row is None:
            refusal = link_invalid(ip)
        else:
            user_id = int(row["user_id"])
            address = normalize_email(str(row["email"]))
            _lock_streak_of(conn, address)
            user = store.user_by_id(conn, user_id, for_update=True)
            assert user is not None
            state = store.address_streak(conn, address)
            wait = _wait(state, cfg)
            if wait:
                refusal = AuthError(429, "too_many_attempts", retry_after=wait)
            elif not passwords.verify_password(user["password_hash"], password):
                refusal = _count_failure(conn, state, cfg, address=address, user_id=user_id, ip=ip,
                                         action="login.failed", detail={"reason": "wrong_password", "for": "verify"})
            else:
                store.update_user(conn, user_id, {"status": "active"})
                conn.execute("UPDATE auth.users SET email_verified_at = now() WHERE id = %s", (user_id,))
                tokens.use(conn, int(row["token_id"]))
                tokens.revoke_open(conn, user_id, ("verify",), "superseded")
                store.record_event(conn, "user.email_verified", actor_user_id=user_id, target_user_id=user_id,
                                   email=address, ip=ip)
                fresh = store.user_by_id(conn, user_id)
                assert fresh is not None
                result = _open_session(conn, fresh, stage=_next_stage(fresh, mfa_done=False), ip=ip,
                                       user_agent=user_agent, mfa_verified=False)
    if refusal is not None:
        raise refusal
    assert result is not None
    log.info("auth.email_verified", user_id=result[1].user_id)
    return result


# ── closing what was never confirmed ──────────────────────────────────────────────────

def purge_unconfirmed(conn: Any, *, at: datetime, mode: PurgeMode | None = None) -> tuple[PurgeMode, int]:
    """Accounts that registered and never confirmed their address, past ``UNCONFIRMED_DAYS``: counted (``dry``, the
    default) or closed (``on``) - the row stays, with the address masked, the names and the mobile gone, the nickname
    released and a password nobody knows, as for any anonymised account; its consents stay (they point at it). The
    caller commits."""
    current = purge_mode() if mode is None else mode
    if current == "off":
        return current, 0
    before = at - timedelta(days=UNCONFIRMED_DAYS)
    ids = [int(r[0]) for r in conn.execute("SELECT id FROM auth.users WHERE status = 'pending' AND origin = 'signup' "
                                           "AND created_at < %s ORDER BY id", (before,)).fetchall()]
    if current == "dry" or not ids:
        return current, len(ids)
    for user_id in ids:
        tokens.revoke_open(conn, user_id, tuple(tokens.LIFETIME), "account_closed")
        conn.execute("UPDATE customer.messages_outbox SET status = 'suppressed', last_error = 'the account was closed', "
                     "updated_at = now() WHERE user_id = %s AND status = 'queued'", (user_id,))
        conn.execute("""
            UPDATE auth.users
               SET email = %s, display_name = %s, password_hash = %s, status = 'deleted', first_name = NULL,
                   last_name = NULL, phone_e164 = NULL, email_verified_at = NULL, updated_at = now()
             WHERE id = %s AND status = 'pending'
        """, (f"deleted-{user_id}@deleted.invalid", f"deleted-{user_id}", passwords.unusable_hash(), user_id))
        store.record_event(conn, "signup.unconfirmed_closed", target_user_id=user_id)
    return current, len(ids)
