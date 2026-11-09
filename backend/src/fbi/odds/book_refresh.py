"""The book refreshes: ``/odds`` asked again between the model windows, for the explorer's book only (plan Cuotas, BE-011).

The capture asks a followed match at the six model windows (T-72, 48, 24, 12, 6 and 3 h); the provider keeps moving its prices
after the last one (14 days, 1,578 matches: its last pre-match update came a median 103 min before kick-off, after our T-180
capture in 84 % of the matches). This job asks the same ``/odds?fixture=`` at the refresh points of ``fbi.odds.freshness`` that
are not model windows - every 3 h from T-72 h to T-6 h, every hour to T-1 h, at T-30 and T-10 min - and builds that match's book
at once. Nothing the models, the picks, the shadow layer, the families or the parlay read can see it:

* the asks are recorded in ``market.book_asks``, never in ``market.odds_asks`` (the capture's, which ``quote_current``, the
  capture planner and the Match Center go by);
* the bodies go to RAW and to the payload index under this job's ledger run, through the same provider client as the capture
  (pages, retries, the persistent daily quota, the minute limiter); ``quote_extract`` skips a payload whose run is this job, so
  nothing reaches ``market.odds_quotes``, and no price is parsed into ``market.odds_snapshots`` or ``market.market_consensus``;
* RAW keeps an identical body once: when a capture later receives a body a refresh fetched first, the index row becomes the
  capture's at its own time (``RunLedger.record_payloads``), and the capture planner's catch-up ignores this job's payloads
  (``OddsRepository.last_asked``) - everything the model pipeline derives is what it would derive without this job.

WHICH MATCHES: those the capture asks (``scripts.capture_odds.UPCOMING_SQL``, the same conditions, pinned by a test) that the
provider has priced before (an ask with entries, of either table, in the 4 days before kick-off), not started and at least
``MIN_MINUTES_TO_KO`` away. A point is due while its band is open (``freshness.due_point``) and done once the match was asked - by
the capture or by a refresh - at or after its nominal instant.

ITS BUDGET, CUT FIRST: at most ``FBI_ODDS_BOOK_DAILY_BUDGET`` requests a UTC day (8,000 by default; what today's runs spent, or
the book asks recorded today if more), inside the shared daily quota, and never when fewer than ``FBI_ODDS_BOOK_RESERVE`` (6,000)
plus the next 24 h of capture windows are left - in our budget or in what the provider's own headers say remains. Every other
job stops later (the in-play follow at 3,000, the history and reference feeds at the next 24 h of windows). It also stops
mid-run as soon as the provider's count falls below that floor.

OFF BY DEFAULT: nothing runs - not even a query - unless ``FBI_ODDS_BOOK_REFRESH`` and ``FBI_ODDS_BOOK`` are both on. A pass with
nothing due writes no ledger row.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import psycopg
import structlog
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row, tuple_row

from fbi.core.clock import now as clock_now
from fbi.core.errors import CircuitOpenError, ProviderError, QuotaExhaustedError
from fbi.odds.freshness import due_point, minutes_to, refresh_points
from fbi.odds.quote_current import LOOKBACK
from fbi.providers.base import OddsQuote, RawResponse
from fbi.providers.quota import ReportedQuota

log = structlog.get_logger(__name__)

JOB = "odds_book_refresh"
"""The ledger job of the refreshes: ``quote_extract.SKIPPED_JOB`` and ``ledger.BOOK_REFRESH_JOB`` name the same one."""
LOCK_KEY = "fbi.odds_book_refresh"
MIN_MINUTES_TO_KO = 2
"""A match this close to kick-off is not asked: its answer could arrive after the whistle and would not count as pre-match."""
PLANNABLE = frozenset({"NS", "TBD", "PST"})
"""The statuses the capture planner asks (``fbi.odds.schedule.CapturePlanner.plan``)."""
DEFAULT_PER_RUN = 400
DEFAULT_RUN_SECONDS = 240.0

ELIGIBLE_SQL = """
SELECT f.id, f.provider_fixture_id, f.kickoff_at, f.status_short,
       (SELECT max(x.asked_at) FROM (
            SELECT a.asked_at FROM market.odds_asks a
             WHERE a.provider_fixture_id = f.provider_fixture_id
               AND a.asked_at >= f.kickoff_at - %(lookback)s AND a.asked_at < f.kickoff_at
            UNION ALL
            SELECT b.asked_at FROM market.book_asks b
             WHERE b.provider_fixture_id = f.provider_fixture_id
               AND b.asked_at >= f.kickoff_at - %(lookback)s AND b.asked_at < f.kickoff_at) x) AS last_asked,
       (EXISTS (SELECT 1 FROM market.odds_asks a
                 WHERE a.provider_fixture_id = f.provider_fixture_id AND a.results > 0
                   AND a.asked_at >= f.kickoff_at - %(lookback)s AND a.asked_at < f.kickoff_at)
        OR EXISTS (SELECT 1 FROM market.book_asks b
                    WHERE b.provider_fixture_id = f.provider_fixture_id AND b.results > 0
                      AND b.asked_at >= f.kickoff_at - %(lookback)s AND b.asked_at < f.kickoff_at)) AS priced
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked
   AND f.kickoff_at BETWEEN %(from)s AND %(until)s
   AND f.status_group = 'scheduled'
   AND (lc.odds IS NOT FALSE
        OR EXISTS (SELECT 1 FROM market.odds_mapping_seen m WHERE m.provider_fixture_id = f.provider_fixture_id))
 ORDER BY f.kickoff_at, f.id
"""
"""The matches the capture asks (the WHERE of ``scripts.capture_odds.UPCOMING_SQL``, word for word), with their newest ask of
either table and whether the provider has priced them. The primary keys of both ask tables serve the subqueries."""

SPENT_SQL = """
SELECT greatest(
    (SELECT coalesce(sum(api_calls), 0) FROM raw.ingestion_runs WHERE job_type = %(job)s AND started_at >= %(day)s),
    (SELECT count(*) FROM market.book_asks WHERE asked_at >= %(day)s))
"""
"""What the refreshes spent today: the closed runs' requests, or the asks recorded if more (a run that died never closed)."""

ASK_SQL = """
INSERT INTO market.book_asks (provider_fixture_id, asked_at, minutes_to_ko, window_minutes, results, quotes, payload_hash,
                              run_id)
VALUES (%(pid)s, %(at)s, %(minutes)s, %(point)s, %(results)s, %(quotes)s, %(hash)s, %(run)s)
ON CONFLICT (provider_fixture_id, asked_at) DO NOTHING
"""


# ── what is due (pure) ────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Candidate:
    fixture_id: int
    provider_fixture_id: int
    kickoff_at: datetime
    status_short: str
    last_asked: datetime | None
    priced: bool


@dataclass(frozen=True, slots=True)
class RefreshTask:
    fixture_id: int
    provider_fixture_id: int
    kickoff_at: datetime
    point: int
    """The refresh point this ask serves, in minutes before kick-off."""
    minutes_to_ko: int


def refresh_only_points(windows: Sequence[int]) -> tuple[int, ...]:
    """The refresh points the capture does not ask itself: a model window is the capture's, never asked twice."""
    model = {int(w) for w in windows}
    return tuple(p for p in refresh_points() if p not in model)


def plan(candidates: Sequence[Candidate], *, at: datetime, points: Sequence[int], tolerance: int) -> list[RefreshTask]:
    """The asks due now, nearest to kick-off first. A match is due when a point's band holds its distance to kick-off and it
    was not asked - by the capture or a refresh - since that point's nominal instant. Pure."""
    tasks: list[RefreshTask] = []
    for c in candidates:
        if not c.priced or c.status_short not in PLANNABLE:
            continue
        minutes = minutes_to(c.kickoff_at, at)
        if minutes < MIN_MINUTES_TO_KO:
            continue
        point = due_point(points, minutes, tolerance)
        if point is None:
            continue
        if c.last_asked is not None and c.last_asked >= c.kickoff_at - timedelta(minutes=point):
            continue
        tasks.append(RefreshTask(c.fixture_id, c.provider_fixture_id, c.kickoff_at, point, int(minutes)))
    tasks.sort(key=lambda t: (t.minutes_to_ko, t.fixture_id))
    return tasks


@dataclass(frozen=True, slots=True)
class Budget:
    """What today allows the refreshes, every figure in requests."""

    daily_budget: int
    spent_today: int
    ours_left: int
    provider_left: int | None
    floor: int

    @property
    def allowance(self) -> int:
        """The most the refreshes may ask now: their own budget, and what is left above the floor in ours and the provider's."""
        left = [self.daily_budget - self.spent_today, self.ours_left - self.floor]
        if self.provider_left is not None:
            left.append(self.provider_left - self.floor)
        return max(0, min(left))

    def as_dict(self) -> dict[str, int | None]:
        return {"daily_budget": self.daily_budget, "spent_today": self.spent_today, "ours_left": self.ours_left,
                "provider_left": self.provider_left, "floor": self.floor, "allowance": self.allowance}


def provider_left(reported: ReportedQuota | None, *, at: datetime) -> int | None:
    """What the provider says remains today, when an answer of today (UTC) said it."""
    if reported is None or reported.requests_remaining is None or reported.observed_at.date() != at.date():
        return None
    return reported.requests_remaining


# ── the database ──────────────────────────────────────────────────────────────────────────────────────────────────


def candidates(conn: psycopg.Connection[Any], *, at: datetime, points: Sequence[int], tolerance: int) -> list[Candidate]:
    if not points:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ELIGIBLE_SQL, {"lookback": LOOKBACK, "from": at + timedelta(minutes=MIN_MINUTES_TO_KO),
                                   "until": at + timedelta(minutes=max(points))})
        return [Candidate(int(r["id"]), int(r["provider_fixture_id"]), r["kickoff_at"], str(r["status_short"] or ""),
                          r["last_asked"], bool(r["priced"])) for r in cur.fetchall()]


def spent_today(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SPENT_SQL, {"job": JOB, "day": at.replace(hour=0, minute=0, second=0, microsecond=0)})
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def budget_now(conn: psycopg.Connection[Any], *, at: datetime, daily_budget: int, reserve: int, our_budget: int,
               prematch_windows: Sequence[int]) -> Budget:
    from fbi.ingestion.backfill import live_reserve
    from fbi.providers.quota import read_reported, read_usage

    return Budget(daily_budget=daily_budget, spent_today=spent_today(conn, at=at),
                  ours_left=read_usage(conn, budget=our_budget).remaining,
                  provider_left=provider_left(read_reported(conn, day=at.date()), at=at),
                  floor=reserve + live_reserve(conn, at=at, prematch_windows=prematch_windows))


def record_ask(conn: psycopg.Connection[Any], task: RefreshTask, raws: Sequence[RawResponse], quotes: int,
               run_id: int) -> None:
    asked_at = raws[0].fetched_at
    with conn.cursor() as cur:
        cur.execute(ASK_SQL, {"pid": task.provider_fixture_id, "at": asked_at,
                              "minutes": max(0, int((task.kickoff_at - asked_at).total_seconds() // 60)), "point": task.point,
                              "results": sum(r.results_count for r in raws), "quotes": quotes,
                              "hash": raws[0].payload_hash, "run": run_id})


class OddsSource(Protocol):
    async def fetch_prematch_odds(self, *, provider_fixture_id: int,
                                  kickoff_at: datetime) -> tuple[list[OddsQuote], list[RawResponse]]: ...


@dataclass
class RefreshReport:
    run_id: int | None = None
    due: int = 0
    allowance: int = 0
    asked: int = 0
    priced: int = 0
    empty: int = 0
    api_calls: int = 0
    payloads: int = 0
    fixtures_built: int = 0
    book_rows_written: int = 0
    budget: dict[str, int | None] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    stopped_early: str | None = None
    skipped_locked: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"due": self.due, "allowance": self.allowance, "asked": self.asked, "priced": self.priced,
                "empty": self.empty, "api_calls": self.api_calls, "payloads": self.payloads,
                "fixtures_built": self.fixtures_built, "book_rows_written": self.book_rows_written, "budget": self.budget,
                "errors": self.errors[:10], "stopped_early": self.stopped_early, "skipped_locked": self.skipped_locked}


async def ask_and_build(conn: psycopg.Connection[Any], provider: OddsSource, tasks: Sequence[RefreshTask], *,
                        raw_root: Path | str, report: RefreshReport, floor: int,
                        reported: Callable[[], ReportedQuota | None], build_book: bool = True,
                        at: datetime | None = None, max_seconds: float | None = None) -> RefreshReport:
    """Ask each task once (in the order given) as one ledger run of ``JOB``, record the ask in ``market.book_asks``, then build
    the book of the matches asked. Stops - and says why - on the run's cap or the daily quota, an open circuit, the time budget,
    or the provider's own count falling below ``floor``. A provider error on one match is recorded and the next goes on."""
    from fbi.ingestion.ledger import RunCounters, RunLedger
    from fbi.odds import book

    moment = at or clock_now()
    started = time.monotonic()
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"due": report.due, "allowance": report.allowance, "asks": len(tasks),
                                      "budget": report.budget})
    report.run_id = run_id
    counters = RunCounters()
    asked: list[int] = []
    try:
        for task in tasks:
            if max_seconds is not None and time.monotonic() - started > max_seconds:
                report.stopped_early = f"time budget of {max_seconds:g} s reached"
                break
            try:
                quotes, raws = await provider.fetch_prematch_odds(provider_fixture_id=task.provider_fixture_id,
                                                                  kickoff_at=task.kickoff_at)
            except (QuotaExhaustedError, CircuitOpenError) as exc:
                report.stopped_early = str(exc)[:300]
                break
            except ProviderError as exc:
                report.errors.append(f"fixture {task.fixture_id}: {str(exc)[:200]}")
                continue
            if not raws:
                continue
            report.asked += 1
            report.api_calls += len(raws)
            report.payloads += ledger.record_payloads(run_id, raws)
            record_ask(conn, task, raws, len(quotes), run_id)
            conn.commit()
            if sum(r.results_count for r in raws) > 0:
                report.priced += 1
            else:
                report.empty += 1
            asked.append(task.fixture_id)
            left = reported()
            if left is not None and left.requests_remaining is not None and left.requests_remaining < floor:
                report.stopped_early = (f"the provider says {left.requests_remaining} requests remain today, under the "
                                        f"refreshes' floor of {floor}")
                break
        if asked and build_book:
            built = book.build(conn, raw_root, asked, apply=True, now=moment)
            report.fixtures_built = built.fixtures_seen
            report.book_rows_written = built.rows_inserted + built.rows_updated + built.rows_deleted
            if built.skipped_locked:
                report.errors.append("the book was being built: its next pass builds these matches")
    finally:
        counters.api_calls = report.api_calls
        counters.payloads_stored = report.payloads
        counters.rows_inserted = report.asked
        counters.rows_updated = report.book_rows_written
        counters.errors.extend(report.errors[:5])
        counters.stopped_early = report.stopped_early
        ledger.close(run_id, counters, notes=json.dumps(report.as_dict(), default=str)[:2000])
    log.info("odds_book_refresh.done", **{k: v for k, v in report.as_dict().items() if isinstance(v, (int, bool))})
    return report


def refresh_enabled() -> bool:
    from fbi.core.config import settings

    return settings.odds.book_refresh_enabled


async def run_refresh_job(conn: psycopg.Connection[Any], raw_root: Path | str, *, enabled: bool | None = None,
                          now: datetime | None = None, per_run: int = DEFAULT_PER_RUN,
                          max_seconds: float = DEFAULT_RUN_SECONDS) -> RefreshReport | None:
    """The worker's pass (``odds_book_refresh``). Does NOTHING - not even a query - unless the refreshes are on
    (``FBI_ODDS_BOOK_REFRESH`` and ``FBI_ODDS_BOOK``). Plans what is due, sizes it to today's budget, asks through the real
    provider client (``build_client``: the persistent quota, capped for this run at the allowance) and builds the book of the
    matches asked. A pass with nothing due, or cut by the budget before asking, writes no ledger row (the cut is logged)."""
    if not (refresh_enabled() if enabled is None else enabled):
        return None
    from fbi.core.config import settings
    from fbi.providers.api_football import ApiFootballProvider
    from fbi.providers.api_football.build import build_client

    moment = now or clock_now()
    cfg = settings.odds
    points = refresh_only_points(cfg.prematch_windows)
    report = RefreshReport()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,))
        locked = cur.fetchone()
    if not locked or not locked[0]:
        conn.commit()
        report.skipped_locked = True
        return report
    try:
        tasks = plan(candidates(conn, at=moment, points=points, tolerance=cfg.odds_window_tolerance), at=moment,
                     points=points, tolerance=cfg.odds_window_tolerance)
        report.due = len(tasks)
        if not tasks:
            conn.commit()
            return None
        budget = budget_now(conn, at=moment, daily_budget=cfg.odds_book_daily_budget, reserve=cfg.odds_book_reserve,
                            our_budget=settings.provider_plan.effective_budget, prematch_windows=cfg.prematch_windows)
        conn.commit()
        report.budget = budget.as_dict()
        report.allowance = min(budget.allowance, per_run, len(tasks))
        if report.allowance <= 0:
            report.stopped_early = "the refreshes' budget or the quota floor leaves nothing for them now"
            log.warning("odds_book_refresh.cut", due=len(tasks), **budget.as_dict())
            return report
        client = build_client(report.allowance)
        provider = ApiFootballProvider(client, market_filter=cfg.market_filter)
        try:
            await ask_and_build(conn, provider, tasks[:report.allowance], raw_root=raw_root, report=report,
                                floor=budget.floor, reported=lambda: client.reported_quota, at=moment,
                                max_seconds=max_seconds)
        finally:
            await provider.aclose()
        return report
    finally:
        try:
            if conn.info.transaction_status == TransactionStatus.INERROR:
                conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))
            conn.commit()
        except psycopg.Error as exc:
            log.error("odds_book_refresh.unlock_failed", error=str(exc)[:200])
