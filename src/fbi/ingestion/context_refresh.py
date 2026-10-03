"""Keep the current season's context fresh: league tables and injury reports.

Both were only ever fetched by the historical backfill, once per season: on
3 Oct 2026 the newest Premier League table in the database was from 29 Sep,
and an injury reported on Thursday for Saturday's match was not there. The
Match Center's "context" was therefore context for a week ago.

One request per active season for each (``/standings`` for leagues only - a
cup has no table to return - and ``/injuries`` for every competition), every
twelve hours: about 400 requests a day against a 60,000 guard. Tables are
appended as snapshots (core.standings is keyed on the snapshot time), so the
history of a table is kept; injuries go through the same monotonic writer the
backfill uses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.errors import ProviderError, QuotaExhaustedError
from fbi.core.logging import get_logger
from fbi.ingestion.details import apply_injuries, apply_standings
from fbi.ingestion.fixtures import active_seasons
from fbi.ingestion.ledger import RunCounters, RunLedger

log = get_logger(__name__)


def _league_type(conn: psycopg.Connection) -> dict[int, str]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT provider_league_id, type FROM core.competitions WHERE is_tracked")
        return {int(a): str(b) for a, b in cur.fetchall()}


async def refresh_context(conn: psycopg.Connection, provider: Any, *, at: datetime | None = None,
                          max_requests: int = 400) -> RunCounters:
    moment = at or now()
    seasons = active_seasons(conn)
    kinds = _league_type(conn)
    ledger = RunLedger(conn)
    run_id = ledger.open("context_refresh", params={"seasons": len(seasons)}, scheduled_for=moment)
    counters = RunCounters()
    tables = injuries = 0
    try:
        for s in seasons:
            for what in ("standings", "injuries"):
                if what == "standings" and kinds.get(s.provider_league_id) != "league":
                    continue
                if counters.api_calls >= max_requests:
                    counters.stopped_early = f"request cap {max_requests}"
                    break
                try:
                    if what == "standings":
                        refs, raw = await provider.fetch_standings(league_id=s.provider_league_id, season=s.season)
                    else:
                        absences, raw = await provider.fetch_injuries(league_id=s.provider_league_id,
                                                                      season=s.season)
                except QuotaExhaustedError as exc:
                    counters.errors.append(str(exc))
                    counters.stopped_early = "quota"
                    break
                except ProviderError as exc:
                    counters.api_calls += 1
                    counters.errors.append(f"{s.name} {s.season} {what}: {exc}")
                    continue
                counters.api_calls += 1
                counters.payloads_stored += ledger.record_payloads(run_id, [raw])
                observed = ledger.indexed_at(raw.payload_hash) or raw.fetched_at
                if what == "standings":
                    n = apply_standings(conn, refs, fetched_at=observed)
                    tables += 1 if n else 0
                else:
                    n = apply_injuries(conn, absences, payload_hash=raw.payload_hash, fetched_at=observed)
                    injuries += n
                counters.rows_inserted += n
                conn.commit()
            if counters.stopped_early:
                break
    finally:
        ledger.close(run_id, counters, notes=f"{tables} tables, {injuries} absence rows")
        conn.commit()
    log.info("context_refresh.done", seasons=len(seasons), requests=counters.api_calls, tables=tables,
             absences=injuries, errors=len(counters.errors))
    return counters
