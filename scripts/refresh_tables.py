"""Re-read league tables now: every tracked current season with a table, cups included.

    python -m scripts.refresh_tables              # what the 12-hour job does, now (cups with tables included)
    python -m scripts.refresh_tables --legacy     # also every tracked season whose newest snapshot was written
                                                  # by the pre-0048 writer (one row per team: a second table -
                                                  # Apertura/Clausura, a third-place ranking - was dropped)
    python -m scripts.refresh_tables --dry-run    # list the seasons, no request

One /standings request per season through the normal refresh path: the answer is a raw payload,
the check is recorded in core.context_checks, rows go through the same writer. When the provider's
table is the very payload we already hold, the writer files the rows under the time that payload was
first seen; rows the old writer had dropped are then ADDED to that snapshot (nothing is updated or
deleted), and each such season is written to audit.data_repairs (rule standings_dropped_tables) with
the payload hash as evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.ingestion.context_refresh import HAS_TABLE, _refresh_one, _Totals
from fbi.ingestion.fixtures import ActiveSeason
from fbi.ingestion.ledger import RunCounters, RunLedger

CURRENT_SQL = ("SELECT cs.id, c.provider_league_id, cs.season, c.name FROM core.competition_seasons cs "
               "JOIN core.competitions c ON c.id = cs.competition_id "
               f"WHERE c.is_tracked AND cs.is_current AND {HAS_TABLE} ORDER BY c.provider_league_id")
LEGACY_SQL = """
SELECT cs.id, c.provider_league_id, cs.season, c.name FROM core.competition_seasons cs
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND EXISTS (
       SELECT 1 FROM core.standings s WHERE s.competition_season_id = cs.id
          AND s.snapshot_at = (SELECT max(snapshot_at) FROM core.standings WHERE competition_season_id = cs.id)
          AND s.payload_hash IS NULL)
 ORDER BY c.provider_league_id, cs.season
"""


def seasons(conn: psycopg.Connection[Any], legacy: bool) -> list[ActiveSeason]:
    out: dict[int, ActiveSeason] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        for sql in (CURRENT_SQL, LEGACY_SQL) if legacy else (CURRENT_SQL,):
            cur.execute(sql)
            for a, b, c, d in cur.fetchall():
                out[int(a)] = ActiveSeason(int(a), int(b), int(c), str(d))
    return list(out.values())


def snapshot_rows(conn: psycopg.Connection[Any], cs_id: int) -> tuple[Any, int]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT max(snapshot_at) FROM core.standings WHERE competition_season_id = %s", (cs_id,))
        at = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("SELECT count(*) FROM core.standings WHERE competition_season_id = %s AND snapshot_at = %s",
                    (cs_id, at))
        return at, int(cur.fetchone()[0])  # type: ignore[index]


async def run(args: argparse.Namespace) -> int:
    from fbi.providers.api_football import ApiFootballProvider
    from fbi.providers.api_football.build import build_client

    with psycopg.connect(settings.database.psycopg_url) as conn:
        todo = seasons(conn, args.legacy)
        if args.dry_run:
            print(json.dumps([s.__dict__ for s in todo], indent=1))
            return 0
        provider = ApiFootballProvider(build_client(max_requests=args.max_requests))
        ledger = RunLedger(conn)
        at = now()
        run_id = ledger.open("context_refresh_manual", params={"seasons": len(todo), "legacy": args.legacy},
                             scheduled_for=at)
        counters, totals = RunCounters(), _Totals()
        repaired = []
        try:
            for s in todo:
                before_at, before_n = snapshot_rows(conn, s.competition_season_id)
                if not await _refresh_one(conn, provider, ledger, run_id, counters, totals, s, "standings"):
                    break
                after_at, after_n = snapshot_rows(conn, s.competition_season_id)
                if before_at is not None and after_at == before_at and after_n > before_n:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO audit.data_repairs (rule, entity, entity_id, provider_ref, field, before_value, "
                            "after_value, reason, evidence) VALUES ('standings_dropped_tables', 'core.standings', %s, "
                            "%s, 'rows in snapshot', %s, %s, %s, %s)",
                            (s.competition_season_id, s.provider_league_id, f"{before_n} rows at {before_at}",
                             f"{after_n} rows at {after_at}",
                             "the pre-0048 writer kept one row per team; the rows of the season's other tables were "
                             "added from the same provider payload (nothing updated or deleted)",
                             f"/standings league={s.provider_league_id} season={s.season}"))
                    conn.commit()
                    repaired.append((s.provider_league_id, s.season, before_n, after_n))
        finally:
            ledger.close(run_id, counters, notes=totals.notes() + f"; {len(repaired)} snapshots completed")
            conn.commit()
            await provider.aclose()
    print(json.dumps({"seasons": len(todo), "requests": counters.api_calls, "tables_written": totals.tables,
                      "errors": counters.errors[:10], "stopped": counters.stopped_early,
                      "snapshots_completed": repaired}, indent=1, default=str))
    return 0 if not counters.errors and not counters.stopped_early else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="refresh_tables", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-requests", type=int, default=400)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
