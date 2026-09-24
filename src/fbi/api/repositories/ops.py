"""Counts, freshness and the job ledger - for Overview and Data Quality."""

from __future__ import annotations

from datetime import datetime

from fbi.api.repositories import Conn, Row, fetch_all, fetch_one


def database_stats(conn: Conn) -> Row:
    r = fetch_one(conn, """
        SELECT (SELECT version_num FROM alembic_version) AS revision,
               (SELECT count(*) FROM core.competitions) AS competitions_known,
               (SELECT count(*) FROM core.competitions WHERE is_tracked) AS competitions_tracked,
               (SELECT count(*) FROM core.teams) AS teams,
               (SELECT count(*) FROM core.fixtures) AS fixtures,
               (SELECT count(*) FROM core.fixture_results) AS fixtures_with_result,
               (SELECT count(*) FROM market.odds_snapshots) AS odds_snapshots,
               (SELECT count(*) FROM market.near_close_snapshots) AS near_close_snapshots,
               (SELECT count(*) FROM market.bookmakers) AS bookmakers,
               (SELECT count(*) FROM market.markets WHERE is_tracked) AS markets_tracked,
               (SELECT count(*) FROM raw.ingestion_payloads) AS raw_payloads,
               (SELECT count(*) FROM models.predictions) AS predictions,
               (SELECT count(*) FROM picks.picks) AS picks
    """)
    assert r is not None
    return r


def fixture_counts(conn: Conn, at: datetime) -> Row:
    r = fetch_one(conn, """
        SELECT count(*) FILTER (WHERE f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %(at)s AND %(at)s + interval '24 hours') AS upcoming_24h,
               count(*) FILTER (WHERE f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %(at)s AND %(at)s + interval '7 days') AS upcoming_7d,
               count(*) FILTER (WHERE c.is_tracked AND f.kickoff_at < %(at)s AND f.status_group IN ('scheduled','live')) AS awaiting_result,
               count(*) FILTER (WHERE f.status_group = 'finished') AS finished,
               count(r.fixture_id) FILTER (WHERE f.status_group = 'finished') AS finished_with_result
        FROM core.fixtures f
        JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
        JOIN core.competitions c ON c.id = cs.competition_id
        LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
    """, {"at": at})
    assert r is not None
    return r


def next_fixture_id(conn: Conn, at: datetime) -> int | None:
    r = fetch_one(conn, """
        SELECT f.id FROM core.fixtures f
        WHERE f.status_group = 'scheduled' AND f.kickoff_at >= %s ORDER BY f.kickoff_at, f.id LIMIT 1
    """, (at,))
    return int(r["id"]) if r else None


def freshness(conn: Conn) -> Row:
    r = fetch_one(conn, """
        SELECT (SELECT max(fetched_at) FROM raw.ingestion_payloads) AS last_payload_at,
               (SELECT max(finished_at) FROM raw.ingestion_runs WHERE job_type = 'fixtures_sync' AND status IN ('completed','partial')) AS last_fixtures_sync_at,
               (SELECT max(finished_at) FROM raw.ingestion_runs WHERE job_type = 'results_sync' AND status IN ('completed','partial')) AS last_results_sync_at,
               (SELECT max(finished_at) FROM raw.ingestion_runs WHERE job_type = 'odds_capture' AND status IN ('completed','partial')) AS last_odds_capture_at,
               (SELECT max(captured_at) FROM market.odds_snapshots) AS last_snapshot_at
    """)
    assert r is not None
    return r


def recent_runs(conn: Conn, *, limit: int, job_type: str | None = None, status: str | None = None) -> list[Row]:
    return fetch_all(conn, """
        SELECT id, job_type, job_name, status, started_at, finished_at, duration_ms, api_calls,
               payloads_stored, rows_written, rows_updated, errors, last_error, notes
        FROM raw.ingestion_runs
        WHERE (%(job_type)s::text IS NULL OR job_type = %(job_type)s::text)
          AND (%(status)s::text IS NULL OR status = %(status)s::text)
        ORDER BY started_at DESC, id DESC LIMIT %(limit)s
    """, {"limit": limit, "job_type": job_type, "status": status})


def coverage_by_competition(conn: Conn, at: datetime, horizon_hours: int) -> list[Row]:
    return fetch_all(conn, """
        SELECT c.id AS competition_id, c.name AS competition, cs.season,
               count(DISTINCT f.id) FILTER (WHERE f.status_group = 'scheduled'
                   AND f.kickoff_at BETWEEN %(at)s AND %(at)s + make_interval(hours => %(h)s)) AS fixtures_in_horizon,
               count(DISTINCT f.id) FILTER (WHERE f.status_group = 'scheduled'
                   AND f.kickoff_at BETWEEN %(at)s AND %(at)s + make_interval(hours => %(h)s)
                   AND EXISTS (SELECT 1 FROM market.odds_snapshots o WHERE o.fixture_id = f.id)) AS fixtures_with_odds,
               (SELECT count(DISTINCT o.bookmaker_id) FROM market.odds_snapshots o JOIN core.fixtures f2 ON f2.id = o.fixture_id
                  WHERE f2.competition_season_id = cs.id AND o.captured_at >= %(at)s - interval '24 hours') AS bookmakers_seen_24h,
               (SELECT count(DISTINCT o.market_key) FROM market.odds_snapshots o JOIN core.fixtures f2 ON f2.id = o.fixture_id
                  WHERE f2.competition_season_id = cs.id AND o.captured_at >= %(at)s - interval '24 hours') AS markets_seen_24h,
               (SELECT max(o.captured_at) FROM market.odds_snapshots o JOIN core.fixtures f2 ON f2.id = o.fixture_id
                  WHERE f2.competition_season_id = cs.id) AS last_capture_at,
               count(DISTINCT f.id) FILTER (WHERE f.kickoff_at < %(at)s AND f.status_group IN ('scheduled','live')) AS fixtures_awaiting_result
        FROM core.competitions c
        JOIN core.competition_seasons cs ON cs.competition_id = c.id
        LEFT JOIN core.fixtures f ON f.competition_season_id = cs.id
        WHERE c.is_tracked AND cs.is_current
        GROUP BY c.id, cs.id ORDER BY c.name
    """, {"at": at, "h": horizon_hours})


def lineage_gaps(conn: Conn) -> Row:
    r = fetch_one(conn, """
        SELECT (SELECT count(*) FROM core.fixtures WHERE source_payload_hash IS NULL) AS fixtures_without_lineage,
               (SELECT count(*) FROM core.fixture_results WHERE source_payload_hash IS NULL) AS results_without_lineage
    """)
    assert r is not None
    return r
