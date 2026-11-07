"""Sign in (password, second factor, enrolment, required new password), sign out, who am I, my preferences, my
security: sessions, sign-in history, the second factor and its recovery codes."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query, Request, Response

from fbi.api.contracts.auth import (
    AccessEvent,
    IdentityIn,
    LoginIn,
    Me,
    MfaCodeIn,
    MfaEnrolled,
    MfaEnrollment,
    MfaGuardedIn,
    MfaStartIn,
    MfaVerifyIn,
    PasswordChangeIn,
    PreferencesIn,
    RecoveryCodes,
    RequiredPasswordIn,
    SessionInfo,
)
from fbi.api.contracts.guides import GuideState
from fbi.api.contracts.membership import MembershipSummary
from fbi.api.deps import get_db
from fbi.api.security import (
    AnySession,
    App,
    clear_session_cookie,
    client_ip,
    optional_principal,
    same_site_only,
    set_session_cookie,
)
from fbi.api.switches import explain_on, transparency_open
from fbi.auth import crypto, service
from fbi.auth.roles import Role
from fbi.auth.service import Principal
from fbi.auth.settings import session_settings
from fbi.core.clock import now
from fbi.customer import consents, favorites, guides, membership, support

public_router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(same_site_only)])
session_router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(same_site_only)])
"""Any live session, whatever its stage: who am I, and the steps that finish signing in."""
router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(same_site_only)])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


def me_of(p: Principal, row: dict[str, Any] | None = None) -> Me:
    src = row or {}
    role = src.get("role", p.role)
    limits = session_settings()
    return Me(
        id=p.user_id, email=src.get("email", p.email), display_name=src.get("display_name", p.display_name),
        role=role, permissions=sorted(perm.value for perm in p.permissions),
        language=src.get("language", p.language), timezone=src.get("timezone", p.timezone),
        session_expires_at=p.session_expires_at,
        session_idle_hours=limits.admin_idle_hours if role == "SUPER_ADMIN" else limits.idle_hours,
        stage=p.stage,  # type: ignore[arg-type]
        mfa_enabled=p.mfa_enabled, mfa_required=p.mfa_required, must_change_password=p.must_change_password,
        recovery_codes_left=p.recovery_codes_left, observability_id=crypto.observability_id(p.user_id),
        transparency=transparency_open(), support=support.support_on(), explain=explain_on(),
    )


def with_consents(who: Me, principal: Principal, conn: psycopg.Connection[Any]) -> Me:
    """The consents the reader owes (plan UX, A4) and their membership now (A8), on every Me a step of signing in or
    /auth/me answers: the page shows the gate, or what a limited account can do, at once instead of opening the
    product and meeting a 403 on its first read."""
    if not principal.is_full:
        return who
    update: dict[str, Any] = {}
    if consents.gate_enabled() and not consents.exempt(principal.email, super_admin=principal.is_super_admin):
        update["consents_due"] = consents.due_cached(conn, principal.user_id)
    found = membership.summary(membership.of(conn, principal.user_id, email=principal.email,
                                             super_admin=principal.is_super_admin))
    if found is not None:
        update["membership"] = MembershipSummary(**found)
    # the welcome and the hints (plan UX, A13): the page opens /welcome once the consents are done
    prefs = favorites.preferences(conn, principal.user_id)
    update["hints_seen"] = list(prefs.hints_seen)
    # the welcome tour and the guides of each screen (UX-027)
    update["guides"] = [GuideState(**{f: getattr(g, f) for f in GuideState.model_fields})
                        for g in guides.progress(conn, principal.user_id)]
    update["guides_on"] = guides.guides_on()
    update["guides_auto"] = guides.auto(conn, principal.user_id)
    if favorites.welcome_due(conn, principal.user_id, reader=principal.role == Role.USER):
        update["welcome_due"] = True
        update["welcome_steps"] = list(favorites.welcome_steps(conn, principal.user_id))
    return who.model_copy(update=update) if update else who


def _signed_in(response: Response, issued: tuple[str, Principal], conn: psycopg.Connection[Any]) -> Me:
    token, principal = issued
    set_session_cookie(response, token, principal.session_expires_at)
    return with_consents(me_of(principal), principal, conn)


@public_router.post("/login", response_model=Me)
def login(body: LoginIn, request: Request, response: Response, conn: Db) -> Me:
    """Sets an HttpOnly, SameSite session cookie. The token is never in the body. When a step is still owed
    (stage mfa / enroll / password) the session can do nothing but that step."""
    issued = service.login(body.email, body.password, ip=client_ip(request),
                           user_agent=request.headers.get("user-agent"))
    return _signed_in(response, issued, conn)


@public_router.post("/logout", status_code=204)
def logout(request: Request, principal: Annotated[Principal | None, Depends(optional_principal)]) -> Response:
    """Ends this browser's session. Always succeeds: signing out twice is not an error."""
    if principal is not None:
        service.logout(principal, ip=client_ip(request))
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@session_router.get("/me", response_model=Me)
def me(principal: AnySession, conn: Db) -> Me:
    return with_consents(me_of(principal), principal, conn)


@session_router.post("/mfa/verify", response_model=Me)
def verify_mfa(body: MfaVerifyIn, request: Request, response: Response, principal: AnySession,
               conn: Db) -> Me:
    """Second step: a 6-digit code from the authenticator app, or one recovery code. A new session replaces the
    staged one."""
    issued = service.verify_mfa(principal, code=body.code, recovery_code=body.recovery_code, ip=client_ip(request),
                                user_agent=request.headers.get("user-agent"))
    return _signed_in(response, issued, conn)


@session_router.post("/mfa/enroll/start", response_model=MfaEnrollment)
def start_enrollment(body: MfaStartIn, request: Request, principal: AnySession) -> MfaEnrollment:
    e = service.start_enrollment(principal, password=body.password, ip=client_ip(request))
    return MfaEnrollment(secret=e.secret, otpauth_uri=e.otpauth_uri, qr_svg=e.qr_svg, issuer=e.issuer,
                         account=e.account)


@session_router.post("/mfa/enroll/confirm", response_model=MfaEnrolled)
def confirm_enrollment(body: MfaCodeIn, request: Request, response: Response, principal: AnySession,
                       conn: Db) -> MfaEnrolled:
    """The first code turns the second factor on. The recovery codes come back ONCE, here."""
    codes, advanced = service.confirm_enrollment(principal, code=body.code, ip=client_ip(request),
                                                 user_agent=request.headers.get("user-agent"))
    if advanced is not None:
        me_now = _signed_in(response, advanced, conn)
    else:
        me_now = with_consents(
            me_of(principal).model_copy(update={"mfa_enabled": True, "recovery_codes_left": len(codes)}),
            principal, conn)
    return MfaEnrolled(me=me_now, recovery_codes=codes)


@session_router.post("/password/required", response_model=Me)
def set_required_password(body: RequiredPasswordIn, request: Request, response: Response,
                          principal: AnySession, conn: Db) -> Me:
    """The account was created or reset by an administrator: it chooses its own password before anything else."""
    issued = service.set_required_password(principal, new_password=body.new_password, ip=client_ip(request),
                                           user_agent=request.headers.get("user-agent"))
    return _signed_in(response, issued, conn)


@router.patch("/me/preferences", response_model=Me)
def update_preferences(body: PreferencesIn, principal: App, conn: Db) -> Me:
    row = service.update_preferences(principal, language=body.language, timezone=body.timezone,
                                     display_name=body.display_name)
    if body.guides_auto is not None:
        guides.set_auto(principal.user_id, body.guides_auto, at=now())
        conn.rollback()  # the connection's snapshot is older than this write: Me reads it again
    return with_consents(me_of(principal, row), principal, conn)


@router.post("/me/password", status_code=204)
def change_password(body: PasswordChangeIn, request: Request, principal: App) -> Response:
    """Every other session of this account is ended; this one stays signed in."""
    service.change_password(principal, current_password=body.current_password, new_password=body.new_password,
                            ip=client_ip(request))
    return Response(status_code=204)


@router.post("/me/mfa/disable", status_code=204)
def disable_mfa(body: MfaGuardedIn, request: Request, principal: App) -> Response:
    """Refused (409 mfa_required_by_policy) when the role or the owner requires a second factor."""
    service.disable_mfa(principal, password=body.password, code=body.code, ip=client_ip(request))
    return Response(status_code=204)


@router.post("/me/mfa/recovery-codes", response_model=RecoveryCodes)
def regenerate_recovery_codes(body: MfaGuardedIn, request: Request, principal: App) -> RecoveryCodes:
    """New codes replace every old one, used or not. Shown once."""
    return RecoveryCodes(recovery_codes=service.regenerate_recovery_codes(principal, password=body.password,
                                                                          code=body.code, ip=client_ip(request)))


@router.get("/me/sessions", response_model=list[SessionInfo])
def my_sessions(conn: Db, principal: App) -> list[SessionInfo]:
    return [SessionInfo(**r) for r in service.my_sessions(conn, principal)]


@router.post("/me/sessions/{session_id}/revoke", status_code=204)
def revoke_my_session(request: Request, principal: App,
                      session_id: Annotated[str, Path(pattern=r"^[0-9a-f]{16}$")],
                      body: IdentityIn | None = None) -> Response:
    """Ending another session asks for the password or a code (ASVS 7.5.2); ending this one is signing out."""
    who = body or IdentityIn()
    own = service.revoke_my_session(principal, session_id, ip=client_ip(request), password=who.password,
                                    code=who.code)
    response = Response(status_code=204)
    if own:
        clear_session_cookie(response)
    return response


@router.post("/me/sessions/revoke-others", response_model=dict[str, int])
def revoke_my_other_sessions(request: Request, principal: App, body: IdentityIn | None = None) -> dict[str, int]:
    """Every other session ends, once the password or a code of the second factor confirms who asks (ASVS 7.5.2)."""
    who = body or IdentityIn()
    return {"revoked": service.revoke_my_other_sessions(principal, ip=client_ip(request), password=who.password,
                                                        code=who.code)}


@router.get("/me/access", response_model=list[AccessEvent])
def my_access(conn: Db, principal: App,
              limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[AccessEvent]:
    """This account's recent sign-ins, failed attempts, second-factor events and sign-outs."""
    return [AccessEvent(**r) for r in service.my_access_history(conn, principal, limit=limit)]
