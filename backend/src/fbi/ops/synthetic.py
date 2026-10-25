"""The synthetic journey (plan UX, A2): every 15 minutes a dedicated USER account walks what a reader does - the
sign-in page, signing in, Home, a match of today and its centre, the day's picks and their own picks, signing out -
through the public front door, as a browser would, and the worker writes the result in the job ledger
(``raw.ingestion_runs``, job ``synthetic_journey``). A failed step is an error in the log, which reaches Sentry
(fbi.core.sentry.report_error_logs), and the console shows the last runs with the jobs.

Black box on purpose: it speaks HTTP to the platform like a reader and imports nothing of what serves the pages, so it
sees what a reader would - Caddy, the web, the API and the database together. Besides its ledger row it leaves what
any reader's visit leaves: a session, closed at the end, and the sign-in's audit rows (about 190 rows a day).

Off until the owner configures it (and creates the account, which only the owner does):

    FBI_SYNTHETIC_BASE_URL       the public origin, e.g. https://predigolai.com
    FBI_SYNTHETIC_EMAIL          the dedicated USER account (no second factor)
    FBI_SYNTHETIC_PASSWORD_FILE  a file only root can read, with its password (or FBI_SYNTHETIC_PASSWORD)
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
import structlog

from fbi.ingestion.ledger import RunCounters, RunLedger

log = structlog.get_logger(__name__)

JOB_TYPE = "synthetic_journey"
EVERY_MINUTES = 15
BUDGET_S = 90.0
"""The whole walk: past it the remaining steps are skipped (and named), but a signed-in walk always signs out - the
job's deadline cannot stop a thread, so the walk stops itself (review of A2)."""
SAME_SITE = {"x-requested-with": "predigol"}
AGENT = "predigol-synthetic/1 (+plan UX A2)"


@dataclass(frozen=True, slots=True)
class JourneyConfig:
    base_url: str
    email: str
    password: str
    timeout_s: float = 15.0

    def __repr__(self) -> str:  # never the password, never the whole address
        return f"JourneyConfig(base_url={self.base_url!r}, email='***', timeout_s={self.timeout_s})"


@dataclass(frozen=True, slots=True)
class Step:
    name: str
    ok: bool
    status: int | None
    ms: int
    note: str = ""

    def problem(self) -> str:
        return f"{self.name}: " + (f"HTTP {self.status}" if self.status is not None else self.note or "failed") + (
            f" ({self.note})" if self.status is not None and self.note else "")


def config_from_env(env: dict[str, str] | None = None) -> JourneyConfig | None:
    """The journey's configuration, or None while any part of it is missing (then the worker does not run it)."""
    source = os.environ if env is None else env
    base = source.get("FBI_SYNTHETIC_BASE_URL", "").strip().rstrip("/")
    email = source.get("FBI_SYNTHETIC_EMAIL", "").strip()
    password = source.get("FBI_SYNTHETIC_PASSWORD", "")
    path = source.get("FBI_SYNTHETIC_PASSWORD_FILE", "").strip()
    if not password and path:
        try:
            password = Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            return None
    if not base.startswith(("https://", "http://")) or not email or not password:
        return None
    return JourneyConfig(base_url=base, email=email, password=password)


def walk(cfg: JourneyConfig, *, client: httpx.Client | None = None, today: date | None = None,
         budget_s: float = BUDGET_S, clock: Callable[[], float] = time.monotonic) -> list[Step]:
    """Walk the journey once and say how each step went. Stops at a failed sign-in; signs out whenever the server
    accepted the password, even when a step of signing in was still owed (review of A2: that session stayed open).
    Never raises: a step that cannot be made is a failed step."""
    day = today or datetime.now(UTC).date()
    steps: list[Step] = []
    deadline = clock() + budget_s
    own = client is None
    http = client or httpx.Client(base_url=cfg.base_url, timeout=cfg.timeout_s, follow_redirects=False,
                                  headers={"user-agent": AGENT})

    def call(name: str, method: str, path: str, *, check: Callable[[httpx.Response], str] | None = None,
             always: bool = False, **kwargs: Any) -> httpx.Response | None:
        if not always and clock() > deadline:
            steps.append(Step(name, False, None, 0, "skipped: past the walk's time budget"))
            return None
        started = time.monotonic()
        try:
            reply = http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            steps.append(Step(name, False, None, int((time.monotonic() - started) * 1000), type(exc).__name__))
            return None
        ms = int((time.monotonic() - started) * 1000)
        problem = "" if 200 <= reply.status_code < 300 else "unexpected status"
        if not problem and check is not None:
            try:
                problem = check(reply)
            except Exception as exc:  # an answer the check cannot read is a failed step
                problem = f"unreadable answer ({type(exc).__name__})"
        steps.append(Step(name, not problem, reply.status_code, ms, problem if problem != "unexpected status" else ""))
        last[0] = reply
        return reply if not problem else None

    last: list[httpx.Response | None] = [None]
    try:
        call("page", "GET", "/login", headers={"accept": "text/html"},
             check=lambda r: "" if "<html" in r.text[:4000].lower() else "not the sign-in page")
        last[0] = None
        signed = call("sign_in", "POST", "/api/v1/auth/login", headers=SAME_SITE,
                      json={"email": cfg.email, "password": cfg.password},
                      check=lambda r: "" if r.json().get("stage") == "full" else "a sign-in step is still owed")
        accepted = last[0] is not None and 200 <= last[0].status_code < 300
        if signed is None:
            if accepted:  # a session was opened (a step still owed): it is closed all the same
                call("sign_out", "POST", "/api/v1/auth/logout", headers=SAME_SITE, always=True)
            return steps
        try:
            call("home", "GET", "/api/v1/home")
            matches = call("matches_today", "GET", "/api/v1/matches",
                           params={"date_from": day.isoformat(), "date_to": day.isoformat(), "limit": 5,
                                   "order": "asc"})
            rows = (matches.json().get("data") or []) if matches is not None else []
            first = next((r.get("id") for r in rows if isinstance(r, dict) and isinstance(r.get("id"), int)), None)
            if first is not None:
                call("match_center", "GET", f"/api/v1/matches/{first}/center")
            call("picks", "GET", "/api/v1/picks")
            call("my_picks", "GET", "/api/v1/me/picks", params={"limit": 5})
        finally:
            call("sign_out", "POST", "/api/v1/auth/logout", headers=SAME_SITE, always=True)
    finally:
        if own:
            http.close()
    return steps


def run_once(conn: psycopg.Connection[Any], cfg: JourneyConfig, *, client: httpx.Client | None = None,
             today: date | None = None) -> list[Step]:
    """One journey, with its ledger row: completed when every step passed, failed otherwise (the last error names
    the step and its status, never a body). A failure is logged as an error, which Sentry receives."""
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB_TYPE)
    counters = RunCounters()
    steps: list[Step] = []
    try:
        steps = walk(cfg, client=client, today=today)
        counters.errors.extend(s.problem() for s in steps if not s.ok)
    finally:
        notes = ", ".join(f"{s.name} {s.status if s.status is not None else '-'} {s.ms} ms" for s in steps)
        ledger.close(run_id, counters, notes=notes[:1000] or None)
    failed = [s for s in steps if not s.ok]
    if failed:
        log.error("synthetic.failed", step=failed[0].name, status=failed[0].status, error=failed[0].problem(),
                  failed_steps=len(failed), steps=len(steps))
    else:
        log.info("synthetic.passed", steps=len(steps), ms=sum(s.ms for s in steps))
    return steps
