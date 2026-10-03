"""Who is asking, and whether they may.

Authorization is decided here, on the server, for every request - hiding a link in
the browser is presentation, not protection. A route belongs to exactly one tier:

  public     /health, /auth/login, /auth/logout
  APP        the product (any signed-in, active account)
  ADMIN      /api/v1/admin/* (SUPER_ADMIN)

A request with no valid session gets 401; a signed-in account without the permission
gets 403. Neither says anything about the data behind the route.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Annotated, Any

import psycopg
from fastapi import Depends, Request, Response

from fbi.api.deps import get_db
from fbi.api.errors import ApiError
from fbi.auth.roles import Permission
from fbi.auth.service import Principal, principal_from_token
from fbi.auth.settings import session_settings

DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "predigol"

Db = Annotated[psycopg.Connection[Any], Depends(get_db)]


def allowed_origins() -> list[str]:
    return [o.strip() for o in os.environ.get("FBI_API_CORS_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()]


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def optional_principal(request: Request, conn: Db) -> Principal | None:
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    principal = principal_from_token(conn, request.cookies.get(session_settings().cookie_name))
    if principal is not None:
        request.state.principal = principal
    return principal


def current_principal(principal: Annotated[Principal | None, Depends(optional_principal)]) -> Principal:
    if principal is None:
        raise ApiError(401, "unauthenticated", "sign in to continue")
    return principal


def require(permission: Permission) -> Callable[[Principal], Principal]:
    def dependency(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
        if not principal.can(permission):
            raise ApiError(403, "forbidden", "this account may not use this route")
        return principal

    dependency.__name__ = f"require_{permission.value.replace('.', '_')}"
    return dependency


def same_site_only(request: Request) -> None:
    """A state-changing request must come from our own pages.

    The session cookie is SameSite=Lax, which already keeps it off cross-site POSTs; on
    top of that a custom header is required - a cross-site form cannot set one, and a
    cross-site script cannot send one without a CORS preflight that only our own
    origins pass - and a declared Origin must be one of ours.
    """
    if request.method in SAFE_METHODS:
        return
    if request.headers.get(CSRF_HEADER, "").lower() != CSRF_VALUE:
        raise ApiError(403, "csrf", "missing same-site request header")
    origin = request.headers.get("origin")
    if origin and origin not in allowed_origins():
        raise ApiError(403, "csrf", "request from an origin that is not this platform")


def set_session_cookie(response: Response, token: str) -> None:
    cfg = session_settings()
    response.set_cookie(
        key=cfg.cookie_name, value=token, max_age=cfg.ttl_hours * 3600, path="/",
        secure=cfg.cookie_secure, httponly=True, samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    cfg = session_settings()
    response.delete_cookie(key=cfg.cookie_name, path="/", secure=cfg.cookie_secure, httponly=True, samesite="lax")


require_app = require(Permission.APP)
require_admin = require(Permission.ADMIN)
require_users_admin = require(Permission.MANAGE_USERS)

App = Annotated[Principal, Depends(require_app)]
Admin = Annotated[Principal, Depends(require_admin)]
UsersAdmin = Annotated[Principal, Depends(require_users_admin)]
