"""The pre-match line-up watch (IA-069, plan piece AD-D05): every few minutes from T-90 to kick-off, in shadow.

WHY: the line-up is the moment the rest of the plan waits for (AD-D06's E3), and today it is read late and coarsely: the
pre-match read asks every 10 minutes in the last 75 (``fbi.ingestion.live_match.refresh_prematch_lineups``) and stops once
both sides are in; the follow starts 2 minutes before kick-off. The arrival is therefore known to 10 minutes at best, and a
starter corrected after the first read is not seen until the follow.

WHAT IT DOES, IN SHADOW: for every tracked match that kicks off in the next 90 minutes, one ``/fixtures?ids=`` request per 20
matches (the same request the follow makes), every ``FBI_LINEUP_WATCH_MINUTES`` (3 by default). Each side's line-up it reads is
recorded in ``core.fixture_lineup_arrivals`` with ``channel = 'lineup_watch'`` - change-only, like the detail writers'
arrivals (``fbi.ingestion.lineup_arrivals``). It writes NOTHING else: not ``core.fixture_lineups``, not the fixture, not the
live state, not the detail. What the Match Center, the agents, the picks and ``decision-v1`` read is exactly what they read
without it. The bodies go to RAW and to the payload index under this job's ledger run, through the real client (the
persistent daily quota, the minute limiter, the provider's headers).

ITS BUDGET, CUT FIRST: at most ``FBI_LINEUP_WATCH_DAILY_BUDGET`` requests a UTC day (1,200 by default: the busiest day of the
30 measured needed 752 at 3 minutes), inside the shared daily quota, never when fewer than ``FBI_LINEUP_WATCH_RESERVE`` (6,000)
plus the next 24 h of capture windows (``fbi.ingestion.backfill.live_reserve``) are left - in our budget or in what the
provider's own headers say remains - and at most ``FBI_LINEUP_WATCH_PER_RUN`` requests a pass (8: 160 matches; the busiest
5-minute slot measured had 122 due). It also stops mid-pass as soon as the provider's count falls below that floor. Matches
nearest to kick-off go first when the allowance is short.

OFF BY DEFAULT: ``FBI_LINEUP_WATCH`` = ``off`` (the default; anything not understood is ``off``) or ``shadow``. Off, the worker
does not even schedule the job. A pass with nothing due writes no ledger row.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Literal, Protocol

import psycopg
import structlog
from psycopg.pq import TransactionStatus
from psycopg.rows import tuple_row

from fbi.core.clock import now as clock_now
from fbi.core.errors import ProviderError, QuotaExhaustedError
from fbi.ingestion.details import LOCK_PREFIX
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.ingestion.lineup_arrivals import record_arrivals
from fbi.providers.api_football.details import FixtureDetail
from fbi.providers.base import RawResponse
from fbi.providers.quota import ReportedQuota

log = structlog.get_logger(__name__)

JOB: Final = "lineup_watch"
LOCK_KEY: Final = "fbi.lineup_watch"
MAX_IDS: Final = 20
"""What one ``/fixtures?ids=`` takes (``fbi.providers.api_football.provider.MAX_IDS``)."""
WINDOW: Final = timedelta(minutes=90)
"""From T-90 to kick-off (the ficha of AD-D05). The measured arrival: 20 min before kick-off at the median, 76 % before it."""

Mode = Literal["off", "shadow"]


@dataclass(frozen=True, slots=True)
class WatchSettings:
    mode: Mode = "off"
    every_minutes: int = 3
    daily_budget: int = 1_200
    reserve: int = 6_000
    per_run: int = 8

    @property
    def enabled(self) -> bool:
        return self.mode == "shadow"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> WatchSettings:
        """The switch and its numbers from the environment. Anything not understood falls back to the default (and the
        switch to ``off``): a typo can never turn the watch on or widen its budget."""
        raw = env.get("FBI_LINEUP_WATCH", "off").strip().lower()
        mode: Mode = "shadow" if raw == "shadow" else "off"

        def number(name: str, default: int, low: int, high: int) -> int:
            try:
                value = int(env.get(name, str(default)).strip())
            except ValueError:
                return default
            return value if low <= value <= high else default

        return cls(mode=mode, every_minutes=number("FBI_LINEUP_WATCH_MINUTES", 3, 1, 30),
                   daily_budget=number("FBI_LINEUP_WATCH_DAILY_BUDGET", 1_200, 1, 6_000),
                   reserve=number("FBI_LINEUP_WATCH_RESERVE", 6_000, 0, 1_000_000),
                   per_run=number("FBI_LINEUP_WATCH_PER_RUN", 8, 1, 50))


def watch_settings() -> WatchSettings:
    import os

    return WatchSettings.from_env(os.environ)


# ── what is due and what today allows (pure) ──────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Due:
    fixture_id: int
    provider_fixture_id: int
    kickoff_at: datetime


def batches(due: Sequence[Due], *, size: int = MAX_IDS) -> list[list[Due]]:
    """Nearest kick-off first, in groups of ``size`` (one request each). Pure."""
    ordered = sorted(due, key=lambda d: (d.kickoff_at, d.fixture_id))
    return [ordered[i:i + size] for i in range(0, len(ordered), size)]


@dataclass(frozen=True, slots=True)
class Budget:
    """What today allows the watch, every figure in requests."""

    daily_budget: int
    spent_today: int
    ours_left: int
    provider_left: int | None
    floor: int

    @property
    def allowance(self) -> int:
        """The most the watch may ask now: its own budget, and what is left above the floor in ours and the provider's."""
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


def requests_per_day(due_per_slot: Sequence[int], *, size: int = MAX_IDS) -> int:
    """What a day of passes costs: one request per ``size`` matches due in each pass. Pure (the sizing in the owner's guide)."""
    return sum(-(-n // size) for n in due_per_slot if n > 0)


# ── the database ──────────────────────────────────────────────────────────────────────────────────────────────────────

DUE_SQL = """
SELECT f.id, f.provider_fixture_id, f.kickoff_at
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.status_group = 'scheduled'
   AND f.kickoff_at > %(at)s AND f.kickoff_at <= %(at)s + %(window)s
 ORDER BY f.kickoff_at, f.id
"""

SPENT_SQL = """
SELECT greatest(
    (SELECT coalesce(sum(api_calls), 0) FROM raw.ingestion_runs WHERE job_type = %(job)s AND started_at >= %(day)s),
    (SELECT count(*) FROM raw.ingestion_payloads p JOIN raw.ingestion_runs r ON r.id = p.run_id
      WHERE r.job_type = %(job)s AND r.started_at >= %(day)s))
"""
"""What the watch spent today: the closed runs' requests, or the payloads its runs indexed if more (a run that died never
closed)."""

SIDES_SQL = """
SELECT f.provider_fixture_id, f.id, th.provider_team_id, ta.provider_team_id
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.provider_fixture_id = ANY(%(ids)s)
"""


def due_now(conn: psycopg.Connection[Any], *, at: datetime) -> list[Due]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(DUE_SQL, {"at": at, "window": WINDOW})
        return [Due(int(a), int(b), c) for a, b, c in cur.fetchall()]


def spent_today(conn: psycopg.Connection[Any], *, at: datetime) -> int:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SPENT_SQL, {"job": JOB, "day": at.replace(hour=0, minute=0, second=0, microsecond=0)})
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def budget_now(conn: psycopg.Connection[Any], *, at: datetime, cfg: WatchSettings) -> Budget:
    from fbi.core.config import settings
    from fbi.ingestion.backfill import live_reserve
    from fbi.providers.quota import read_reported, read_usage

    return Budget(daily_budget=cfg.daily_budget, spent_today=spent_today(conn, at=at),
                  ours_left=read_usage(conn, budget=settings.provider_plan.effective_budget).remaining,
                  provider_left=provider_left(read_reported(conn, day=at.date()), at=at),
                  floor=cfg.reserve + live_reserve(conn, at=at, prematch_windows=settings.odds.prematch_windows))


def record_observations(conn: psycopg.Connection[Any], details: Sequence[FixtureDetail], *, observed_at: datetime,
                        payload_hash: str, run_id: int | None) -> int:
    """The line-ups one answer carried, as arrivals of the watch, and nothing else. Takes the detail writers' lock per
    fixture (ascending), so a watch and a follow on the same match take turns. Rows added; the caller commits."""
    wanted = [d for d in details if "lineups" in d.blocks_present and d.lineups]
    if not wanted:
        return 0
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SIDES_SQL, {"ids": sorted({d.provider_fixture_id for d in wanted})})
        sides = {int(p): (int(f), int(h), int(a)) for p, f, h, a in cur.fetchall()}
        for fixture_id in sorted({v[0] for v in sides.values()}):
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"{LOCK_PREFIX}{fixture_id}",))
        added = 0
        for d in wanted:
            known = sides.get(d.provider_fixture_id)
            if known is None:
                continue
            fixture_id, home, away = known
            added += record_arrivals(cur, fixture_id=fixture_id, home=home, away=away, lineups=d.lineups,
                                     observed_at=observed_at, payload_hash=payload_hash, channel="lineup_watch",
                                     run_id=run_id)
    return added


# ── the pass ──────────────────────────────────────────────────────────────────────────────────────────────────────────


class DetailSource(Protocol):
    async def fetch_fixture_details(self, *, provider_fixture_ids: list[int]) -> tuple[list[FixtureDetail], RawResponse]: ...


@dataclass
class WatchReport:
    mode: str = "off"
    due: int = 0
    batches_due: int = 0
    allowance: int = 0
    requests: int = 0
    fixtures_read: int = 0
    arrivals: int = 0
    errors: list[str] = field(default_factory=list)
    stopped_early: str | None = None
    budget: dict[str, int | None] = field(default_factory=dict)
    skipped_locked: bool = False
    run_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


async def watch(conn: psycopg.Connection[Any], provider: DetailSource, groups: Sequence[Sequence[Due]], *,
                report: WatchReport, moment: datetime, floor: int,
                reported: Callable[[], ReportedQuota | None] = lambda: None) -> WatchReport:
    """Ask each group once, nearest kick-off first, and record the line-ups it carried. Stops when the provider's count of
    today falls below ``floor`` or the client refuses for quota."""
    ledger = RunLedger(conn)
    run_id = ledger.open(JOB, params={"fixtures": sum(len(g) for g in groups), "batches": len(groups)},
                         scheduled_for=moment)
    report.run_id = run_id
    counters = RunCounters()
    try:
        for n, group in enumerate(groups):
            left = provider_left(reported(), at=moment)
            if left is not None and left < floor:
                report.stopped_early = f"the provider says {left} requests remain today, below the floor of {floor}"
                break
            ids = [d.provider_fixture_id for d in group]
            try:
                details, raw = await provider.fetch_fixture_details(provider_fixture_ids=ids)
            except QuotaExhaustedError as exc:
                report.stopped_early = f"quota: {exc}"[:300]
                break
            except ProviderError as exc:
                report.requests += 1
                counters.api_calls += 1
                report.errors.append(str(exc)[:300])
                counters.errors.append(str(exc)[:300])
                log.warning("lineup_watch.fetch_failed", error=str(exc)[:200])
                continue
            report.requests += 1
            counters.api_calls += 1
            counters.payloads_stored += ledger.record_payloads(run_id, [raw])
            observed_at = ledger.indexed_at(raw.payload_hash) or raw.fetched_at
            added = record_observations(conn, details, observed_at=observed_at, payload_hash=raw.payload_hash,
                                        run_id=run_id)
            conn.commit()
            report.fixtures_read += len(details)
            report.arrivals += added
            if n + 1 < len(groups):
                ledger.beat(run_id)
        counters.rows_normalized = report.fixtures_read
        counters.rows_inserted = report.arrivals
        counters.stopped_early = report.stopped_early
    finally:
        if conn.info.transaction_status == TransactionStatus.INERROR:
            conn.rollback()
        ledger.close(run_id, counters, notes=json.dumps(report.as_dict(), default=str)[:2000])
        conn.commit()
    log.info("lineup_watch.done", due=report.due, requests=report.requests, arrivals=report.arrivals,
             stopped_early=report.stopped_early)
    return report


async def run_watch_job(conn: psycopg.Connection[Any], *, cfg: WatchSettings | None = None, now: datetime | None = None,
                        provider: DetailSource | None = None, budget: Budget | None = None) -> WatchReport | None:
    """The worker's pass (``lineup_watch``). Does NOTHING - not even a query - unless ``FBI_LINEUP_WATCH=shadow``. Lists
    what is due, sizes it to today's budget and asks through the real provider client (``build_client``: the persistent
    quota, capped for this pass at the allowance). A pass with nothing due writes no ledger row; one cut by the budget
    before asking writes none either (the cut is logged). ``provider`` and ``budget`` are for tests."""
    cfg = cfg or watch_settings()
    if not cfg.enabled:
        return None
    moment = now or clock_now()
    report = WatchReport(mode=cfg.mode)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (LOCK_KEY,))
        locked = cur.fetchone()
    if not locked or not locked[0]:
        conn.commit()
        report.skipped_locked = True
        return report
    try:
        due = due_now(conn, at=moment)
        report.due = len(due)
        if not due:
            conn.commit()
            return None
        groups = batches(due)
        report.batches_due = len(groups)
        budget = budget or budget_now(conn, at=moment, cfg=cfg)
        conn.commit()
        report.budget = budget.as_dict()
        report.allowance = min(budget.allowance, cfg.per_run, len(groups))
        if report.allowance <= 0:
            report.stopped_early = "the watch's budget or the quota floor leaves nothing for it now"
            log.warning("lineup_watch.cut", due=len(due), **budget.as_dict())
            return report
        if len(groups) > report.allowance:
            log.warning("lineup_watch.partial", due=len(due), batches=len(groups), allowance=report.allowance)
        if provider is not None:
            return await watch(conn, provider, groups[:report.allowance], report=report, moment=moment,
                               floor=budget.floor)
        from fbi.providers.api_football import ApiFootballProvider
        from fbi.providers.api_football.build import build_client

        client = build_client(report.allowance)
        real = ApiFootballProvider(client)
        try:
            return await watch(conn, real, groups[:report.allowance], report=report, moment=moment, floor=budget.floor,
                               reported=lambda: client.reported_quota)
        finally:
            await real.aclose()
    finally:
        try:
            if conn.info.transaction_status == TransactionStatus.INERROR:
                conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (LOCK_KEY,))
            conn.commit()
        except psycopg.Error as exc:
            log.error("lineup_watch.unlock_failed", error=str(exc)[:200])
