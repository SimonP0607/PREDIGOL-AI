"""The API. Today: /health and /health/quality. Everything else comes after
the data does.

Both endpoints read the database and the job ledger; neither ever calls the
provider (that would spend quota on a health check) or returns a credential.
"""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi import FastAPI, Response

from fbi.core.config import settings
from fbi.core.logging import configure
from fbi.quality.health import health
from fbi.quality.metrics import data_quality_snapshot

VERSION = "0.1.0"

app = FastAPI(title="Football Intelligence Platform", version=VERSION, docs_url="/docs")


@app.on_event("startup")
def _startup() -> None:
    configure(settings.runtime.log_level)


def _conn() -> psycopg.Connection | None:
    try:
        return psycopg.connect(settings.database.psycopg_url, connect_timeout=3)
    except psycopg.Error:
        return None


def _budget() -> int:
    """Our internal cap, never reported as higher than the plan allows - the
    same arithmetic the capturer uses, so /health and the capturer cannot
    disagree about what the budget is."""
    cfg = settings.api_football
    return min(cfg.daily_budget, cfg.per_day_limit)


@app.get("/health")
def get_health(response: Response) -> dict[str, Any]:
    conn = _conn()
    try:
        h = health(conn, version=VERSION, daily_budget=_budget())
    finally:
        if conn is not None:
            conn.close()
    if h.status == "down":
        response.status_code = 503
    return h.as_dict()


@app.get("/health/quality")
def get_quality(response: Response) -> dict[str, Any]:
    conn = _conn()
    if conn is None:
        response.status_code = 503
        return {"status": "down", "detail": "no database connection"}
    try:
        return data_quality_snapshot(
            conn,
            prematch_windows=len(settings.odds.prematch_windows),
            daily_budget=_budget(),
        ).as_dict()
    finally:
        conn.close()
