"""Error responses that say what went wrong without saying what is inside.

A 500 never carries a traceback, a SQL fragment or a connection string: it
carries a request id, and the full error goes to the structured log under the
same id.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from fbi.api.limits import BodyTooLargeError
from fbi.auth.service import AuthError

log = structlog.get_logger("api")


def body(code: str, message: str, request_id: str, **extra: object) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message, **extra}
    return {"status": "error", "error": error, "request_id": request_id}


class ApiError(Exception):
    """A refusal the API means to give: a status and a code the frontend translates."""

    def __init__(self, status: int, code: str, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


STATUS_CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict",
                422: "invalid", 429: "rate_limited", 503: "unavailable"}


def request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else uuid.uuid4().hex[:12]


def install(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        code = STATUS_CODES.get(exc.status_code, "error")
        return JSONResponse(body(code, str(exc.detail), request_id(request)), status_code=exc.status_code)

    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(body(exc.code, exc.message, request_id(request)), status_code=exc.status,
                            headers=exc.headers)

    @app.exception_handler(AuthError)
    async def _auth(request: Request, exc: AuthError) -> JSONResponse:
        headers = {"retry-after": str(exc.retry_after)} if exc.retry_after else {}
        extra: dict[str, object] = {"problems": exc.problems} if exc.problems else {}
        extra.update(exc.extra)
        if exc.retry_after:
            extra["retry_after"] = exc.retry_after
        return JSONResponse(body(exc.code, exc.code.replace("_", " "), request_id(request), **extra),
                            status_code=exc.status, headers=headers)

    @app.exception_handler(BodyTooLargeError)
    async def _too_large(request: Request, exc: BodyTooLargeError) -> JSONResponse:
        return JSONResponse(body("payload_too_large", "request body too large", request_id(request)),
                            status_code=413, headers={"connection": "close"})

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and messages only - never the submitted values.
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e.get('loc', ()) if p != 'query')}: {e.get('msg', 'invalid')}"
            for e in exc.errors()
        )
        return JSONResponse(body("invalid", problems or "invalid request", request_id(request)), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = request_id(request)
        log.error("api.unhandled", request_id=rid, path=request.url.path, error=exc.__class__.__name__)
        return JSONResponse(body("internal", "internal error; see the server log for this request id", rid),
                            status_code=500)
