"""The keeper of the heavy admin reads (plan de correcciones UX, AP-A06 «Consola rápida»).

Why: Analytics > Competitions, Analytics > Coverage and Performance read the whole history (nine data flags for each of the
249k stored fixtures; every settled pick). Measured in production on 23-nov-2026 they took 17.3 s, 25.1 s and 12.4 s
the first time and the API keeps their answers (``fbi.api.cache``) - so each person who opened the console after a deploy
or after the answer expired waited that long.

What: while the API's cache is on (the server's API turns it on; the worker, the scripts and the tests never do), one
thread per API process computes those answers a minute after start and again before each one expires, so a reader finds
them ready. Each answer keeps the time it was computed in its own envelope (``meta.generated_at``): the screen shows it.
It uses its own read-only connection, one answer at a time, and a failure is logged and tried again later; it never
touches a request. ``FBI_API_WARM=0`` turns it off without a deploy of code.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
import structlog

from fbi.api import cache
from fbi.api.deps import read_only_connection
from fbi.api.services import analytics, explorer

log = structlog.get_logger(__name__)

START_DELAY_S = 60.0
RETRY_S = 600.0
POLL_S = 30.0


@dataclass(frozen=True)
class Job:
    name: str
    read: Callable[..., Any]
    every_s: float  # always shorter than the answer's own lifetime in its service


# The lifetimes (`@shared(...)`) are in the services; every_s is a third shorter so the entry is replaced before it expires.
JOBS: tuple[Job, ...] = (
    Job("analytics.competitions", explorer.competitions, every_s=explorer.CACHE_SECONDS * 2 / 3),
    Job("analytics.coverage", explorer.coverage, every_s=explorer.CACHE_SECONDS * 2 / 3),
    Job("performance", analytics.performance, every_s=analytics.PERFORMANCE_CACHE_SECONDS * 2 / 3),
)


def enabled() -> bool:
    """On when the API's cache is on, unless FBI_API_WARM says no (0, off, false, no)."""
    if not cache.enabled():
        return False
    return os.environ.get("FBI_API_WARM", "1").strip().lower() not in {"0", "off", "false", "no"}


def run_one(job: Job) -> None:
    """Computes one answer on its own connection and keeps it."""
    conn = read_only_connection()
    try:
        cache.recompute(job.read, conn)
    finally:
        with contextlib.suppress(psycopg.Error):
            conn.rollback()
        conn.close()


def _loop(stop: threading.Event, jobs: tuple[Job, ...]) -> None:
    if stop.wait(START_DELAY_S):
        return
    due = {job.name: 0.0 for job in jobs}
    while not stop.is_set():
        now = time.monotonic()
        for job in jobs:
            if stop.is_set() or due[job.name] > now:
                continue
            started = time.monotonic()
            try:
                run_one(job)
            except Exception as exc:  # a keeper never takes the API down: the reader simply computes it, as before
                due[job.name] = time.monotonic() + RETRY_S
                log.warning("api_warm_failed", job=job.name, error=exc.__class__.__name__)
            else:
                due[job.name] = time.monotonic() + job.every_s
                log.info("api_warm_done", job=job.name, seconds=round(time.monotonic() - started, 1))
        stop.wait(POLL_S)


def start(jobs: tuple[Job, ...] = JOBS) -> threading.Event | None:
    """Starts the keeper when it is on; returns the event that stops it (None when it is off)."""
    if not enabled():
        return None
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop, jobs), name="api-warm", daemon=True).start()
    return stop
