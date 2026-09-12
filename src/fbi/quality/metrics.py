"""Data quality foundation: the numbers behind the P0 Data Quality screen.

Every metric is computed from what is actually stored - the fixtures table,
the odds series, the ledger - never from a counter somebody increments. A
metric that cannot be computed says so with a null, the same rule the schema
applies to ROI.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.core.clock import now

STALE_CAPTURE_AFTER = timedelta(hours=4)  # /odds refreshes every 3 h; beyond 4 h something is wrong


@dataclass(frozen=True, slots=True)
class CoverageMetric:
    expected: int
    available: int

    @property
    def ratio(self) -> float | None:
        return None if self.expected == 0 else round(self.available / self.expected, 4)


@dataclass(frozen=True, slots=True)
class QualitySnapshot:
    computed_at: datetime
    horizon_hours: int
    fixtures_expected: int
    """Scheduled fixtures of active competitions inside the horizon."""
    fixtures_with_odds: int
    """Of those, how many have at least one odds snapshot."""
    fixtures_with_near_close: int
    bookmakers_active: int
    bookmakers_seen_24h: int
    markets_tracked: int
    markets_seen_24h: int
    snapshots_24h: int
    stale_fixtures: int
    """Upcoming fixtures whose newest snapshot is older than STALE_CAPTURE_AFTER."""
    failed_jobs_24h: int
    provider_errors_24h: int
    requests_today: int
    last_successful_capture: datetime | None
    windows_expected_24h: int
    windows_captured_24h: int
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["computed_at"] = self.computed_at.isoformat()
        d["last_successful_capture"] = self.last_successful_capture.isoformat() if self.last_successful_capture else None
        d["fixture_odds_coverage"] = CoverageMetric(self.fixtures_expected, self.fixtures_with_odds).ratio
        d["bookmaker_coverage"] = CoverageMetric(self.bookmakers_active, self.bookmakers_seen_24h).ratio
        d["market_coverage"] = CoverageMetric(self.markets_tracked, self.markets_seen_24h).ratio
        d["window_coverage_24h"] = CoverageMetric(self.windows_expected_24h, self.windows_captured_24h).ratio
        return d


def _scalar(cur: psycopg.Cursor, sql: str, params: tuple[Any, ...] = ()) -> Any:
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def data_quality_snapshot(conn: psycopg.Connection, *, horizon_hours: int = 96, prematch_windows: int = 6) -> QualitySnapshot:
    moment = now()
    since = moment - timedelta(hours=24)
    until = moment + timedelta(hours=horizon_hours)
    notes: list[str] = []
    with conn.cursor(row_factory=tuple_row) as cur:
        fixtures_expected = int(_scalar(cur, """
            SELECT count(*) FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %s AND %s
        """, (moment, until)))
        fixtures_with_odds = int(_scalar(cur, """
            SELECT count(DISTINCT f.id) FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            JOIN market.odds_snapshots o ON o.fixture_id = f.id
            WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %s AND %s
        """, (moment, until)))
        fixtures_with_near_close = int(_scalar(cur, """
            SELECT count(DISTINCT n.fixture_id) FROM market.near_close_snapshots n
            JOIN core.fixtures f ON f.id = n.fixture_id WHERE f.kickoff_at BETWEEN %s AND %s
        """, (since, until)))
        bookmakers_active = int(_scalar(cur, "SELECT count(*) FROM market.bookmakers WHERE is_active"))
        bookmakers_seen = int(_scalar(cur, "SELECT count(DISTINCT bookmaker_id) FROM market.odds_snapshots WHERE captured_at >= %s", (since,)))
        markets_tracked = int(_scalar(cur, "SELECT count(*) FROM market.markets WHERE is_tracked"))
        markets_seen = int(_scalar(cur, "SELECT count(DISTINCT market_key) FROM market.odds_snapshots WHERE captured_at >= %s", (since,)))
        snapshots_24h = int(_scalar(cur, "SELECT count(*) FROM market.odds_snapshots WHERE captured_at >= %s", (since,)))
        stale = int(_scalar(cur, """
            SELECT count(*) FROM (
              SELECT f.id, max(o.captured_at) AS last_seen FROM core.fixtures f
              JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
              JOIN core.competitions c ON c.id = cs.competition_id
              JOIN market.odds_snapshots o ON o.fixture_id = f.id
              WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %s AND %s
              GROUP BY f.id
            ) t WHERE last_seen < %s
        """, (moment, until, moment - STALE_CAPTURE_AFTER)))
        failed_jobs = int(_scalar(cur, "SELECT count(*) FROM raw.ingestion_runs WHERE status IN ('failed','aborted') AND started_at >= %s", (since,)))
        provider_errors = int(_scalar(cur, "SELECT coalesce(sum(errors), 0) FROM raw.ingestion_runs WHERE started_at >= %s", (since,)))
        # Day boundary from the application clock, not the database's now().
        start_of_day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        requests_today = int(_scalar(cur, "SELECT coalesce(sum(api_calls), 0) FROM raw.ingestion_runs WHERE started_at >= %s", (start_of_day,)))
        last_ok = _scalar(cur, "SELECT max(finished_at) FROM raw.ingestion_runs WHERE job_type = 'odds_capture' AND status = 'completed'")
        # Windows: for fixtures that kicked off in the last 24 h, how many
        # distinct prematch windows did we actually record vs the configured cadence.
        kicked = int(_scalar(cur, """
            SELECT count(*) FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND f.kickoff_at BETWEEN %s AND %s
        """, (since, moment)))
        windows_captured = int(_scalar(cur, """
            SELECT coalesce(sum(n), 0) FROM (
              SELECT count(DISTINCT date_trunc('hour', o.captured_at)) AS n
              FROM market.odds_snapshots o JOIN core.fixtures f ON f.id = o.fixture_id
              WHERE f.kickoff_at BETWEEN %s AND %s AND o.source = 'prematch'
              GROUP BY f.id
            ) t
        """, (since, moment)))
    if fixtures_expected == 0:
        notes.append("no scheduled fixtures for active competitions in the horizon: coverage ratios are null, not zero")
    if snapshots_24h == 0:
        notes.append("no snapshots in the last 24 h")
    return QualitySnapshot(
        computed_at=moment,
        horizon_hours=horizon_hours,
        fixtures_expected=fixtures_expected,
        fixtures_with_odds=fixtures_with_odds,
        fixtures_with_near_close=fixtures_with_near_close,
        bookmakers_active=bookmakers_active,
        bookmakers_seen_24h=bookmakers_seen,
        markets_tracked=markets_tracked,
        markets_seen_24h=markets_seen,
        snapshots_24h=snapshots_24h,
        stale_fixtures=stale,
        failed_jobs_24h=failed_jobs,
        provider_errors_24h=provider_errors,
        requests_today=requests_today,
        last_successful_capture=last_ok,
        windows_expected_24h=kicked * prematch_windows,
        windows_captured_24h=min(windows_captured, kicked * prematch_windows),
        notes=notes,
    )
