"""Capture in-play odds. A pipeline of its own, runnable on its own.

    python scripts/capture_live.py plan        # what the cadence would do, 0 requests
    python scripts/capture_live.py once        # one tick
    python scripts/capture_live.py follow      # keep ticking at the measured cadence
    python scripts/capture_live.py coverage    # what has been captured so far, 0 requests
    python scripts/capture_live.py movement    # the price changes observed, 0 requests

``plan``, ``coverage`` and ``movement`` never call the provider, so they are safe to run at
any time to see what the live path is doing and what it has.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import psycopg
import structlog

from fbi.core.config import settings
from fbi.odds.live_capture import LiveCaptureService
from fbi.odds.live_repository import LiveOddsRepository
from fbi.odds.partitions import ensure_partitions
from fbi.providers.api_football import ApiFootballProvider
from fbi.providers.quota import read_usage
from scripts.capture_odds import _client, _connect

log = structlog.get_logger(__name__)


def _remaining(conn: psycopg.Connection) -> int:
    cfg = settings.api_football
    usage = read_usage(conn, budget=min(cfg.daily_budget, cfg.per_day_limit))
    return int(usage.remaining)


def _plan() -> int:
    with _connect() as conn:
        service = LiveCaptureService(conn, provider=None)  # type: ignore[arg-type]
        decision = service.plan(remaining_quota=_remaining(conn))
    print(f"capture now        : {'yes' if decision.should_capture else 'no'}")
    print(f"reason             : {decision.reason}")
    print(f"next look in       : {decision.next_in_seconds}s")
    print(f"possibly in play   : {decision.fixtures_possibly_live}")
    print(f"budget floor       : {decision.budget_floor_seconds}s")
    return 0


async def _once() -> int:
    with _connect() as conn:
        from fbi.core.clock import today

        ensure_partitions(conn, today=today())
        provider = ApiFootballProvider(_client())
        try:
            service = LiveCaptureService(conn, provider)
            report = await service.capture(remaining_quota=_remaining(conn))
        finally:
            await provider.aclose()
    if not report.captured:
        print(f"skipped: {report.skipped_reason}")
        print(f"next look in {report.next_in_seconds}s")
        return 0
    print(f"fixtures priced    : {report.fixtures_priced}")
    print(f"quotes seen        : {report.quotes_seen}")
    print(f"quotes written     : {report.quotes_written}")
    print(f"already had        : {report.quotes_duplicate}")
    print(f"states written     : {report.states_written}")
    print(f"values suspended   : {report.values_suspended}")
    print(f"refused (no price) : {report.refused}")
    print(f"unmapped rows kept : {report.unmapped_rows}")
    print(f"markets observed   : {report.markets_observed}")
    print(f"untracked fixtures : {report.unknown_fixtures} "
          f"({report.quotes_untracked} quotes)")
    print(f"accounting holds   : "
          f"{'yes' if report.accounting_holds else 'NO - PRICES MAY BE LOST'}")
    print(f"quality issues     : {report.quality_issues_opened}")
    print(f"next look in       : {report.next_in_seconds}s")
    return 1 if report.errors else 0


async def _follow(max_ticks: int | None) -> int:
    """Keep capturing at whatever cadence the decision asks for.

    A skipped tick sleeps for exactly as long as the decision says, so an idle
    night costs one database query every five minutes and no requests at all.
    """
    ticks = 0
    provider = ApiFootballProvider(_client())
    try:
        while max_ticks is None or ticks < max_ticks:
            with _connect() as conn:
                from fbi.core.clock import today

                ensure_partitions(conn, today=today())
                service = LiveCaptureService(conn, provider)
                report = await service.capture(remaining_quota=_remaining(conn))
            ticks += 1
            if report.captured:
                log.info(
                    "capture_live.tick",
                    fixtures=report.fixtures_priced,
                    written=report.quotes_written,
                    duplicate=report.quotes_duplicate,
                    next_in=report.next_in_seconds,
                )
            else:
                log.info(
                    "capture_live.idle",
                    reason=report.skipped_reason,
                    next_in=report.next_in_seconds,
                )
            await asyncio.sleep(max(1, report.next_in_seconds))
    except KeyboardInterrupt:
        log.info("capture_live.stopped", ticks=ticks)
    finally:
        await provider.aclose()
    return 0


def _coverage(hours: int) -> int:
    with _connect() as conn:
        repo = LiveOddsRepository(conn)
        markets = repo.market_coverage(since_hours=hours)
        comps = repo.competition_coverage(since_hours=hours)
    print(f"=== in-play markets actually priced, last {hours}h "
          f"({len(markets)} distinct bets)")
    print(f"{'bet':>5}  {'fixtures':>8}  {'values':>8}  name")
    for bet_id, name, fixtures, values in markets[:40]:
        print(f"{bet_id:>5}  {fixtures:>8}  {values:>8}  {name}")
    print(f"\n=== competitions seen in play, last {hours}h ({len(comps)})")
    for league_id, name, fixtures in comps[:40]:
        print(f"{league_id:>6}  {fixtures:>4}  {name}")
    if not markets:
        print("(nothing captured yet)")
    return 0


def _movement(hours: int, fixture: int | None) -> int:
    with _connect() as conn:
        rows = LiveOddsRepository(conn).movements(
            provider_fixture_id=fixture, since_minutes=hours * 60, limit=40
        )
    if not rows:
        print("(no price change observed in that window)")
        return 0
    print(f"{'fixture':>9} {'market':>5} {'selection':>9} {'line':>6} "
          f"{'from':>7} {'to':>7} {'d prob':>8} {'min':>4} score  why")
    for m in rows:
        why = []
        if m.score_changed:
            why.append("GOAL")
        if m.became_suspended:
            why.append("suspended")
        if m.became_available:
            why.append("reopened")
        print(f"{m.provider_fixture_id:>9} {m.market_key or '-':>5} "
              f"{m.selection:>9} {m.line:>6} {m.previous_odds:>7} {m.odds:>7} "
              f"{m.implied_prob_delta:>+8.4f} {m.elapsed_minute or 0:>4} "
              f"{m.score_home}-{m.score_away}  {' '.join(why)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="what the cadence would do (no requests)")
    sub.add_parser("once", help="one capture tick")
    f = sub.add_parser("follow", help="capture continuously at the measured cadence")
    f.add_argument("--max-ticks", type=int, default=None)
    c = sub.add_parser("coverage", help="what has been captured (no requests)")
    c.add_argument("--hours", type=int, default=24)
    mv = sub.add_parser("movement", help="observed price changes (no requests)")
    mv.add_argument("--hours", type=int, default=3)
    mv.add_argument("--fixture", type=int, default=None,
                    help="one provider fixture id")
    args = ap.parse_args()

    if args.cmd == "plan":
        return _plan()
    if args.cmd == "once":
        return asyncio.run(_once())
    if args.cmd == "follow":
        return asyncio.run(_follow(args.max_ticks))
    if args.cmd == "movement":
        return _movement(args.hours, args.fixture)
    return _coverage(args.hours)


if __name__ == "__main__":
    raise SystemExit(main())
