"""Application factory for the product API."""

from __future__ import annotations

import os
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from fbi.api import errors
from fbi.api.routers import (
    admin_users,
    analyst,
    auth,
    center,
    explorer,
    football,
    market,
    product,
    system,
    truth,
)
from fbi.api.security import allowed_origins, require_admin, require_app, same_site_only
from fbi.api.services.ops import VERSION
from fbi.core.config import settings
from fbi.core.logging import configure

log = structlog.get_logger("api")


class _RateLimiter:
    """A per-client sliding window. Generous for one person clicking around;
    it exists to stop a runaway polling loop from pinning the database."""

    def __init__(self, per_window: int, window_s: float) -> None:
        self._per_window = per_window
        self._window_s = window_s
        self._hits: dict[str, deque[float]] = {}

    def allow(self, client: str) -> bool:
        t = time.monotonic()
        q = self._hits.setdefault(client, deque())
        while q and t - q[0] > self._window_s:
            q.popleft()
        if len(q) >= self._per_window:
            return False
        q.append(t)
        return True


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        configure(settings.runtime.log_level)
        yield

    app = FastAPI(
        title="Football Intelligence Platform",
        version=VERSION,
        docs_url="/docs",
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

    limiter = _RateLimiter(
        per_window=int(os.environ.get("FBI_API_RATE_LIMIT", "240")), window_s=60.0
    )

    @app.middleware("http")
    async def _context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = request.headers.get("x-request-id", "")
        rid = rid if rid.isalnum() and len(rid) <= 32 else uuid.uuid4().hex[:12]
        request.state.request_id = rid
        client = request.client.host if request.client else "unknown"
        if request.method != "OPTIONS" and not limiter.allow(client):
            return JSONResponse(
                {"status": "error", "error": {"code": "rate_limited", "message": "too many requests"},
                 "request_id": rid},
                status_code=429, headers={"retry-after": "10", "x-request-id": rid},
            )
        started = time.monotonic()
        response = await call_next(request)
        elapsed_ms = int((time.monotonic() - started) * 1000)
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
    for r in (system.router, auth.public_router):
        app.include_router(r, prefix="/api/v1")
    app_tier = [Depends(same_site_only), Depends(require_app)]
    for r in (auth.router, product.router, football.router, market.router, center.router):
        app.include_router(r, prefix="/api/v1", dependencies=app_tier)
    admin_tier = [Depends(same_site_only), Depends(require_admin)]
    for r in (system.admin_router, football.admin_router, market.admin_router,
              center.admin_router, explorer.router, analyst.router, admin_users.router, truth.router):
        app.include_router(r, prefix="/api/v1/admin", dependencies=admin_tier)
    # The original unversioned health endpoint stays where monitors expect it.
    app.add_api_route("/health", system.get_health, methods=["GET"], include_in_schema=False)
    return app
