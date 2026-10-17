"""Fetch the squads' teams for the tracked current seasons, and settle what each
competition actually is.

    python -m scripts.sync_teams                 # announce the cost, spend nothing
    python -m scripts.sync_teams --yes
    python -m scripts.sync_teams --scopes-only   # re-decide from teams already stored, no request

Cost: one /teams call per tracked current season.

Two things come out of it. The team, venue and season-membership catalogue - /teams is the
only endpoint that carries a team's founding year, country and home venue - and the fact
that decides whether a competition is club or national-team football, which is published
on the team (``national: true``) and nowhere on the competition. Without it the World Cup
and the Champions League are indistinguishable: both are Cup with country World.

Exit status: 0 good, 1 some season failed (the rest still ran), 2 usage error.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import psycopg
from psycopg.rows import dict_row

from fbi.catalog.scopes import resolve_scopes
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion.identity import apply_teams
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.api_football import ApiFootballProvider
from fbi.providers.api_football.build import build_client
from fbi.providers.api_football.details import iter_teams

SEASONS_SQL = """
SELECT s.id AS season_id, s.season, c.provider_league_id, c.name
  FROM core.competition_seasons s
  JOIN core.competitions c ON c.id = s.competition_id
 WHERE c.is_tracked AND s.is_current
 ORDER BY c.tier NULLS LAST, c.provider_league_id
"""


async def _main(yes: bool, scopes_only: bool) -> int:
    configure_logging(settings.runtime.log_level)
    failures: list[str] = []

    with psycopg.connect(settings.database.psycopg_url) as conn:
        if not scopes_only:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(SEASONS_SQL)
                seasons = cur.fetchall()
            print(f"{len(seasons)} tracked current season(s); this will spend exactly "
                  f"{len(seasons)} provider request(s).")
            if not yes:
                print("re-run with --yes to spend them, or --scopes-only to decide from what is "
                      "already stored")
                return 0

            # build_client, never a locally constructed one: that is what attaches the
            # persistent request budget, so these calls are counted across processes.
            provider = ApiFootballProvider(build_client())
            ledger, counters = RunLedger(conn), RunCounters()
            run_id = ledger.open("teams_sync", params={"seasons": len(seasons)})
            try:
                for row in seasons:
                    league, season = int(row["provider_league_id"]), int(row["season"])
                    try:
                        raw = await provider.fetch_teams(league_id=league, season=season)
                    except Exception as exc:  # one league failing must not stop the rest
                        failures.append(f"league {league} season {season}: {type(exc).__name__}: {exc}")
                        counters.errors.append(f"league {league}: {exc}")
                        continue
                    counters.api_calls += 1
                    counters.payloads_stored += ledger.record_payloads(run_id, [raw])
                    teams = list(iter_teams(raw.body)) if isinstance(raw.body, dict) else []
                    report = apply_teams(
                        conn, teams, payload_hash=raw.payload_hash, fetched_at=raw.fetched_at,
                        competition_season_id=int(row["season_id"]),
                    )
                    counters.rows_normalized += len(teams)
                    counters.rows_inserted += report.rows
                    conn.commit()
                    print(f"  {league:>5} {str(row['name'])[:38]:<38} {len(teams):>3} team(s), "
                          f"{report.rows} row(s)")
            finally:
                ledger.close(run_id, counters)
                conn.commit()
                await provider.aclose()

        scopes = resolve_scopes(conn)

    print("\nwhat each competition is, decided from the teams that played:")
    print(f"  national-team football : {len(scopes.resolved_national)}")
    print(f"  club football          : {len(scopes.resolved_club)}")
    print(f"  friendlies, weight 0   : {len(scopes.friendlies_weighted_zero)}")
    print(f"  already correct        : {scopes.unchanged}")
    for label, entries in (("NO EVIDENCE", scopes.no_evidence),
                           ("CONTRADICTORY", scopes.contradictory)):
        if entries:
            print(f"  {label} ({len(entries)}), recorded in audit.data_quality_issues:")
            for entry in entries[:15]:
                print(f"    {entry}")
    for problem in failures:
        print(f"  FAILED {problem}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="sync_teams", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="actually spend the requests")
    parser.add_argument("--scopes-only", action="store_true",
                        help="no request: re-decide scopes from teams already stored")
    args = parser.parse_args()
    return asyncio.run(_main(args.yes, args.scopes_only))


if __name__ == "__main__":
    sys.exit(main())
