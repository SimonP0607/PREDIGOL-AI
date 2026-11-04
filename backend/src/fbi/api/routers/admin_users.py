"""Accounts and the sign-in audit trail - SUPER_ADMIN only.

There is no public registration: every account is created here (or with scripts/create_user.py). From A7 (plan UX),
while FBI_SELF_SERVICE is on, the way in is an invitation: the reader receives a one-use link and chooses their own
password. The temporary password stays as the backup: a new account signs in once with the password the owner gives
it and must then choose its own. An account is deleted only as anonymisation, with its address typed again.
"""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query, Request

from fbi.api.contracts.auth import (
    AdminAnonymised,
    AdminAnonymiseIn,
    AdminInviteIn,
    AdminPasswordReset,
    AdminPasswordResult,
    AdminUser,
    AdminUserCreate,
    AdminUserPatch,
    AuditEvent,
    SelfServiceState,
    SessionInfo,
)
from fbi.api.contracts.membership import MembershipSummary
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, listing, ok
from fbi.api.security import UsersAdmin, client_ip, same_site_only
from fbi.auth import anonymize, invitations, service, tokens
from fbi.customer import membership
from fbi.messaging import outbox

router = APIRouter(tags=["admin: users"], dependencies=[Depends(same_site_only)])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]
UserId = Annotated[int, Path(ge=1)]


def _user(row: dict[str, Any], member: membership.Membership | None = None) -> AdminUser:
    found = membership.summary(member) if member is not None else None
    return AdminUser(
        id=int(row["id"]), email=row["email"], display_name=row["display_name"], role=row["role"],
        status=row["status"], language=row["language"], timezone=row["timezone"], created_at=row["created_at"],
        last_login_at=row["last_login_at"], active_sessions=int(row.get("active_sessions") or 0),
        mfa_enabled=row.get("totp_enabled_at") is not None, mfa_required=service.mfa_required_for(row),
        must_change_password=bool(row.get("must_change_password")),
        locked_until=row["locked_until"] if row.get("is_locked") else None,
        failed_logins=int(row.get("failed_logins") or 0),
        recovery_codes_left=int(row.get("recovery_codes_left") or 0),
        membership=MembershipSummary(**found) if found is not None else None,
    )


@router.get("/users", response_model=Envelope[list[AdminUser]])
def list_users(conn: Db, _: UsersAdmin) -> Envelope[list[AdminUser]]:
    rows = service.list_users(conn)
    members = membership.of_many(conn, rows)  # plan UX, A8: every account's membership in two queries
    return listing([_user(r, members.get(int(r["id"]))) for r in rows], empty_reason="No account exists yet.")


@router.post("/users", response_model=Envelope[AdminUser], status_code=201)
def create_user(body: AdminUserCreate, request: Request, actor: UsersAdmin) -> Envelope[AdminUser]:
    row = service.create_user(actor, email=body.email, display_name=body.display_name, role=body.role,
                              password=body.password, language=body.language, timezone=body.timezone,
                              ip=client_ip(request), must_change_password=body.must_change_password,
                              mfa_required=body.mfa_required)
    if row["role"] == "USER":
        # A reader's account created with a temporary password (the backup to an invitation) starts its trial now
        # (plan UX, A8): it has no activation of its own.
        membership.start_trial_for(int(row["id"]), actor=actor.user_id)
    return ok(_user(row))


@router.get("/users/self-service", response_model=SelfServiceState)
def self_service_state(_: UsersAdmin) -> SelfServiceState:
    """Whether invitations can be sent, and whether their e-mails leave now or wait in the queue."""
    return SelfServiceState(self_service=tokens.self_service_enabled(), email_sending=outbox.sending_enabled())


@router.post("/users/invite", response_model=Envelope[AdminUser], status_code=201)
def invite_user(body: AdminInviteIn, request: Request, actor: UsersAdmin) -> Envelope[AdminUser]:
    """An invited USER account and an e-mail with a one-use link, valid 7 days (409 ``self_service_off`` while
    FBI_SELF_SERVICE is off: then the account is created with a temporary password)."""
    row = invitations.invite(actor, email=body.email, display_name=body.display_name, language=body.language,
                             timezone=body.timezone, ip=client_ip(request), trial_days=body.trial_days)
    return ok(_user(row))


@router.post("/users/{user_id}/invitation", response_model=Envelope[AdminUser])
def resend_invitation(request: Request, actor: UsersAdmin, user_id: UserId) -> Envelope[AdminUser]:
    """A new link for an account still invited; the previous one stops working (at most three an hour)."""
    return ok(_user(invitations.resend(actor, user_id, ip=client_ip(request))))


@router.post("/users/{user_id}/anonymise", response_model=Envelope[AdminAnonymised])
def anonymise_user(body: AdminAnonymiseIn, request: Request, actor: UsersAdmin,
                   user_id: UserId) -> Envelope[AdminAnonymised]:
    """The deletion of an account as anonymisation (fbi.auth.anonymize), with its address typed again (422
    ``confirmation_mismatch`` otherwise). Not the owner's own account, nor a SUPER_ADMIN's. Cannot be undone."""
    done = anonymize.anonymise(actor, user_id, confirm=body.confirm, ip=client_ip(request))
    return ok(AdminAnonymised(user=_user(done.user), picks=done.picks, parlays=done.parlays, sessions=done.sessions,
                              messages_dropped=done.messages_dropped, trail_rows=done.trail_rows))


@router.patch("/users/{user_id}", response_model=Envelope[AdminUser])
def update_user(body: AdminUserPatch, request: Request, actor: UsersAdmin, user_id: UserId) -> Envelope[AdminUser]:
    row = service.update_user(actor, user_id, role=body.role, status=body.status, mfa_required=body.mfa_required,
                              ip=client_ip(request))
    return ok(_user(row))


@router.post("/users/{user_id}/password", response_model=Envelope[AdminPasswordResult])
def reset_password(body: AdminPasswordReset, request: Request, actor: UsersAdmin,
                   user_id: UserId) -> Envelope[AdminPasswordResult]:
    """Controlled recovery: a temporary password (given, or generated and shown once). The account must replace it
    at its next sign-in; its sessions end and a lock is lifted."""
    row, temporary = service.admin_reset_password(actor, user_id, password=body.password or None,
                                                  ip=client_ip(request))
    return ok(AdminPasswordResult(user=_user(row), temporary_password=temporary))


@router.post("/users/{user_id}/mfa/reset", response_model=Envelope[AdminUser])
def reset_mfa(request: Request, actor: UsersAdmin, user_id: UserId) -> Envelope[AdminUser]:
    """A lost phone: the second factor and its recovery codes are removed and the sessions end. An account whose role
    requires a second factor sets a new one up at its next sign-in."""
    return ok(_user(service.admin_reset_mfa(actor, user_id, ip=client_ip(request))))


@router.post("/users/{user_id}/unlock", response_model=Envelope[AdminUser])
def unlock(request: Request, actor: UsersAdmin, user_id: UserId) -> Envelope[AdminUser]:
    return ok(_user(service.admin_unlock(actor, user_id, ip=client_ip(request))))


@router.post("/users/{user_id}/sessions/revoke", response_model=Envelope[dict[str, int]])
def revoke_sessions(request: Request, actor: UsersAdmin, user_id: UserId) -> Envelope[dict[str, int]]:
    return ok({"revoked": service.admin_revoke_sessions(actor, user_id, ip=client_ip(request))})


@router.get("/users/{user_id}/sessions", response_model=Envelope[list[SessionInfo]])
def user_sessions(conn: Db, _: UsersAdmin, user_id: UserId) -> Envelope[list[SessionInfo]]:
    rows = [SessionInfo(**r) for r in service.admin_user_sessions(conn, user_id)]
    return listing(rows, empty_reason="No open session.")


@router.get("/audit", response_model=Envelope[list[AuditEvent]])
def audit(
    conn: Db,
    _: UsersAdmin,
    action: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z][a-z_.]+$")] = None,
    user_id: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Envelope[list[AuditEvent]]:
    rows, total = service.audit_events(conn, limit=limit, offset=offset, action=action, target_user_id=user_id)
    events = [AuditEvent(**r) for r in rows]
    return listing(events, empty_reason="Nothing has been recorded yet.", total=total, limit=limit, offset=offset)
