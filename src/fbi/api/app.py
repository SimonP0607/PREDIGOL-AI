"""Application factory for the product API."""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from fbi.api import errors
from fbi.api.limits import BodyLimit, SlidingWindow
from fbi.api.routers import (
    admin_users,
    analyst,
    auth,
    center,
    evolution,
    explorer,
    football,
    market,
    product,
    records,
    system,
    truth,
)
from fbi.api.security import (
    SAFE_METHODS,
    allowed_origins,
    client_ip,
    require_admin,
    require_app,
    same_site_only,
)
from fbi.api.services.ops import VERSION
from fbi.auth import crypto
from fbi.auth.service import Principal, record_admin_write
from fbi.core.config import settings
from fbi.core.logging import configure

log = structlog.get_logger("api")

AUTH_STEP_PATHS = frozenset({"/api/v1/auth/login", "/api/v1/auth/mfa/verify",
                             "/api/v1/auth/mfa/enroll/confirm", "/api/v1/auth/password/required"})
SELF_AUDITED = ("/api/v1/admin/users",)
"""Account management records its own, more precise events (user.created, password.reset, ...)."""


def _flag(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        configure(settings.runtime.log_level)
        yield

    # A deployment closes the interactive docs and the schema (FBI_API_DOCS=0): they list every route,
    # admin ones included. Locally they stay open.
    docs = _flag("FBI_API_DOCS", default=True)
    # The second factor's secrets cannot be stored or checked without the key: a production API refuses to start
    # without it rather than lock the owner out at the first sign-in.
    if settings.runtime.env == "production" and not crypto.key_available():
        raise RuntimeError("FBI_AUTH_SECRET_KEY must be set (32 random bytes, base64) in production")
    app = FastAPI(
        title="Football Intelligence Platform",
        version=VERSION,
        docs_url="/docs" if docs else None,
        openapi_url="/openapi.json" if docs else None,
        redoc_url=None,
        lifespan=lifespan,
        description=(
            "Read-only product API. Every list answers ok | empty | insufficient_data | "
            "not_available with a reason; nothing is filled in to look complete."
        ),
    )
    errors.install(app)

    # Registered BEFORE the CORS middleware, so it sits inside it: an
    # unexpected error becomes a JSON 500 that still carries the CORS headers.
    # Otherwise the browser reports a CORS failure and hides the real status.
    @app.middleware("http")
    async def _contain(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            rid = errors.request_id(request)
            log.error("api.unhandled", request_id=rid, path=request.url.path, error=exc.__class__.__name__)
            return JSONResponse(errors.body("internal", "internal error; see the server log for this request id", rid),
                                status_code=500)

    app.add_middleware(
        CORSMiddleware,
        # Explicit origins only - never "*" - because the session cookie travels with credentials.
        allow_origins=allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["accept", "content-type", "x-request-id", "x-requested-with"],
        expose_headers=["x-request-id"],
        max_age=600,
    )

    limiter = SlidingWindow(per_window=int(os.environ.get("FBI_API_RATE_LIMIT", "240")), window_s=60.0)
    login_limiter = SlidingWindow(per_window=int(os.environ.get("FBI_API_LOGIN_RATE_LIMIT", "20")), window_s=60.0)
    """Sign-in and second-factor attempts per address per minute, before any password is hashed."""

    @app.middleware("http")
    async def _context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id", "")
        rid = rid if rid.isalnum() and len(rid) <= 32 else uuid.uuid4().hex[:12]
        request.state.request_id = rid
        client = request.client.host if request.client else "unknown"
        path = request.url.path
        limited = request.method != "OPTIONS" and not limiter.allow(client)
        if not limited and request.method == "POST" and path in AUTH_STEP_PATHS:
            limited = not login_limiter.allow(client)
        if limited:
            return JSONResponse(
                {"status": "error", "error": {"code": "rate_limited", "message": "too many requests"},
                 "request_id": rid},
                status_code=429, headers={"retry-after": "10", "x-request-id": rid},
            )
        started = time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        principal = getattr(request.state, "principal", None)
        if (request.method not in SAFE_METHODS and path.startswith("/api/v1/admin/")
                and not path.startswith(SELF_AUDITED) and isinstance(principal, Principal)):
            try:
                await run_in_threadpool(record_admin_write, principal.user_id, method=request.method, path=path,
                                        status=response.status_code, ip=client_ip(request), request_id=rid)
            except Exception as exc:  # the action happened; a missing audit row is logged, never a 500
                log.error("api.admin_audit_failed", request_id=rid, error=exc.__class__.__name__)
        response.headers["x-request-id"] = rid
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "no-referrer"
        response.headers["cache-control"] = "no-store"
        log.info("api.request", method=request.method, path=request.url.path, status=response.status_code,
                 ms=elapsed_ms, request_id=rid)
        return response

    # Three tiers, decided here and nowhere else (see fbi.api.security):
    #   public  - health, sign-in, sign-out
    #   app     - the product, for any signed-in account
    #   admin   - /api/v1/admin/*, SUPER_ADMIN only
    for r in (system.router, auth.public_router, auth.session_router):
        app.include_router(r, prefix="/api/v1")
    app_tier = [Depends(same_site_only), Depends(require_app)]
    for r in (auth.router, product.router, records.router, football.router, market.router, center.router):
        app.include_router(r, prefix="/api/v1", dependencies=app_tier)
    admin_tier = [Depends(same_site_only), Depends(require_admin)]
    for r in (system.admin_router, football.admin_router, market.admin_router,
              center.admin_router, explorer.router, analyst.router, admin_users.router, truth.router,
              evolution.router):
        app.include_router(r, prefix="/api/v1/admin", dependencies=admin_tier)
    # The original unversioned health endpoint stays where monitors expect it.
    app.add_api_route("/health", system.get_health, methods=["GET"], include_in_schema=False)
    # Outermost: a body over the limit is refused before anything reads it.
    app.add_middleware(BodyLimit, max_bytes=int(os.environ.get("FBI_API_MAX_BODY_BYTES", str(256 * 1024))))
    return app
