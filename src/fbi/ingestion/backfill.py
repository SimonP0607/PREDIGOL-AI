"""Historical backfill: resumable, idempotent, and always behind live capture.

Measured, not assumed: on the free plan ``/fixtures?league=&season=`` serves
the 2022-2024 seasons in full - one request returns a whole season, scores
included - and refuses the current ones. A season of history therefore costs
one request, and the whole backfill of several competitions costs a couple of
dozen. The constraint is not the backfill's size; it is that it draws on the
same daily budget as live odds capture, and a missed odds window is gone for
ever while a season of history will still be there tomorrow.

So every run computes a reserve first - what live capture and the worker's
standing syncs may need over the next 24 hours - and spends only what is left
above it. A run that finds nothing to spare records that it deferred, and
spends nothing.

Work is tracked per unit in raw.backfill_tasks: a run takes pending tasks in
priority order until its allowance is gone; the next run carries on. Applying
a task twice rewrites the same rows (writes are monotonic on payload time).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.errors import ProviderError
from fbi.ingestion.apply import apply_fixtures_payload
from fbi.ingestion.fixtures import PLAN_REFUSAL
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.base import FootballDataProvider
from fbi.providers.quota import read_usage

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 3
RESERVE_MARGIN = 10
"""Requests always left untouched on top of the computed live need."""


@dataclass(frozen=True, slots=True)
class BackfillUnit:
    provider_league_id: int
    season: int
    priority: int


@dataclass
class BackfillReport:
    reserve: int = 0
    remaining_before: int = 0
    allowance: int = 0
    attempted: int = 0
    done: int = 0
    refused: int = 0
    failed: int = 0
    fixtures_written: int = 0
    results_written: int = 0
    deferred_reason: str | None = None
    run_id: int | None = None
    notes: list[str] = field(default_factory=list)


def seed_tasks(conn: psycopg.Connection, units: Iterable[BackfillUnit]) -> int:
    """Add tasks that do not exist yet. Existing tasks keep their state."""
    added = 0
    with conn.cursor() as cur:
        for u in units:
            cur.execute(
                "INSERT INTO raw.backfill_tasks (kind, provider_league_id, season, priority) "
                "VALUES ('fixtures_season', %s, %s, %s) "
                "ON CONFLICT (provider, kind, provider_league_id, season) DO NOTHING RETURNING id",
                (u.provider_league_id, u.season, u.priority),
            )
            if cur.fetchone() is not None:
                added += 1
    conn.commit()
    return added


def live_reserve(
    conn: psycopg.Connection,
    *,
    at: datetime | None = None,
    prematch_windows: Iterable[int] = (4320, 2880, 1440, 720, 360, 180),
    standing_daily: int = 12,
) -> int:
    """Upper bound on what the live path may spend in the next 24 h.

    For every tracked scheduled fixture, one request per pre-match window that
    falls inside the next 24 h, plus one near-close request if it kicks off in
    that time; plus the worker's standing fixtures and results syncs. Deliberately
    generous: over-reserving delays history by a day, under-reserving loses odds.
    """
    moment = at or now()
    until = moment + timedelta(hours=24)
    windows = sorted(set(prematch_windows))
    horizon = until + timedelta(minutes=max(windows) if windows else 0)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT f.kickoff_at FROM core.fixtures f "
            "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
            "JOIN core.competitions c ON c.id = cs.competition_id "
            "WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %s AND %s",
            (moment, horizon),
        )
        kickoffs = [r[0] for r in cur.fetchall()]
    need = 0
    for ko in kickoffs:
        need += sum(1 for w in windows if moment <= ko - timedelta(minutes=w) <= until)
        if moment <= ko <= until:
            need += 1
    return need + standing_daily


def _season_row(conn: psycopg.Connection, league_id: int, season: int) -> int | None:
    """The competition_seasons row for a catalogued competition, created if the
    season is new to us. A competition missing from the catalogue is not invented."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT id FROM core.competitions WHERE provider_league_id = %s", (league_id,))
        comp = cur.fetchone()
        if comp is None:
            return None
        cur.execute(
            "INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, %s, false) "
            "ON CONFLICT (competition_id, season) DO NOTHING",
            (int(comp[0]), season),
        )
        cur.execute(
            "SELECT id FROM core.competition_seasons WHERE competition_id = %s AND season = %s",
            (int(comp[0]), season),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None


def _pending(conn: psycopg.Connection, limit: int) -> list[tuple[int, int, int]]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT id, provider_league_id, season FROM raw.backfill_tasks "
            "WHERE status = 'pending' OR (status = 'failed' AND attempts < %s) "
            "ORDER BY priority, provider_league_id, season DESC LIMIT %s",
            (MAX_ATTEMPTS, limit),
        )
        return [(int(a), int(b), int(c)) for a, b, c in cur.fetchall()]


def progress(conn: psycopg.Connection) -> dict[str, int]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT status, count(*) FROM raw.backfill_tasks GROUP BY status")
        return {str(k): int(v) for k, v in cur.fetchall()}


async def run_backfill(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    *,
    max_requests: int,
    daily_budget: int,
    prematch_windows: Iterable[int] = (4320, 2880, 1440, 720, 360, 180),
    at: datetime | None = None,
) -> BackfillReport:
    """Spend at most ``max_requests`` - and never the live reserve - on pending tasks."""
    moment = at or now()
    report = BackfillReport()
    report.reserve = live_reserve(conn, at=moment, prematch_windows=prematch_windows) + RESERVE_MARGIN
    report.remaining_before = read_usage(conn, budget=daily_budget).remaining
    report.allowance = max(0, min(max_requests, report.remaining_before - report.reserve))
    tasks = _pending(conn, report.allowance) if report.allowance else []
    if not tasks:
        report.deferred_reason = (
            "nothing pending" if report.allowance and not tasks
            else f"live capture reserve: {report.remaining_before} remaining, {report.reserve} reserved"
        )
        log.info("backfill.deferred", reason=report.deferred_reason)
        return report

    ledger = RunLedger(conn)
    run_id = ledger.open("historical_backfill", params={"allowance": report.allowance, "reserve": report.reserve},
                         scheduled_for=moment)
    report.run_id = run_id
    counters = RunCounters()
    try:
        for task_id, league_id, season in tasks:
            report.attempted += 1
            season_id = _season_row(conn, league_id, season)
            if season_id is None:
                _mark(conn, task_id, "refused", run_id, error=f"competition {league_id} is not in the catalogue")
                report.refused += 1
                continue
            try:
                _, raw = await provider.fetch_fixtures(league_id=league_id, season=season)
            except ProviderError as exc:
                counters.api_calls += 1
                message = str(exc)
                if PLAN_REFUSAL in message:
                    _mark(conn, task_id, "refused", run_id, error=message)
                    report.refused += 1
                    report.notes.append(f"{league_id}/{season}: refused by the plan")
                else:
                    _mark(conn, task_id, "failed", run_id, error=message)
                    counters.errors.append(f"{league_id}/{season}: {message}")
                    report.failed += 1
                continue
            counters.api_calls += 1
            counters.payloads_stored += ledger.record_payloads(run_id, [raw])
            outcome = apply_fixtures_payload(
                conn, provider, raw.body, payload_hash=raw.payload_hash, fetched_at=raw.fetched_at,
                season_ids={(league_id, season): season_id},
            )
            counters.rows_normalized += outcome.ours
            counters.rows_inserted += outcome.fixtures_inserted
            counters.rows_updated += outcome.fixtures_updated + outcome.results_written
            _mark(conn, task_id, "done", run_id, payload_hash=raw.payload_hash, seen=outcome.ours,
                  written=outcome.fixtures_inserted + outcome.fixtures_updated, results=outcome.results_written)
            conn.commit()
            report.done += 1
            report.fixtures_written += outcome.fixtures_inserted + outcome.fixtures_updated
            report.results_written += outcome.results_written
            log.info("backfill.season_done", league=league_id, season=season, fixtures=outcome.ours,
                     results=outcome.results_written)
    finally:
        ledger.close(run_id, counters, notes=f"{report.done} done, {report.refused} refused, {report.failed} failed")
    return report


def _mark(
    conn: psycopg.Connection,
    task_id: int,
    status: str,
    run_id: int,
    *,
    error: str | None = None,
    payload_hash: str | None = None,
    seen: int | None = None,
    written: int | None = None,
    results: int | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE raw.backfill_tasks SET status = %s, attempts = attempts + 1, last_run_id = %s, "
            "last_error = %s, last_payload_hash = COALESCE(%s, last_payload_hash), "
            "fixtures_seen = COALESCE(%s, fixtures_seen), fixtures_written = COALESCE(%s, fixtures_written), "
            "results_written = COALESCE(%s, results_written), updated_at = now(), "
            "completed_at = CASE WHEN %s = 'done' THEN now() ELSE completed_at END WHERE id = %s",
            (status, run_id, error, payload_hash, seen, written, results, status, task_id),
        )
    conn.commit()
