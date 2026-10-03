"""Sign in, sign out, who am I, and my preferences."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from fbi.api.contracts.auth import LoginIn, Me, PasswordChangeIn, PreferencesIn
from fbi.api.security import (
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
router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(same_site_only)])


def me_of(p: Principal, row: dict[str, Any] | None = None) -> Me:
    src = row or {}
    return Me(
        id=p.user_id, email=src.get("email", p.email), display_name=src.get("display_name", p.display_name),
        role=src.get("role", p.role), permissions=sorted(perm.value for perm in p.permissions),
        language=src.get("language", p.language), timezone=src.get("timezone", p.timezone),
        session_expires_at=p.session_expires_at,
    )


@public_router.post("/login", response_model=Me)
def login(body: LoginIn, request: Request, response: Response) -> Me:
    """Sets an HttpOnly, SameSite=Lax session cookie. The token is never in the body."""
    token, principal = service.login(body.email, body.password, ip=client_ip(request),
                                     user_agent=request.headers.get("user-agent"))
    set_session_cookie(response, token)
    return me_of(principal)


@public_router.post("/logout", status_code=204)
def logout(request: Request, principal: Annotated[Principal | None, Depends(optional_principal)]) -> Response:
    """Ends this browser's session. Always succeeds: signing out twice is not an error."""
    if principal is not None:
        service.logout(principal, ip=client_ip(request))
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=Me)
def me(principal: App) -> Me:
    return me_of(principal)


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
