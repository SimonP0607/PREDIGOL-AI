"""Answer the two questions the plan choice depends on, for 2 requests, before buying.

    python -m scripts.probe_plan            # what it would do; no request
    python -m scripts.probe_plan --yes      # 1 x /fixtures?ids= + 1 x /leagues (the plan: capture_odds status)

1. Does ``/fixtures?ids=`` return the detail blocks (events, lineups, team and
   player statistics) on this account? The documentation lists it for every
   plan; one official post says "when available for your plan". The capacity
   model's answer turns on it: with batching the whole migration fits Pro in
   days, without it Pro would need months. Run on the Free plan: if the blocks
   come back there, a paid plan has them too. It also measures a real detail
   payload, replacing the planner's 7 KB-per-fixture estimate.
2. What does the provider actually cover? ``/leagues`` returns every league
   with every season and its coverage flags in one request: the migration's
   first unit, run early. The planner then prints "verified" instead of
   "unverified", with the provider's own name for each configured id.

Both payloads are stored and indexed like any other (lineage), both requests
go through the persistent daily quota the worker shares, and the probe refuses
when fewer than 5 requests remain today. It never touches odds capture.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import psycopg
from psycopg.rows import tuple_row

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.migration.config import load_migration_config
from fbi.migration.probe import BLOCKS, run_probe
from fbi.providers.api_football import ApiFootballProvider
from fbi.providers.api_football.build import build_client, build_quota

MIN_REMAINING = 5


def _say(msg: str) -> None:
    print(msg, flush=True)


def two_finished_fixtures(conn: psycopg.Connection) -> list[int]:
    """Two finished top-league fixtures of the newest season the free plan serves (<= 2024)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT f.provider_fixture_id FROM core.fixtures f "
            "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
            "JOIN core.competitions c ON c.id = cs.competition_id "
            "WHERE f.status_group = 'finished' AND cs.season <= 2024 AND c.provider_league_id IN (39, 140, 78, 135, 61) "
            "ORDER BY cs.season DESC, f.kickoff_at DESC LIMIT 2")
        return [int(r[0]) for r in cur.fetchall()]


async def _go(conn: psycopg.Connection, ids: list[int]) -> int:
    provider = ApiFootballProvider(build_client(max_requests=2))
    cfg = load_migration_config()
    try:
        rep = await run_probe(conn, provider, ids, configured={c.league_id: c.name for c in cfg.competitions})
    finally:
        await provider.aclose()
    n = rep.fixtures_returned
    if rep.ids_refusal is None:
        _say(f"/fixtures?ids={'-'.join(map(str, ids))}: {n} fixtures; blocks present: "
             + ", ".join(f"{b} {rep.blocks_present.get(b, 0)}/{n}" for b in BLOCKS))
    else:
        _say(f"/fixtures?ids={'-'.join(map(str, ids))}: refused by the plan")
    if rep.detail_kb_per_fixture is not None:
        _say(f"  detail payload {rep.detail_kb_per_fixture:.1f} KB per fixture (gzip); {rep.detail_rows} rows normalised")
    if rep.ids_verdict == "refused_by_plan":
        _say(f"  RESULT: this plan REFUSES the ids parameter - the provider says: {rep.ids_refusal}")
        _say("          That settles THIS plan only. Probe again on the first day of a paid plan (same command, "
             "2 requests): AVAILABLE -> stay; otherwise price with `scripts.migration capacity --no-ids`.")
    elif rep.ids_batching_available:
        _say("  RESULT: /fixtures?ids= detail batching is AVAILABLE on this account")
    else:
        _say("  RESULT: detail batching is NOT available on this account - price with "
             "`scripts.migration capacity --no-ids`")
    _say(f"/leagues: {rep.coverage_rows} (league, season) coverage rows stored")
    for lid, mine, theirs in rep.name_mismatches:
        _say(f"  NAME CHECK: league {lid} is '{mine}' in config/migration.yaml but '{theirs}' at the provider")
    if not rep.name_mismatches:
        _say("  name check: every configured league id matches the provider's name")
    _say(f"{rep.requests} requests spent (ledger run {rep.run_id})")
    return 0


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="probe_plan", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="spend the 2 requests")
    args = parser.parse_args()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        ids = two_finished_fixtures(conn)
        if len(ids) < 2:
            _say("no two finished top-league fixtures of 2024 or earlier are stored: nothing to probe with")
            return 1
        remaining = build_quota().remaining
        _say(f"today's quota: {remaining} requests left of our budget; the probe spends 2 "
             f"(/fixtures?ids={'-'.join(map(str, ids))} and /leagues)")
        if not args.yes:
            _say("dry run - add --yes to spend them")
            return 0
        if remaining < MIN_REMAINING:
            _say(f"refusing: fewer than {MIN_REMAINING} requests left today; run after 00:00 UTC")
            return 2
        return asyncio.run(_go(conn, ids))


if __name__ == "__main__":
    sys.exit(main())
