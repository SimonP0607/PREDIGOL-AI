"""The messenger process (plan UX, A5): sends the queue, drafts the owner's notices about the readers' side, and
nothing else - no model, no decision, no data of PrediGol Intelligence (it runs with the API's database role).

One messenger per database (a PostgreSQL advisory lock on a connection of its own; a second one waits). Work is
organised in cycles of five minutes, each one row of the job ledger (``raw.ingestion_runs``, job
``messenger_cycle``): at the start of a cycle the owner's notices, the legal-change messages, the product
analytics' daily aggregate and retention (A6: the purge only with FBI_EVENTS_PURGE=on) and the retention of the
accounts' one-use links (A7: 30 days, deleted only with FBI_TOKENS_PURGE=on); then a tick every
15 seconds sends what is due (only while FBI_EMAIL_SEND is on and the provider is configured), with a heartbeat on
the run. A cycle that dies is closed as stale by the worker's run watchdog (``fbi.ops.run_watchdog``: the
messenger's job is registered there) and three failed cycles in a row are a ``job_failing`` notice. The container's
health check reads ``ALIVE_FILE``, touched on every tick.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
import structlog

from fbi.auth import tokens
from fbi.core.clock import now
from fbi.core.logging import error_summary
from fbi.customer import events, feedback, membership
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.messaging import notices
from fbi.messaging.email import client_from_env
from fbi.messaging.legal_change import enqueue_legal_changes
from fbi.messaging.outbox import DispatchReport, dispatch, sending_enabled
from fbi.messaging.provider import Provider

log = structlog.get_logger(__name__)

JOB_TYPE = "messenger_cycle"
LOCK_KEY = 0x4642_494D
"""'FBIM': one messenger per database."""
TICK_S = 15.0
CYCLE_S = 300.0
ALIVE_FILE = Path(os.environ.get("FBI_MESSENGER_ALIVE_FILE", "/tmp/predigol-messenger.alive"))
ALIVE_WITHIN_S = 120.0


def try_lock(dsn: str) -> psycopg.Connection[Any] | None:
    conn = psycopg.connect(dsn, connect_timeout=5, autocommit=True, application_name="fbi-messenger")
    row = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()
    if row is not None and row[0]:
        return conn
    conn.close()
    return None


def touch_alive(path: Path = ALIVE_FILE) -> None:
    with contextlib.suppress(OSError):
        path.touch()


def alive(path: Path = ALIVE_FILE, *, within_s: float = ALIVE_WITHIN_S) -> bool:
    """The health check: a tick touched the file recently."""
    try:
        return time.time() - path.stat().st_mtime < within_s
    except OSError:
        return False


@dataclass
class CycleTotals:
    notices: int = 0
    legal: int = 0
    sent: int = 0
    retried: int = 0
    failed: int = 0
    suppressed: int = 0
    deferred: int = 0
    rollup: int = 0
    purge: events.PurgeReport | None = None
    links_purge: tuple[str, int] | None = None
    """The accounts' one-use links past their 30 days (plan UX, A7): the mode and how many."""
    feedback_purge: feedback.PurgeReport | None = None
    """The readers' answers past their 24 months (plan UX, B6), under the analytics' purge switch."""
    membership: int = 0
    """The notices of a membership's end recorded this cycle (plan UX, A8)."""
    errors: list[str] = field(default_factory=list)

    def add(self, report: DispatchReport) -> None:
        self.sent += report.sent
        self.retried += report.retried
        self.failed += report.failed
        self.suppressed += report.suppressed
        self.deferred += report.deferred

    def counters(self, *, interrupted: bool) -> RunCounters:
        provider_calls = self.sent + self.retried + self.deferred
        c = RunCounters(api_calls=provider_calls,
                        rows_inserted=self.notices + self.legal + self.rollup + self.membership,
                        rows_updated=self.sent + self.retried + self.failed + self.suppressed + self.deferred,
                        errors=list(self.errors))
        if interrupted:
            c.stopped_early = "interrupted: the messenger was stopped"
        return c

    def notes(self, *, sending: bool, provider: bool) -> str:
        purge = (f"; events purge {self.purge.mode}: raw {self.purge.raw}, daily {self.purge.daily}"
                 if self.purge is not None else "")
        if self.links_purge is not None:
            purge += f"; links purge {self.links_purge[0]}: {self.links_purge[1]}"
        if self.feedback_purge is not None:
            purge += f"; feedback purge {self.feedback_purge.mode}: {self.feedback_purge.rows}"
        return (f"sending {'on' if sending else 'off'}{'' if provider or not sending else ' (no provider)'}; "
                f"sent {self.sent}, retried {self.retried}, failed {self.failed}, suppressed {self.suppressed}, "
                f"deferred {self.deferred}; notices {self.notices}, legal {self.legal}, membership {self.membership}; "
                f"activity rows {self.rollup}{purge}")


def start_of_cycle(conn: psycopg.Connection[Any], totals: CycleTotals, *, sending: bool, provider: bool) -> None:
    """The legal-change messages, the owner's notices, the product analytics' daily aggregate and retention (A6) with the
    readers' feedback's (B6), the notices of a membership's end (A8) and the old links' purge (A7); each step's failure is
    recorded and the cycle goes on."""
    try:
        totals.legal += enqueue_legal_changes(conn)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        totals.errors.append(f"legal_change: {error_summary(exc)}"[:300])
        log.error("messenger.legal_change_failed", error=error_summary(exc))
    try:
        totals.notices += notices.write(conn, notices.collect(conn, at=now(), sending=sending, provider=provider))
    except Exception as exc:
        conn.rollback()
        totals.errors.append(f"notices: {error_summary(exc)}"[:300])
        log.error("messenger.notices_failed", error=error_summary(exc))
    try:
        moment = now()
        today = events.bogota_day(moment)
        totals.rollup += events.rollup(conn, [today - timedelta(days=1), today])
        totals.purge = events.purge(conn, at=moment)
        totals.feedback_purge = feedback.purge(conn, at=moment, mode=events.purge_mode())
        conn.commit()
    except Exception as exc:
        conn.rollback()
        totals.errors.append(f"activity: {error_summary(exc)}"[:300])
        log.error("messenger.activity_failed", error=error_summary(exc))
    try:
        totals.membership += membership.remind(conn, at=now())
    except Exception as exc:
        conn.rollback()
        totals.errors.append(f"membership: {error_summary(exc)}"[:300])
        log.error("messenger.membership_failed", error=error_summary(exc))
    try:
        totals.links_purge = tokens.purge(conn, at=now())
        conn.commit()
    except Exception as exc:
        conn.rollback()
        totals.errors.append(f"links: {error_summary(exc)}"[:300])
        log.error("messenger.links_purge_failed", error=error_summary(exc))


def tick(conn: psycopg.Connection[Any], provider: Provider | None, totals: CycleTotals) -> None:
    if not sending_enabled() or provider is None:
        return
    try:
        totals.add(dispatch(conn, provider, at=now()))
    except Exception as exc:
        conn.rollback()
        totals.errors.append(f"dispatch: {error_summary(exc)}"[:300])
        log.error("messenger.dispatch_failed", error=error_summary(exc))


def run_cycle(dsn: str, provider: Provider | None, stop: threading.Event, *, tick_s: float = TICK_S,
              cycle_s: float = CYCLE_S, alive_file: Path = ALIVE_FILE) -> CycleTotals:
    """One cycle with its ledger row. Returns early when ``stop`` is set (the run is closed as interrupted)."""
    sending = sending_enabled()
    totals = CycleTotals()
    with psycopg.connect(dsn, connect_timeout=5, options="-c statement_timeout=30000 -c TimeZone=UTC") as conn:
        ledger = RunLedger(conn)
        run_id = ledger.open(JOB_TYPE, params={"sending": sending, "provider": provider is not None})
        try:
            start_of_cycle(conn, totals, sending=sending, provider=provider is not None)
            ends = time.monotonic() + cycle_s
            while not stop.is_set():
                touch_alive(alive_file)
                tick(conn, provider, totals)
                ledger.beat(run_id)
                remaining = ends - time.monotonic()
                if remaining <= 0:
                    break
                stop.wait(min(tick_s, remaining))
        finally:
            ledger.close(run_id, totals.counters(interrupted=stop.is_set()),
                         notes=totals.notes(sending=sending, provider=provider is not None))
    return totals


def run(stop: threading.Event, *, dsn: str, provider_factory: Callable[[], Provider | None] = client_from_env,
        tick_s: float = TICK_S, cycle_s: float = CYCLE_S, alive_file: Path = ALIVE_FILE) -> None:
    """Until ``stop``: take the lock (or wait for it), then one cycle after another."""
    lock: psycopg.Connection[Any] | None = None
    waited = False
    while not stop.is_set() and lock is None:
        try:
            lock = try_lock(dsn)
            if lock is None and not waited:
                log.error("messenger.already_running", action="waiting: another messenger holds the lock")
                waited = True
        except psycopg.OperationalError as exc:
            log.error("messenger.database_unreachable", error=type(exc).__name__)
        if lock is None:
            stop.wait(60)
    if lock is None:
        return
    provider = provider_factory()
    log.info("messenger.started", sending=sending_enabled(), provider=provider is not None)
    try:
        while not stop.is_set():
            try:
                run_cycle(dsn, provider, stop, tick_s=tick_s, cycle_s=cycle_s, alive_file=alive_file)
            except psycopg.OperationalError as exc:  # the database restarted: try again shortly
                log.error("messenger.cycle_failed", error=type(exc).__name__)
                stop.wait(30)
            try:
                lock.execute("SELECT 1")
            except psycopg.Error:
                log.error("messenger.lock_lost", action="leaving: the container restarts and takes it again")
                return
    finally:
        with contextlib.suppress(psycopg.Error):
            lock.close()
        close = getattr(provider, "close", None)
        if callable(close):
            close()
        log.info("messenger.stopped")
