"""Application factory for the product API."""

from __future__ import annotations

import os
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from fbi.api import errors
from fbi.api.routers import analyst, center, explorer, football, market, system
from fbi.api.services.ops import VERSION
from fbi.core.config import settings
from fbi.core.logging import configure

log = structlog.get_logger("api")

DEFAULT_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


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

    origins = [o.strip() for o in os.environ.get("FBI_API_CORS_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        # POST exists for one route only - /analyst/ask - and it writes nothing.
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["accept", "content-type", "x-request-id"],
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

    for r in (system.router, football.router, market.router, explorer.router, analyst.router, center.router):
        app.include_router(r, prefix="/api/v1")
    # The original unversioned health endpoints stay where monitors expect them.
    app.add_api_route("/health", system.get_health, methods=["GET"], include_in_schema=False)
    app.add_api_route("/health/quality", system.get_quality, methods=["GET"], include_in_schema=False)
    return app
