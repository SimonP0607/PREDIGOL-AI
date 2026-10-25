"""Invitations (plan UX, A7): the owner invites a reader from the Admin Console - address, alias, language, time zone -
and the reader receives a one-use link, valid 7 days, that creates their password and signs them in.

An invited account exists from the invitation (status ``invited``) with a random password hash nobody knows: it
cannot sign in until it chooses its own on ``/activate``. Its consents are asked right after, by the same gate as
everyone's (plan UX, A4). A link that expired or was replaced can ask for a new one from its own page (the same answer
whatever happens, at most three an hour); the owner can resend it from the console, or - when e-mail cannot be used -
give the account a temporary password (``service.admin_reset_password``), the backup that stays.
"""

from __future__ import annotations

from typing import Any

import structlog

from fbi.auth import account_mail, crypto, passwords, store, tokens
from fbi.auth.db import write_connection
from fbi.auth.recovery import accept_link, link_invalid
from fbi.auth.service import (
    EMAIL_RE,
    LANGUAGES,
    AuthError,
    Principal,
    _next_stage,
    _open_session,
    normalize_email,
    valid_timezone,
)
from fbi.customer import events

log = structlog.get_logger("auth.invitations")


def _require_switch() -> None:
    if not tokens.self_service_enabled():
        raise AuthError(409, "self_service_off")


def invite(actor: Principal, *, email: str, display_name: str | None, language: str, timezone: str,
           ip: str | None) -> dict[str, Any]:
    """A new invited USER account and its invitation in the queue - one transaction."""
    _require_switch()
    address = normalize_email(email)
    if not EMAIL_RE.match(address) or len(address) > 254:
        raise AuthError(422, "invalid_email")
    if language not in LANGUAGES:
        raise AuthError(422, "invalid_language")
    if not valid_timezone(timezone):
        raise AuthError(422, "invalid_timezone")
    name = (display_name or address.split("@", 1)[0]).strip()[:80] or address
    with write_connection() as conn:
        if store.user_by_email(conn, address) is not None:
            raise AuthError(409, "email_taken")
        row = store.insert_user(conn, email=address, display_name=name, password_hash=passwords.unusable_hash(),
                                role="USER", language=language, timezone=timezone, status="invited")
        user_id = int(row["id"])
        grant = tokens.issue(conn, user_id, "invite")
        assert grant is not None  # a new account has asked for nothing yet
        account_mail.enqueue_link(conn, user_id, "invite", grant)
        store.record_event(conn, "user.invited", actor_user_id=actor.user_id, target_user_id=user_id, email=address,
                           ip=ip, detail={"language": language, "grant": grant})
    log.info("auth.invited", user_id=user_id)
    return row


def resend(actor: Principal, user_id: int, *, ip: str | None) -> dict[str, Any]:
    """A new invitation for an account still invited; the earlier link stops working."""
    _require_switch()
    refusal: AuthError | None = None
    with write_connection() as conn:
        target = store.user_by_id(conn, user_id, for_update=True)
        if target is None:
            raise AuthError(404, "user_not_found")
        if target["status"] != "invited":
            raise AuthError(409, "not_invited")
        grant = tokens.issue(conn, user_id, "invite")
        if grant is None:
            refusal = AuthError(429, "too_many_links", retry_after=3600)
        else:
            account_mail.enqueue_link(conn, user_id, "invite", grant)
            store.record_event(conn, "user.invitation_resent", actor_user_id=actor.user_id, target_user_id=user_id,
                               ip=ip, detail={"grant": grant})
    if refusal is not None:
        raise refusal
    return target


def check(link: str, *, ip: str | None) -> dict[str, Any]:
    """Whether an invitation link works: the account's address, alias, language and time zone, to fill the page (and
    for the system's password manager to save the new password under the address)."""
    accept_link(ip)
    with write_connection() as conn:
        row = tokens.find(conn, link, "invite")
    if row is None:
        raise link_invalid(ip)
    return {k: row[k] for k in ("email", "display_name", "language", "timezone")}


def activate(link: str, *, password: str, language: str, timezone: str, ip: str | None,
             user_agent: str | None) -> tuple[str, Principal]:
    """The account's own password, its language and time zone, once: the account becomes active and signed in (a
    session like any sign-in's). Its consents are asked next, by the gate."""
    accept_link(ip)
    if language not in LANGUAGES:
        raise AuthError(422, "invalid_language")
    if not valid_timezone(timezone):
        raise AuthError(422, "invalid_timezone")
    refusal: AuthError | None = None
    result: tuple[str, Principal] | None = None
    with write_connection() as conn:
        row = tokens.find(conn, link, "invite")
        if row is None:
            refusal = link_invalid(ip)
        else:
            user_id = int(row["user_id"])
            problems = passwords.password_problems(password, email=str(row["email"]), name=str(row["display_name"]))
            if problems:
                refusal = AuthError(422, "weak_password", problems=problems)
            else:
                store.update_user(conn, user_id, {"password_hash": passwords.hash_password(password),
                                                  "status": "active", "language": language, "timezone": timezone,
                                                  "must_change_password": False})
                tokens.use(conn, int(row["token_id"]))
                tokens.revoke_open(conn, user_id, ("invite",), "superseded")
                store.record_event(conn, "user.activated", actor_user_id=user_id, target_user_id=user_id,
                                   email=normalize_email(str(row["email"])), ip=ip,
                                   detail={"language": language})
                # The activation funnel's first step (plan UX, A6: a server event; recorded only as FBI_PRODUCT_EVENTS
                # allows, under the account's pseudonym).
                events.record_server(conn, user_id, "account_activated")
                user = store.user_by_id(conn, user_id)
                assert user is not None
                stage = _next_stage(user, mfa_done=False)  # "enroll" when the owner required a second factor
                if stage == "enroll" and not crypto.key_available():
                    refusal = AuthError(503, "mfa_unavailable")
                    conn.rollback()  # the link stays unused: the reader can come back once the key is there
                else:
                    result = _open_session(conn, user, stage=stage, ip=ip, user_agent=user_agent,
                                           mfa_verified=False)
    if refusal is not None:
        raise refusal
    assert result is not None
    log.info("auth.activated", user_id=result[1].user_id)
    return result


def renew(link: str, *, ip: str | None) -> None:
    """After the answer has left: a new invitation for the account of an invitation link that no longer works, while
    it is still invited, within its hourly cap. Never raises."""
    try:
        with write_connection() as conn:
            row = tokens.find_spent_invitation(conn, link)
            if row is None:
                return
            user_id = int(row["user_id"])
            grant = tokens.issue(conn, user_id, "invite")
            if grant is None:
                store.record_event(conn, "account.link_capped", target_user_id=user_id, ip=ip,
                                   detail={"purpose": "invite"})
                return
            account_mail.enqueue_link(conn, user_id, "invite", grant)
            store.record_event(conn, "user.invitation_renewed", actor_user_id=user_id, target_user_id=user_id,
                               ip=ip, detail={"grant": grant})
    except Exception as exc:
        log.error("invitations.renew_failed", error=exc.__class__.__name__)

