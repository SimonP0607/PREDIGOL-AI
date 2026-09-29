"""The historical migration: price it, dry-run it, seed it, run it, watch it.

    python -m scripts.migration plan                      # tiers 1-3, every assumption shown; no request
    python -m scripts.migration plan --tiers 1,2 --no-ids # priced as if /fixtures?ids= were unavailable
    python -m scripts.migration capacity                  # Pro / Ultra / Mega against the plan and live needs
    python -m scripts.migration dry-run                   # end to end on a scratch database, fake HTTP
    python -m scripts.migration seed --tiers 1 --yes      # write the units (no request)
    python -m scripts.migration status                    # progress, requests spent vs planned
    python -m scripts.migration run --yes --max 500       # spend at most 500, never the live reserve

`plan` and `capacity` read the database for what is already stored and for
the provider's coverage flags (raw.league_coverage, filled by the first unit
of the migration itself). Nothing here calls the provider except `run`.
"""

from __future__ import annotations

import argparse
import asyncio
import json

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.migration.capacity import live_budget, recommend, scenarios
from fbi.migration.config import load_migration_config, load_plans
from fbi.migration.facts import DatabaseFacts, name_mismatches
from fbi.migration.planner import MigrationPlan, plan_migration
from fbi.migration.units import migration_status, save_plan, seed_plan


def _tiers(text: str) -> set[int]:
    return {int(x) for x in text.split(",") if x.strip()}


def _plan(conn: psycopg.Connection, args: argparse.Namespace) -> MigrationPlan:
    cfg = load_migration_config()
    return plan_migration(cfg, DatabaseFacts(conn), tiers=_tiers(args.tiers), ids_batching=not args.no_ids,
                          with_optional=args.with_optional)


def _print_plan(plan: MigrationPlan) -> None:
    print(f"tiers {list(plan.tiers)} · /fixtures?ids= batching {'ASSUMED AVAILABLE' if plan.ids_batching else 'ASSUMED UNAVAILABLE'}"
          f" · optional endpoints {'included' if plan.with_optional else 'excluded'}")
    print(f"league-seasons {len(plan.seasons)} · fixtures {plan.fixtures:,} · requests {plan.requests:,} · "
          f"raw storage {plan.raw_storage_kb / 1024:,.0f} MB (gzip)")
    print("requests by unit kind:", ", ".join(f"{k}={v:,}" for k, v in plan.requests_by_kind().items()))
    print("requests by tier:     ", ", ".join(f"T{k}={v:,}" for k, v in sorted(plan.requests_by_tier().items())))
    print("\ncompetition depth (seasons planned; coverage verified / unverified):")
    for lid, d in sorted(plan.depth().items(), key=lambda kv: (kv[1].tier, kv[0])):
        seasons = sorted(d.seasons)
        span = f"{seasons[0]}-{seasons[-1]}" if seasons else "-"
        print(f"  T{d.tier} {lid:>5} {d.name:<32} {len(seasons):>2} seasons {span:<9} "
              f"verified {d.verified:>2} / unverified {d.unverified:>2}")
    for n in plan.notes:
        print(f"note: {n}")


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="migration", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "capacity", "seed"):
        p = sub.add_parser(name)
        p.add_argument("--tiers", default="1,2,3")
        p.add_argument("--no-ids", action="store_true", help="price detail as 4 requests per fixture")
        p.add_argument("--with-optional", action="store_true", help="include OPTIONAL endpoints (player seasons)")
        p.add_argument("--json", action="store_true")
        if name == "seed":
            p.add_argument("--yes", action="store_true")
        if name == "capacity":
            p.add_argument("--live-tiers", default="", help="tiers captured live (default: config live.tiers)")
    sub.add_parser("status")
    gaps = sub.add_parser("gaps", help="played fixtures whose detail has never been fetched")
    gaps.add_argument("--tier", type=int)
    gaps.add_argument("--expand", action="store_true", help="create the units that would close them")
    gaps.add_argument("--json", action="store_true")
    dr = sub.add_parser("dry-run")
    dr.add_argument("--admin-url", default="", help="admin DSN of the same server (default: the configured one)")
    dr.add_argument("--keep", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--yes", action="store_true")
    run.add_argument("--max", type=int, default=100)
    args = parser.parse_args()

    if args.cmd == "dry-run":
        from fbi.migration.dryrun import dry_run

        admin = args.admin_url or settings.database.psycopg_url.rsplit("/", 1)[0] + "/postgres"
        report = asyncio.run(dry_run(admin, keep=args.keep))
        print(f"scratch database {report.database} ({'kept' if report.kept else 'dropped'}); "
              f"{report.requests} fake requests; units {report.units}")
        for c in report.checks:
            print(f"  {'PASS' if c.ok else 'FAIL'}  {c.name}  ({c.detail})")
        print("DRY RUN OK" if report.ok else "DRY RUN FAILED")
        return 0 if report.ok else 1

    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.cmd == "status":
            rows = migration_status(conn)
            if not rows:
                print("no migration units yet: python -m scripts.migration seed --tiers 1 --yes")
                return 0
            print(f"{'tier':>4} {'kind':<18} {'status':<8} {'units':>7} {'requests':>9} {'rows':>9}")
            for r in rows:
                print(f"{r.tier if r.tier is not None else '-':>4} {r.kind:<18} {r.status:<8} {r.units:>7} "
                      f"{r.requests:>9} {r.rows:>9}")
            return 0
        if args.cmd == "gaps":
            from fbi.ingestion.backfill import DETAIL_BATCH, expand_detail_batches
            from fbi.migration.completeness import season_gaps

            gap_rows = season_gaps(conn, tier=args.tier)
            if args.json:
                print(json.dumps([{"league": g.provider_league_id, "season": g.season, "tier": g.tier,
                                   "played": g.played, "missing": g.missing, "requests": g.batches}
                                  for g in gap_rows], indent=2))
            else:
                print(f"{'tier':>4} {'league':>7} {'season':>7} {'played':>7} {'missing':>8} {'requests':>9}")
                for g in gap_rows:
                    print(f"{g.tier if g.tier is not None else '-':>4} {g.provider_league_id:>7} "
                          f"{g.season:>7} {g.played:>7} {g.missing:>8} {g.batches:>9}")
            total_missing = sum(g.missing for g in gap_rows)
            total_requests = sum(g.batches for g in gap_rows)
            print(f"{len(gap_rows)} league-season(s), {total_missing} fixture(s) without detail, "
                  f"{total_requests} request(s) at {DETAIL_BATCH} per request")
            if not args.expand:
                if gap_rows:
                    print("add --expand to create the units (no provider request is made)")
                return 0
            created = 0
            for g in gap_rows:
                created += expand_detail_batches(
                    conn, league_id=g.provider_league_id, season=g.season, tier=g.tier,
                    priority=(g.tier or 9) * 10_000 + 200,
                )
            print(f"{created} detail unit(s) created or revived; run them with: "
                  f"python -m scripts.migration run --yes --max N")
            return 0
        if args.cmd == "run":
            if not args.yes:
                print("this spends provider requests: add --yes")
                return 2
            from fbi.ingestion.backfill import run_backfill
            from fbi.providers.api_football import ApiFootballProvider
            from fbi.providers.api_football.build import build_client

            async def go() -> None:
                provider = ApiFootballProvider(build_client())
                try:
                    rep = await run_backfill(conn, provider, max_requests=args.max,
                                             daily_budget=settings.provider_plan.effective_budget,
                                             prematch_windows=settings.odds.prematch_windows)
                finally:
                    await provider.aclose()
                print(f"allowance {rep.allowance} (reserve {rep.reserve}); attempted {rep.attempted}: "
                      f"done {rep.done}, refused {rep.refused}, failed {rep.failed}; rows {rep.rows_written}; "
                      f"new units {rep.units_created}; {rep.deferred_reason or ''}")

            asyncio.run(go())
            return 0

        plan = _plan(conn, args)
        cfg = load_migration_config()
        if args.cmd == "plan":
            if args.json:
                print(json.dumps(plan.as_dict(), indent=2, default=str))
            else:
                _print_plan(plan)
                configured = {c.league_id: c.name for c in cfg.tier_competitions(set(plan.tiers))}
                wrong = name_mismatches(DatabaseFacts(conn), configured)
                for lid, mine, theirs in wrong:
                    print(f"NAME CHECK: league {lid} is '{mine}' here but '{theirs}' at the provider - fix the id "
                          "before seeding")
                if not wrong:
                    print("name check: every league the provider has described matches its configured name")
            return 0
        if args.cmd == "capacity":
            catalogue = load_plans()
            live = live_budget(cfg, _tiers(args.live_tiers) if args.live_tiers else None)
            options = scenarios(plan, cfg, catalogue, live, max_backfill_days=cfg.max_backfill_days)
            rec = recommend(options)
            _print_plan(plan)
            print(f"\nlive operation, tiers {list(live.tiers)} ({live.leagues} competitions, "
                  f"{live.fixtures_per_season:,} fixtures a season): average day {live.avg_total:,.0f} requests "
                  f"({live.avg_fixtures_per_day:.1f} fixtures), busiest day {live.peak_total:,.0f} "
                  f"({live.peak_fixtures_per_day:.1f} fixtures)")
            for k, v in live.peak.items():
                print(f"    peak {k:<26} {v:>7,.0f}")
            print(f"\nbuffer {cfg.buffer_fraction:.0%} on every estimate; {cfg.live_reserve_fraction:.0%} of the quota "
                  f"never used by the backfill; the backfill must finish within {cfg.max_backfill_days:g} days")
            print(f"{'plan':<6} {'$/month':>8} {'req/day':>9} {'backfill':>10} {'days':>7} {'live peak':>10} "
                  f"{'headroom':>9}  fits")
            for s in options:
                days = f"{s.backfill_days:.1f}" if s.backfill_days is not None else "never"
                print(f"{s.plan.name:<6} {s.plan.price_month:>8.0f} {s.plan.requests_per_day:>9,} "
                      f"{s.backfill_requests:>10,} {days:>7} {s.live_peak:>10,.0f} {s.live_headroom_pct:>8.1f}%  "
                      f"{'yes' if s.fits else 'no'}")
            print(f"\nrecommended: {rec.plan.name if rec else 'none fits'} (prices as of {catalogue.checked_on}: "
                  "confirm on the dashboard before buying)")
            return 0
        if args.cmd == "seed":
            if not args.yes:
                _print_plan(plan)
                print("\nthis writes the units above: add --yes")
                return 2
            plan_id = save_plan(conn, plan, name=f"tiers-{'-'.join(map(str, plan.tiers))}")
            rep = seed_plan(conn, plan, plan_id=plan_id, current_season=cfg.current_season)
            print(f"plan {plan_id}: {rep.created} units created, {rep.existing} already present; "
                  f"{rep.detail_units} detail units from stored fixtures; by kind {rep.by_kind}")
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
