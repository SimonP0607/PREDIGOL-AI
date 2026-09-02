"""Operator entry point for the odds capturer.

    python -m scripts.capture_odds plan     # show what WOULD be captured, no calls
    python -m scripts.capture_odds run      # capture the windows due right now
    python -m scripts.capture_odds report   # what the store actually holds

``plan`` exists so a change to the cadence can be inspected before it spends
quota. Nothing here publishes a pick or places a bet; this program only records
what the market said and when.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure_logging
from fbi.ingestion.payload_store import PayloadStore
from fbi.odds.capture import OddsCaptureService
from fbi.odds.schedule import CapturePlanner, ScheduledFixture
from fbi.providers.api_football import ApiFootballClient, ApiFootballProvider

log = structlog.get_logger("capture_odds")


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.database.psycopg_url)


def _build_planner() -> CapturePlanner:
    cfg = settings.odds
    return CapturePlanner(cfg.prematch_windows, cfg.odds_nearclose_window, cfg.odds_window_tolerance)


def _upcoming(conn: psycopg.Connection, horizon_hours: int) -> list[ScheduledFixture]:
    """Fixtures inside the horizon, restricted to the configured leagues.

    The league list is configuration, never a constant in the domain: the legacy
    system hard-coded nine league ids in five different files.
    """
    league_ids = settings.odds.league_ids
    if not league_ids:
        log.warning("capture.no_active_leagues", hint="set FBI_ACTIVE_LEAGUES")
        return []
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT f.provider_fixture_id, f.kickoff_at, f.status_short "
            "FROM core.fixtures f "
            "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
            "JOIN core.competitions c ON c.id = cs.competition_id "
            "WHERE c.provider_league_id = ANY(%s) "
            "  AND f.kickoff_at BETWEEN %s AND %s "
            "  AND f.status_group = 'scheduled' "
            "ORDER BY f.kickoff_at",
            (league_ids, now(), now() + timedelta(hours=horizon_hours)),
        )
        return [ScheduledFixture(int(a), b, str(c)) for a, b, c in cur.fetchall()]


def _provider() -> ApiFootballProvider:
    client = ApiFootballClient(
        settings.api_football, PayloadStore(settings.runtime.raw_store_dir)
    )
    return ApiFootballProvider(client, market_filter=settings.odds.market_filter)


async def _run(horizon_hours: int, dry_run: bool) -> int:
    with _connect() as conn:
        fixtures = _upcoming(conn, horizon_hours)
        planner = _build_planner()

        if dry_run:
            from fbi.odds.repository import OddsRepository

            repo = OddsRepository(conn)
            covered = planner.covered_keys(
                repo.observations_since(
                    since=now() - timedelta(hours=24),
                    provider_fixture_ids=[f.provider_fixture_id for f in fixtures],
                )
            )
            tasks = planner.plan(fixtures, at=now(), already_done=covered)
            print(f"fixtures in horizon : {len(fixtures)}")
            print(f"already captured    : {len(covered)}")
            print(f"tasks due now       : {len(tasks)}")
            for task in tasks[:50]:
                print(f"  {task.window_key:<28} T-{task.minutes_to_ko:<6} {task.kind}")
            nxt = planner.next_run_at(fixtures, at=now())
            print(f"next window at      : {nxt.isoformat() if nxt else 'nothing pending'}")
            return 0

        provider = _provider()
        try:
            service = OddsCaptureService(
                conn, provider, planner, raw_root=settings.runtime.raw_store_dir
            )
            report = await service.capture(fixtures)
        finally:
            await provider.aclose()

        print(
            f"run {report.run_id}: planned={report.planned} executed={report.executed} "
            f"quotes={report.quotes_seen} written={report.snapshots_written} "
            f"near_close={report.near_close_written} calls={report.api_calls} "
            f"errors={len(report.errors)} status={report.status}"
        )
        if report.stopped_early:
            print(f"stopped early: {report.stopped_early}")
        return 1 if report.status == "failed" else 0


def _report() -> int:
    """What the store holds. Deliberately says near-close, never closing line."""
    with _connect() as conn, conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT count(*), count(DISTINCT fixture_id), min(captured_at), max(captured_at) "
            "FROM market.odds_snapshots"
        )
        total, fixtures, first, last = cur.fetchone()
        print(f"odds snapshots      : {total:,} across {fixtures:,} fixtures")
        print(f"first / last capture: {first} .. {last}")

        cur.execute(
            "SELECT market_key, count(*), count(DISTINCT fixture_id) "
            "FROM market.odds_snapshots GROUP BY 1 ORDER BY 2 DESC"
        )
        for market, rows, fx in cur.fetchall():
            print(f"  {market:<6} {rows:>10,} rows  {fx:>6,} fixtures")

        cur.execute(
            "SELECT count(*), count(*) FILTER (WHERE is_validated_close), "
            "       percentile_disc(0.5) WITHIN GROUP (ORDER BY minutes_to_ko) "
            "FROM market.near_close_snapshots"
        )
        near, validated, median = cur.fetchone()
        print(f"near-close snapshots: {near:,} (median T-{median or 0} min)")
        print(
            f"  validated as closing line: {validated or 0}. "
            "Until that number is meaningful, no figure derived from these is CLV."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capture_odds", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--horizon-hours", type=int, default=96)
    sub.add_parser("report")
    args = parser.parse_args(argv)

    configure_logging(settings.runtime.log_level)
    if args.command == "report":
        return _report()
    return asyncio.run(_run(args.horizon_hours, dry_run=args.command == "plan"))


if __name__ == "__main__":
    sys.exit(main())
