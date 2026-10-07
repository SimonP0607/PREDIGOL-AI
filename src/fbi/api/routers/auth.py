"""Sign in (password, second factor, enrolment, required new password), sign out, who am I, my preferences, my
security: sessions, sign-in history, the second factor and its recovery codes."""

from __future__ import annotations

from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Path, Query, Request, Response

from fbi.api.contracts.auth import (
    AccessEvent,
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
from fbi.auth import service
from fbi.auth.service import Principal

public_router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(same_site_only)])
session_router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(same_site_only)])
"""Any live session, whatever its stage: who am I, and the steps that finish signing in."""
router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(same_site_only)])
Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


def me_of(p: Principal, row: dict[str, Any] | None = None) -> Me:
    src = row or {}
    return Me(
        id=p.user_id, email=src.get("email", p.email), display_name=src.get("display_name", p.display_name),
        role=src.get("role", p.role), permissions=sorted(perm.value for perm in p.permissions),
        language=src.get("language", p.language), timezone=src.get("timezone", p.timezone),
        session_expires_at=p.session_expires_at, stage=p.stage,  # type: ignore[arg-type]
        mfa_enabled=p.mfa_enabled, mfa_required=p.mfa_required, must_change_password=p.must_change_password,
        recovery_codes_left=p.recovery_codes_left,
    )


def _signed_in(response: Response, issued: tuple[str, Principal]) -> Me:
    token, principal = issued
    set_session_cookie(response, token, principal.session_expires_at)
    return me_of(principal)


@public_router.post("/login", response_model=Me)
def login(body: LoginIn, request: Request, response: Response) -> Me:
    """Sets an HttpOnly, SameSite session cookie. The token is never in the body. When a step is still owed
    (stage mfa / enroll / password) the session can do nothing but that step."""
    issued = service.login(body.email, body.password, ip=client_ip(request),
                           user_agent=request.headers.get("user-agent"))
    return _signed_in(response, issued)


@public_router.post("/logout", status_code=204)
def logout(request: Request, principal: Annotated[Principal | None, Depends(optional_principal)]) -> Response:
    """Ends this browser's session. Always succeeds: signing out twice is not an error."""
    if principal is not None:
        service.logout(principal, ip=client_ip(request))
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@session_router.get("/me", response_model=Me)
def me(principal: AnySession) -> Me:
    return me_of(principal)


@session_router.post("/mfa/verify", response_model=Me)
def verify_mfa(body: MfaVerifyIn, request: Request, response: Response, principal: AnySession) -> Me:
    """Second step: a 6-digit code from the authenticator app, or one recovery code. A new session replaces the
    staged one."""
    issued = service.verify_mfa(principal, code=body.code, recovery_code=body.recovery_code, ip=client_ip(request),
                                user_agent=request.headers.get("user-agent"))
    return _signed_in(response, issued)


@session_router.post("/mfa/enroll/start", response_model=MfaEnrollment)
def start_enrollment(body: MfaStartIn, request: Request, principal: AnySession) -> MfaEnrollment:
    e = service.start_enrollment(principal, password=body.password, ip=client_ip(request))
    return MfaEnrollment(secret=e.secret, otpauth_uri=e.otpauth_uri, qr_svg=e.qr_svg, issuer=e.issuer,
                         account=e.account)


@session_router.post("/mfa/enroll/confirm", response_model=MfaEnrolled)
def confirm_enrollment(body: MfaCodeIn, request: Request, response: Response, principal: AnySession) -> MfaEnrolled:
    """The first code turns the second factor on. The recovery codes come back ONCE, here."""
    codes, advanced = service.confirm_enrollment(principal, code=body.code, ip=client_ip(request),
                                                 user_agent=request.headers.get("user-agent"))
    if advanced is not None:
        me_now = _signed_in(response, advanced)
    else:
        me_now = me_of(principal).model_copy(update={"mfa_enabled": True, "recovery_codes_left": len(codes)})
    return MfaEnrolled(me=me_now, recovery_codes=codes)


@session_router.post("/password/required", response_model=Me)
def set_required_password(body: RequiredPasswordIn, request: Request, response: Response,
                          principal: AnySession) -> Me:
    """The account was created or reset by an administrator: it chooses its own password before anything else."""
    issued = service.set_required_password(principal, new_password=body.new_password, ip=client_ip(request),
                                           user_agent=request.headers.get("user-agent"))
    return _signed_in(response, issued)


@router.patch("/me/preferences", response_model=Me)
def update_preferences(body: PreferencesIn, principal: App) -> Me:
    row = service.update_preferences(principal, language=body.language, timezone=body.timezone,
                                     display_name=body.display_name)
    return me_of(principal, row)


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
                      session_id: Annotated[str, Path(pattern=r"^[0-9a-f]{16}$")]) -> Response:
    own = service.revoke_my_session(principal, session_id, ip=client_ip(request))
    response = Response(status_code=204)
    if own:
        clear_session_cookie(response)
    return response


@router.post("/me/sessions/revoke-others", response_model=dict[str, int])
def revoke_my_other_sessions(request: Request, principal: App) -> dict[str, int]:
    return {"revoked": service.revoke_my_other_sessions(principal, ip=client_ip(request))}


@router.get("/me/access", response_model=list[AccessEvent])
def my_access(conn: Db, principal: App,
              limit: Annotated[int, Query(ge=1, le=200)] = 50) -> list[AccessEvent]:
    """This account's recent sign-ins, failed attempts, second-factor events and sign-outs."""
    return [AccessEvent(**r) for r in service.my_access_history(conn, principal, limit=limit)]
