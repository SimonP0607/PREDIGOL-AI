"""Historical backfill: resumable, idempotent, and always behind live capture.

Measured, not assumed: on the free plan ``/fixtures?league=&season=`` serves
the 2022-2024 seasons in full - one request returns a whole season, scores
included - and refuses the current ones. The constraint is not the
backfill's size; it is that it draws on the same daily budget as live odds
capture, and a missed odds window is gone for ever while a season of history
will still be there tomorrow.

So every run computes a reserve first - what live capture and the worker's
standing syncs may need over the next 24 hours - and spends only what is left
above it. A run that finds nothing to spare records that it deferred, and
spends nothing.

Work is tracked per unit in raw.backfill_tasks, one request per unit, of seven
kinds (the historical migration, docs/rebuild/API_FOOTBALL_MIGRATION_PLAN.md):
the provider's coverage flags, a competition-season of fixtures, the detail of
up to twenty fixtures (/fixtures?ids=: events, lineups, statistics, player
statistics), standings, injuries, teams and pages of season player stats. A
run takes units in tier and priority order until its allowance is gone; the
next run carries on - including after a crash, which leaves a unit 'running'
and is picked up again once it is stale. Applying a unit twice rewrites the
same rows (writes are monotonic on payload time).

Some units create others: a season's fixtures, once stored, become batches of
twenty for the detail requests, and the first page of season players tells how
many pages follow.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
import structlog
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.core.clock import now
from fbi.core.errors import ProviderError
from fbi.ingestion.apply import apply_fixtures_payload
from fbi.ingestion.details import (
    apply_coverage,
    apply_fixture_details,
    apply_injuries,
    apply_standings,
)
from fbi.ingestion.fixtures import PLAN_REFUSAL
from fbi.ingestion.identity import apply_teams
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.migration.completeness import fixtures_missing_detail
from fbi.providers.api_football.details import iter_teams
from fbi.providers.base import FootballDataProvider, RawResponse
from fbi.providers.quota import read_usage

log = structlog.get_logger(__name__)

MAX_ATTEMPTS = 3
RESERVE_MARGIN = 10
"""Requests always left untouched on top of the computed live need."""
STALE_RUNNING = timedelta(minutes=30)
"""A unit 'running' for longer than this belonged to a process that died."""
DETAIL_BATCH = 20
KIND_ORDER = ("league_coverage", "fixtures_season", "fixture_details", "standings_season", "injuries_season",
              "teams_season", "players_season")


@dataclass(frozen=True, slots=True)
class BackfillUnit:
    provider_league_id: int
    season: int
    priority: int


@dataclass(frozen=True, slots=True)
class Task:
    id: int
    kind: str
    league_id: int
    season: int
    page: int | None
    batch_key: str | None
    params: dict[str, Any]
    tier: int | None
    plan_id: int | None
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
    rows_written: int = 0
    units_created: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    deferred_reason: str | None = None
    run_id: int | None = None
    notes: list[str] = field(default_factory=list)


def seed_tasks(conn: psycopg.Connection, units: Iterable[BackfillUnit]) -> int:
    """Add fixtures-season tasks that do not exist yet. Existing tasks keep their state."""
    added = 0
    with conn.cursor() as cur:
        for u in units:
            cur.execute(
                "INSERT INTO raw.backfill_tasks (kind, provider_league_id, season, priority, endpoint, params) "
                "VALUES ('fixtures_season', %s, %s, %s, '/fixtures', %s) ON CONFLICT DO NOTHING RETURNING id",
                (u.provider_league_id, u.season, u.priority,
                 Json({"league": u.provider_league_id, "season": u.season})),
            )
            if cur.fetchone() is not None:
                added += 1
    conn.commit()
    return added


def add_unit(cur: psycopg.Cursor[Any], *, kind: str, league_id: int, season: int, endpoint: str,
             params: dict[str, Any], priority: int, tier: int | None = None, plan_id: int | None = None,
             page: int | None = None, batch_key: str | None = None) -> bool:
    """Insert one unit unless an identical one exists. Returns True when created."""
    cur.execute(
        "INSERT INTO raw.backfill_tasks (kind, provider_league_id, season, priority, endpoint, params, page, "
        "batch_key, tier, plan_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
        (kind, league_id, season, priority, endpoint, Json(params), page, batch_key, tier, plan_id),
    )
    return cur.fetchone() is not None


def expand_detail_batches(conn: psycopg.Connection, *, league_id: int, season: int, priority: int,
                          tier: int | None = None, plan_id: int | None = None) -> int:
    """Detail units for played fixtures whose detail has NEVER been fetched,
    twenty per unit, in kick-off order.

    What counts as "already handled" used to be the batch keys of
    ``raw.backfill_tasks``, read regardless of their status - so a unit that was
    pending, failed or refused counted as covered and was never regenerated, and
    a season whose fixtures a previous plan had stored got no units at all.

    It is now ``core.fixture_detail_coverage``: a fixture is skipped when a
    payload has actually been applied for it, and only then. That also keeps the
    work finite - a dataset the provider does not publish has a row saying so and
    is not requested again.
    """
    todo = fixtures_missing_detail(conn, league_id=league_id, season=season)
    created = 0
    with conn.cursor(row_factory=tuple_row) as cur:
        for k in range(0, len(todo), DETAIL_BATCH):
            batch = sorted(todo[k:k + DETAIL_BATCH])
            key = "-".join(str(i) for i in batch)
            if add_unit(cur, kind="fixture_details", league_id=league_id, season=season,
                        endpoint="/fixtures", params={"ids": key}, priority=priority, tier=tier,
                        plan_id=plan_id, batch_key=key):
                created += 1
                continue
            created += _revive(cur, kind="fixture_details", league_id=league_id, season=season,
                               batch_key=key)
    conn.commit()
    return created


def _competition_season_id(conn: psycopg.Connection, league_id: int, season: int) -> int | None:
    """Our competition-season id for a provider league and season, or None.

    None means the catalogue does not hold that season, in which case team
    membership is not recorded - a membership we cannot attach to a season we know
    would be a row with no meaning.
    """
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT cs.id FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id "
            "WHERE c.provider_league_id = %s AND cs.season = %s",
            (league_id, season),
        )
        row = cur.fetchone()
    return int(row[0]) if row else None


def _revive(cur: psycopg.Cursor[Any], *, kind: str, league_id: int, season: int,
            batch_key: str | None) -> int:
    """Put a retryable unit that failed back in the queue. Returns 1 if it moved.

    Without this, "regenerate what is missing" could not regenerate anything: the
    unique key already holds a row, so the insert does nothing, and the fixtures
    stay uncovered for ever. A unit marked ``refused`` is left alone - the
    provider or the plan said no, and asking again in a loop is how quota is
    wasted - and so is one already ``pending`` or ``running``.
    """
    cur.execute(
        "UPDATE raw.backfill_tasks SET status = 'pending', started_at = NULL, updated_at = now() "
        "WHERE kind = %s AND provider_league_id = %s AND season = %s "
        "  AND coalesce(batch_key, '') = coalesce(%s, '') "
        "  AND status = 'failed' AND retryable",
        (kind, league_id, season, batch_key),
    )
    return 1 if cur.rowcount == 1 else 0


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


_ORDER_SQL = "CASE kind " + " ".join(f"WHEN '{k}' THEN {i}" for i, k in enumerate(KIND_ORDER)) + " END"


def _pending(conn: psycopg.Connection, limit: int, *, at: datetime) -> list[Task]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT id, kind, provider_league_id, season, page, batch_key, params, tier, plan_id, priority "
            "FROM raw.backfill_tasks "
            "WHERE status = 'pending' OR (status = 'failed' AND retryable AND attempts < %s) "
            "OR (status = 'running' AND started_at < %s) "
            f"ORDER BY COALESCE(tier, 0), priority, {_ORDER_SQL}, provider_league_id, season DESC, "
            "page NULLS FIRST, id LIMIT %s",
            (MAX_ATTEMPTS, at - STALE_RUNNING, limit),
        )
        return [Task(int(a), str(b), int(c), int(d), e, f, dict(g or {}), h, i, int(j))
                for a, b, c, d, e, f, g, h, i, j in cur.fetchall()]


def progress(conn: psycopg.Connection) -> dict[str, int]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT status, count(*) FROM raw.backfill_tasks GROUP BY status")
        return {str(k): int(v) for k, v in cur.fetchall()}


@dataclass
class _Outcome:
    payload_hash: str | None = None
    rows: int = 0
    seen: int | None = None
    written: int | None = None
    results: int | None = None
    created: int = 0


class _RefusedError(Exception):
    """Retrying cannot help: the unit is recorded as refused, with this reason."""


async def _execute(conn: psycopg.Connection, provider: Any, ledger: RunLedger, run_id: int, task: Task,
                   counters: RunCounters) -> _Outcome:
    def stored(raw: RawResponse) -> None:
        counters.api_calls += 1
        counters.payloads_stored += ledger.record_payloads(run_id, [raw])

    if task.kind == "fixtures_season":
        season_id = _season_row(conn, task.league_id, task.season)
        if season_id is None:
            raise _RefusedError(f"competition {task.league_id} is not in the catalogue")
        _, raw = await provider.fetch_fixtures(league_id=task.league_id, season=task.season)
        stored(raw)
        outcome = apply_fixtures_payload(conn, provider, raw.body, payload_hash=raw.payload_hash,
                                         fetched_at=raw.fetched_at, season_ids={(task.league_id, task.season): season_id})
        counters.rows_normalized += outcome.ours
        counters.rows_inserted += outcome.fixtures_inserted
        counters.rows_updated += outcome.fixtures_updated + outcome.results_written
        written = outcome.fixtures_inserted + outcome.fixtures_updated
        out = _Outcome(raw.payload_hash, written + outcome.results_written, outcome.ours, written,
                       outcome.results_written)
        if task.params.get("then_details"):
            conn.commit()
            out.created = expand_detail_batches(conn, league_id=task.league_id, season=task.season,
                                                priority=task.priority + 1, tier=task.tier, plan_id=task.plan_id)
        return out
    if task.kind == "fixture_details":
        ids = [int(x) for x in str(task.batch_key or "").split("-") if x]
        details, raw = await provider.fetch_fixture_details(provider_fixture_ids=ids)
        stored(raw)
        # The INDEX's time, not the response's. Identical bytes are stored once and
        # keep their first fetch time, so using the response's later time would make
        # these rows newer than the payload they name - which is what left 1,809
        # fixtures looking as though they had no detail at all.
        observed_at = ledger.indexed_at(raw.payload_hash) or raw.fetched_at
        rep = apply_fixture_details(conn, details, payload_hash=raw.payload_hash,
                                    fetched_at=observed_at, run_id=run_id)
        counters.rows_normalized += rep.fixtures
        counters.rows_inserted += rep.rows
        if rep.unknown_stat_types:
            # Also in audit.data_quality_issues now: a log line disappears, and a
            # new provider field must not look like one we never received.
            log.info("details.unknown_stat_types", types=sorted(rep.unknown_stat_types))
        return _Outcome(raw.payload_hash, rep.rows, len(details), rep.fixtures, None)
    if task.kind == "standings_season":
        refs, raw = await provider.fetch_standings(league_id=task.league_id, season=task.season)
        stored(raw)
        n = apply_standings(conn, refs, fetched_at=raw.fetched_at, payload_hash=raw.payload_hash)
        counters.rows_inserted += n
        return _Outcome(raw.payload_hash, n, len(refs))
    if task.kind == "injuries_season":
        absences, raw = await provider.fetch_injuries(league_id=task.league_id, season=task.season)
        stored(raw)
        n = apply_injuries(conn, absences, payload_hash=raw.payload_hash, fetched_at=raw.fetched_at)
        counters.rows_inserted += n
        return _Outcome(raw.payload_hash, n, len(absences))
    if task.kind == "teams_season":
        raw = await provider.fetch_teams(league_id=task.league_id, season=task.season)
        stored(raw)
        teams = list(iter_teams(raw.body)) if isinstance(raw.body, dict) else []
        identity = apply_teams(
            conn, teams, payload_hash=raw.payload_hash, fetched_at=raw.fetched_at,
            competition_season_id=_competition_season_id(conn, task.league_id, task.season),
        )
        counters.rows_normalized += len(teams)
        counters.rows_inserted += identity.rows
        return _Outcome(raw.payload_hash, identity.rows, raw.results_count, len(teams))
    if task.kind == "players_season":
        page = task.page or 1
        raw = await provider.fetch_players_page(league_id=task.league_id, season=task.season, page=page)
        stored(raw)
        created = 0
        paging = raw.body.get("paging") if isinstance(raw.body, dict) else None
        total = paging.get("total") if isinstance(paging, dict) else None
        if page == 1 and isinstance(total, int) and total > 1:
            with conn.cursor() as cur:
                for p in range(2, total + 1):
                    created += add_unit(cur, kind="players_season", league_id=task.league_id, season=task.season,
                                        endpoint="/players", params={"league": task.league_id,
                                                                     "season": task.season, "page": p},
                                        priority=task.priority, tier=task.tier, plan_id=task.plan_id, page=p)
        return _Outcome(raw.payload_hash, 0, raw.results_count, created=created)
    if task.kind == "league_coverage":
        refs, raw = await provider.fetch_coverage(league_id=task.league_id or None)
        stored(raw)
        n = apply_coverage(conn, refs, payload_hash=raw.payload_hash, fetched_at=raw.fetched_at)
        counters.rows_inserted += n
        return _Outcome(raw.payload_hash, n, len(refs))
    raise _RefusedError(f"unknown unit kind {task.kind}")


async def run_backfill(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    *,
    max_requests: int,
    daily_budget: int,
    prematch_windows: Iterable[int] = (4320, 2880, 1440, 720, 360, 180),
    at: datetime | None = None,
) -> BackfillReport:
    """Spend at most ``max_requests`` - and never the live reserve - on pending units."""
    moment = at or now()
    report = BackfillReport()
    report.reserve = live_reserve(conn, at=moment, prematch_windows=prematch_windows) + RESERVE_MARGIN
    report.remaining_before = read_usage(conn, budget=daily_budget).remaining
    report.allowance = max(0, min(max_requests, report.remaining_before - report.reserve))
    tasks = _pending(conn, report.allowance, at=moment) if report.allowance else []
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
        for task in tasks:
            report.attempted += 1
            _start(conn, task.id)
            try:
                out = await _execute(conn, provider, ledger, run_id, task, counters)
            except _RefusedError as exc:
                _mark(conn, task.id, "refused", run_id, error=str(exc), retryable=False)
                report.refused += 1
                continue
            except ProviderError as exc:
                counters.api_calls += 1
                message = str(exc)
                if PLAN_REFUSAL in message:
                    _mark(conn, task.id, "refused", run_id, error=message, retryable=False, requests=1)
                    report.refused += 1
                    report.notes.append(f"{task.kind} {task.league_id}/{task.season}: refused by the plan")
                else:
                    _mark(conn, task.id, "failed", run_id, error=message, requests=1)
                    counters.errors.append(f"{task.kind} {task.league_id}/{task.season}: {message}")
                    report.failed += 1
                continue
            except (ValueError, psycopg.Error) as exc:
                conn.rollback()
                _mark(conn, task.id, "failed", run_id, error=f"{type(exc).__name__}: {exc}"[:500], requests=1)
                counters.errors.append(f"{task.kind} {task.league_id}/{task.season}: {type(exc).__name__}")
                report.failed += 1
                continue
            _mark(conn, task.id, "done", run_id, payload_hash=out.payload_hash, seen=out.seen, written=out.written,
                  results=out.results, rows=out.rows, requests=1)
            conn.commit()
            report.done += 1
            report.rows_written += out.rows
            report.units_created += out.created
            report.by_kind[task.kind] = report.by_kind.get(task.kind, 0) + 1
            if task.kind == "fixtures_season":
                report.fixtures_written += out.written or 0
                report.results_written += out.results or 0
                log.info("backfill.season_done", league=task.league_id, season=task.season, fixtures=out.seen,
                         results=out.results, detail_units=out.created)
    finally:
        ledger.close(run_id, counters, notes=f"{report.done} done, {report.refused} refused, {report.failed} failed")
    return report


def _start(conn: psycopg.Connection, task_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE raw.backfill_tasks SET status = 'running', started_at = now(), updated_at = now() "
                    "WHERE id = %s", (task_id,))
    conn.commit()


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
    rows: int | None = None,
    requests: int = 0,
    retryable: bool = True,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE raw.backfill_tasks SET status = %s, attempts = attempts + 1, last_run_id = %s, "
            "last_error = %s, last_payload_hash = COALESCE(%s, last_payload_hash), "
            "fixtures_seen = COALESCE(%s, fixtures_seen), fixtures_written = COALESCE(%s, fixtures_written), "
            "results_written = COALESCE(%s, results_written), rows_written = COALESCE(%s, rows_written), "
            "requests_spent = requests_spent + %s, retryable = %s, updated_at = now(), "
            "completed_at = CASE WHEN %s = 'done' THEN now() ELSE completed_at END WHERE id = %s",
            (status, run_id, error, payload_hash, seen, written, results, rows, requests, retryable, status,
             task_id),
        )
    conn.commit()
