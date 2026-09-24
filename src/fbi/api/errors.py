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

log = structlog.get_logger("api")


def body(code: str, message: str, request_id: str) -> dict[str, object]:
    return {"status": "error", "error": {"code": code, "message": message}, "request_id": request_id}


def request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    return rid if isinstance(rid, str) else uuid.uuid4().hex[:12]


def install(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        code = {400: "bad_request", 404: "not_found", 422: "invalid", 503: "unavailable"}.get(exc.status_code, "error")
        return JSONResponse(body(code, str(exc.detail), request_id(request)), status_code=exc.status_code)

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
