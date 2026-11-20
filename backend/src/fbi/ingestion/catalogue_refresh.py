"""Once a day, ask the provider which season of each competition is current.

One request: ``/leagues`` with no parameter returns every competition with every
season, its dates, whether it is current and its coverage flags. Nothing else
refreshed them: ``core.competition_seasons`` and ``raw.league_coverage`` were
written when the catalogue was built and then only by hand, so on 4 Oct 2026 the
Italian Super Cup's 2026 edition - current at the provider - did not exist for us,
five seasons had the wrong end date and 25 coverage flags were out of date. A new
season the database does not know is a season the worker never fetches.

Every competition we know gets its seasons rewritten (``refresh_seasons``, the only
writer of ``is_current``); every league's coverage flags are stored, tracked or not,
because the catalogue is chosen from them.

With ``FBI_CATALOGUE_WATCH`` on (OFF by default; plan PM, PM-03-08, DOC-010) the refresh then compares what the provider lists with
the baseline of ``config/catalogue_watch.yaml`` (``fbi.catalog.watch``, by identifier, 0 requests): a new league of a priority
country, or a new season of a discontinued or cyclical competition, is logged as ``catalogue_watch.finding`` (warning) and goes
into the run's notes. The watch never fails the refresh.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.catalog import watch
from fbi.catalog.activation import refresh_seasons
from fbi.core.clock import now
from fbi.core.errors import ProviderError
from fbi.core.logging import get_logger
from fbi.ingestion.details import apply_coverage
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.api_football.normalize import iter_league_seasons

log = get_logger(__name__)


async def refresh_catalogue(conn: psycopg.Connection, provider: Any, *, at: datetime | None = None) -> RunCounters:
    moment = at or now()
    ledger = RunLedger(conn)
    run_id = ledger.open("catalogue_refresh", params={}, scheduled_for=moment)
    counters = RunCounters()
    notes = ""
    try:
        try:
            coverage, raw = await provider.fetch_coverage()
        except ProviderError as exc:
            counters.api_calls += 1
            counters.errors.append(str(exc))
            return counters
        counters.api_calls += 1
        counters.payloads_stored += ledger.record_payloads(run_id, [raw])
        observed = ledger.indexed_at(raw.payload_hash) or raw.fetched_at
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT provider_league_id FROM core.competitions")
            known = {int(r[0]) for r in cur.fetchall()}
        seasons = [s for s in iter_league_seasons(raw.body) if s.provider_league_id in known]
        updates = refresh_seasons(conn, seasons, dry_run=False)
        flags = apply_coverage(conn, coverage, payload_hash=raw.payload_hash, fetched_at=observed)
        changed = [u for u in updates if u.was_current != u.now_current]
        counters.rows_normalized = len(seasons)
        counters.rows_updated = sum(u.seasons_written for u in updates) + flags
        conn.commit()
        notes = (f"{len(updates)} competitions, {len(seasons)} seasons, {flags} coverage rows; current season changed "
                 f"for {len(changed)}: " + ", ".join(f"{u.name} {u.was_current}->{u.now_current}" for u in changed[:10]))
        if watch.watch_on():
            notes += "; " + watch_catalogue(conn)
        log.info("catalogue_refresh.done", competitions=len(updates), seasons=len(seasons), coverage=flags,
                 current_changed=len(changed))
    finally:
        ledger.close(run_id, counters, notes=notes or None)
    return counters


def watch_catalogue(conn: psycopg.Connection) -> str:
    """PM-03-08: the watch over what was just stored, as the ledger's note. A failure is logged and noted, never raised."""
    try:
        found = watch.check(conn)
    except Exception as exc:  # the watch must never cost the day's catalogue
        conn.rollback()
        log.warning("catalogue_watch.failed", error=str(exc)[:300])
        return f"watch failed: {type(exc).__name__}"
    for f in found:
        log.warning("catalogue_watch.finding", kind=f.kind, league=f.league_id, name=f.name, country=f.country,
                    season=f.season, detail=f.detail)
    return watch.notes(found)
