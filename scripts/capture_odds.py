"""Operator entry point for the odds capturer.

    python -m scripts.capture_odds status      # plan + quota from the provider (1 call to /status)
    python -m scripts.capture_odds plan        # what WOULD be captured. ZERO provider calls.
    python -m scripts.capture_odds run         # capture the windows due right now
    python -m scripts.capture_odds run --max-requests 5   # hard cap for a controlled first run
    python -m scripts.capture_odds report      # what the store actually holds

``plan`` validates the plan (duplicates, kicked-off fixtures, unknown fixtures,
budget) and refuses to hand over a plan that fails. ``run`` runs the same
validation first and stops if it fails: a script that "runs" is not the same
as a capture that is correct.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.catalog.activation import active_league_ids
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.odds.capture import OddsCaptureService
from fbi.odds.repository import OddsRepository
from fbi.odds.schedule import (
    CapturePlanner,
    CaptureTask,
    PlanCheck,
    ScheduledFixture,
    validate_plan,
)
from fbi.providers.api_football import ApiFootballClient, ApiFootballProvider
from fbi.providers.api_football.build import build_client
from fbi.providers.api_football.status import fetch_status
from fbi.providers.quota import read_usage

log = structlog.get_logger("capture_odds")


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.database.psycopg_url)


def _build_planner() -> CapturePlanner:
    cfg = settings.odds
    return CapturePlanner(cfg.prematch_windows, cfg.odds_nearclose_window,
                          cfg.odds_window_tolerance,
                          plan_near_close=cfg.odds_capture_near_close)


def _upcoming(conn: psycopg.Connection, horizon_hours: int) -> list[ScheduledFixture]:
    """Fixtures inside the horizon for the ACTIVE competitions.

    Activation lives in core.competitions.is_tracked, set only by
    config/competitions.yaml through scripts.manage_competitions. Nothing here
    or anywhere else carries a league id.
    """
    if not active_league_ids(conn):
        log.warning("capture.no_active_competitions", hint="enable one in config/competitions.yaml and run manage_competitions apply")
        return []
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(UPCOMING_SQL, (now(), now() + timedelta(hours=horizon_hours)))
        return [ScheduledFixture(int(a), b, str(c)) for a, b, c in cur.fetchall()]


UPCOMING_SQL = """
SELECT f.provider_fixture_id, f.kickoff_at, f.status_short
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked
   AND f.kickoff_at BETWEEN %s AND %s
   AND f.status_group = 'scheduled'
   AND (lc.odds IS NOT FALSE
        OR EXISTS (SELECT 1 FROM market.odds_mapping_seen m WHERE m.provider_fixture_id = f.provider_fixture_id))
 ORDER BY f.kickoff_at
"""
"""The fixtures the capture asks /odds for. A league-season the provider's coverage flags as having no odds is not
asked (every answer would be empty) - unless /odds/mapping lists the fixture as priced: the flag is per season and can
be stale, the mapping names the fixture.

The mapping is NOT used to leave a fixture out. Measured on 5 Oct 2026 (``docs/owner/API_FOOTBALL_P1.md``): of the 76
tracked fixtures of the next 96 h with a price, 10 were absent from the newest mapping, and four of those had already
been captured with prices 25 to 86 minutes BEFORE that mapping was read - the provider's daily listing lags its
prices. Skipping unlisted fixtures would have lost those prices to save ~43 empty requests a day (0.07 % of the
internal budget)."""


def _client(max_requests: int | None = None) -> ApiFootballClient:
    """Always through build_client: that is what attaches the persistent
    budget. A locally constructed client would count in memory and forget."""
    return build_client(max_requests)


async def _status() -> int:
    client = _client()
    try:
        st = await fetch_status(client)
    finally:
        await client.aclose()
    cfg = settings.api_football
    with _connect() as conn:
        ours = read_usage(conn, budget=min(cfg.daily_budget, cfg.per_day_limit))
    print(f"plan (provider)      : {st.plan}")
    print(f"plan (configured)    : {cfg.plan}  {'OK' if cfg.plan == st.plan else '<- MISMATCH: fix FBI_APIFOOTBALL_PLAN'}")
    print("--- the provider's limit (it does not count calls it refused) ---")
    print(f"requests today       : {st.requests_today} / {st.requests_limit_day}  (remaining {st.remaining_today})")
    print("--- our budget, counted in the database and shared by every process ---")
    print(f"requests issued today: {ours.spent} / {ours.budget}  (remaining {ours.remaining})")
    print(f"budget vs plan limit : {'OK' if ours.budget < st.requests_limit_day else '<- budget must stay BELOW the plan limit'}")
    print(f"claimed by closed runs: {ours.ledger_api_calls}"
          f"   unattributed: {ours.unattributed}"
          f"{'' if ours.unattributed == 0 else '  (ad-hoc calls like this /status open no run)'}")
    print(f"counted for           : {ours.quota_date.isoformat()} (UTC day)")
    print(f"subscription active  : {st.subscription_active} (ends {st.subscription_end or '-'})")
    return 0 if cfg.plan == st.plan else 1


def _plan_only(conn: psycopg.Connection, horizon_hours: int) -> tuple[list[ScheduledFixture], list[CaptureTask], PlanCheck]:
    fixtures = _upcoming(conn, horizon_hours)
    planner = _build_planner()
    repo = OddsRepository(conn)
    ids = [f.provider_fixture_id for f in fixtures]
    covered = planner.covered_keys(repo.window_observations_since(since=now() - timedelta(hours=24),
                                                                  provider_fixture_ids=ids))
    asked = repo.last_asked(provider_fixture_ids=ids, since=now() - timedelta(days=4))
    tasks = planner.plan(fixtures, at=now(), already_done=covered, last_asked=asked)
    known = {f.provider_fixture_id for f in fixtures}
    cfg = settings.api_football
    # REMAINING, not the whole budget: the guard is
    # requests_used_today + planned <= internal_daily_budget, and passing the
    # full budget here made a plan look affordable on a budget already spent.
    ours = read_usage(conn, budget=min(cfg.daily_budget, cfg.per_day_limit))
    check = validate_plan(tasks, at=now(), budget_remaining=ours.remaining, known_fixture_ids=known)
    print(f"fixtures in horizon  : {len(fixtures)}")
    print(f"already captured     : {len(covered)} window(s)")
    print(f"tasks due now        : {len(tasks)}")
    for t in tasks[:50]:
        print(f"  {t.window_key:<28} T-{t.minutes_to_ko:<6} {'/odds/live' if t.kind == 'near_close' else '/odds'}")
    print(f"estimated requests   : {check.estimated_requests}")
    print(f"budget               : {ours.spent} spent today of {ours.budget}, {ours.remaining} left")
    print("actual requests      : 0")
    nxt = planner.next_run_at(fixtures, at=now())
    print(f"next window at       : {nxt.isoformat() if nxt else 'nothing pending'}")
    if check.issues:
        print("\nPLAN REJECTED:")
        for i in check.issues:
            print("  -", i)
    else:
        print("plan check           : OK")
    return fixtures, list(tasks), check


async def _run(horizon_hours: int, max_requests: int | None) -> int:
    with _connect() as conn:
        fixtures, tasks, check = _plan_only(conn, horizon_hours)
        if not check.ok:
            print("\nSTOP: the plan did not pass validation. Nothing was captured.")
            return 2
        if not tasks:
            print("\nnothing due. 0 requests.")
            return 0
        if max_requests is not None and check.estimated_requests > max_requests:
            print(f"\nSTOP: plan needs ~{check.estimated_requests} requests, cap is {max_requests}. Raise --max-requests or wait.")
            return 2

        client = _client(max_requests)
        provider = ApiFootballProvider(client, market_filter=settings.odds.market_filter)
        try:
            service = OddsCaptureService(conn, provider, _build_planner(), raw_root=settings.runtime.raw_store_dir)
            report = await service.capture(fixtures)
        finally:
            await provider.aclose()

        print(
            f"\nrun {report.run_id}: planned={report.planned} executed={report.executed} "
            f"requests={report.api_calls} payloads={report.payloads_stored} quotes={report.quotes_seen} "
            f"inserted={report.snapshots_written} duplicates={report.duplicates_skipped} "
            f"near_close={report.near_close_written} errors={len(report.errors)} status={report.status}"
        )
        if report.stopped_early:
            print(f"stopped early: {report.stopped_early}")
        return 1 if report.status == "failed" else 0


def _report() -> int:
    """What the store holds. Deliberately says near-close, never closing line."""
    with _connect() as conn, conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT count(*), count(DISTINCT fixture_id), min(captured_at), max(captured_at) FROM market.odds_snapshots")
        total, fixtures, first, last = cur.fetchone()  # type: ignore[misc]
        print(f"odds snapshots       : {total:,} across {fixtures:,} fixtures")
        print(f"first / last capture : {first} .. {last}")
        cur.execute("SELECT market_key, count(*), count(DISTINCT fixture_id) FROM market.odds_snapshots GROUP BY 1 ORDER BY 2 DESC")
        for market, rows, fx in cur.fetchall():
            print(f"  {market:<6} {rows:>10,} rows  {fx:>6,} fixtures")
        cur.execute(
            "SELECT count(*), count(*) FILTER (WHERE is_validated_close), "
            "percentile_disc(0.5) WITHIN GROUP (ORDER BY minutes_to_ko) FROM market.near_close_snapshots"
        )
        near, validated, median = cur.fetchone()  # type: ignore[misc]
        print(f"near-close snapshots : {near:,} (median T-{median or 0} min)")
        print(f"  validated as closing line: {validated or 0}. Until that number is meaningful, no figure derived from these is CLV.")
        cur.execute(
            "SELECT id, job_type, status, started_at, api_calls, payloads_stored, rows_written, rows_updated, errors "
            "FROM raw.ingestion_runs ORDER BY started_at DESC LIMIT 8"
        )
        print("\nlast runs:")
        for rid, jt, st, at, calls, pl, ins, upd, err in cur.fetchall():
            print(f"  #{rid:<4} {jt:<14} {st:<9} {at:%Y-%m-%d %H:%M}  calls={calls} payloads={pl} inserted={ins} updated={upd} errors={err}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="capture_odds", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    p = sub.add_parser("plan")
    p.add_argument("--horizon-hours", type=int, default=96)
    p = sub.add_parser("run")
    p.add_argument("--horizon-hours", type=int, default=96)
    p.add_argument("--max-requests", type=int, default=None, help="hard cap on provider calls for this run")
    sub.add_parser("report")
    args = parser.parse_args(argv)

    configure_logging(settings.runtime.log_level)
    if args.command == "status":
        return asyncio.run(_status())
    if args.command == "report":
        return _report()
    if args.command == "plan":
        with _connect() as conn:
            _, _, check = _plan_only(conn, args.horizon_hours)
        return 0 if check.ok else 2
    return asyncio.run(_run(args.horizon_hours, args.max_requests))


if __name__ == "__main__":
    sys.exit(main())
