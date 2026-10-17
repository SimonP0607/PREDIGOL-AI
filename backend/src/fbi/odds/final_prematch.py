"""The provider's last pre-match prices, read after the match.

API-Football keeps pre-match odds for 7 days after a fixture. Read after kick-off, /odds
answers with each bookmaker's LAST pre-match price and the provider's own ``update`` stamp
(measured 4 Oct 2026: a match five days old came back with nine bookmakers, stamped 30
minutes before kick-off - closer to the close than the T-3 h capture window can be).

What this recovers, and what it must never be mistaken for:

* It is the near-closing line: the price the market settled on, for every tracked match the
  provider prices - including the ones the capture missed while the worker was down.
* It is NOT a capture. It did not exist for us before kick-off, so no pick, no forecast and
  no decision may read it. It lives in its own table (market.final_prematch_odds) and is
  read by evaluation (closing-line value), coverage and research only.
* A stamp at or after kick-off may be an in-play price. Such an answer is refused whole and
  recorded as ``after_kickoff``.

Each fixture is asked once (market.final_prematch_checks), oldest first so the ones about to
leave the provider's 7-day history go before the rest.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.core.clock import now
from fbi.core.errors import ProviderError
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.odds.repository import OddsRepository
from fbi.providers.api_football.provider import FinalPrematch

log = structlog.get_logger(__name__)

RETENTION_DAYS = 7
"""The provider's documented history of pre-match odds (a match 8 days old answered empty)."""
ASK_WITHIN_DAYS = 6
"""A day's margin inside the retention."""
ASK_AFTER_MINUTES = 150
"""The match is over; its last pre-match update was fixed at kick-off."""
MAX_PER_RUN = 300


class FinalPrematchSource(Protocol):
    async def fetch_final_prematch_odds(self, *, provider_fixture_id: int, kickoff_at: datetime) -> FinalPrematch: ...


DUE_SQL = """
SELECT f.id, f.provider_fixture_id, f.kickoff_at
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
  LEFT JOIN market.final_prematch_checks k ON k.fixture_id = f.id
 WHERE c.is_tracked AND f.status_group = 'finished' AND k.fixture_id IS NULL
   AND f.kickoff_at BETWEEN %(at)s - make_interval(days => %(days)s) AND %(at)s - make_interval(mins => %(after)s)
 ORDER BY (lc.odds IS FALSE), f.kickoff_at
 LIMIT %(limit)s
"""


@dataclass
class FinalPrematchReport:
    run_id: int | None = None
    due: int = 0
    asked: int = 0
    priced: int = 0
    empty: int = 0
    after_kickoff: int = 0
    quotes: int = 0
    requests: int = 0
    minutes_before_kickoff: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def median_minutes_before_kickoff(self) -> float | None:
        return float(statistics.median(self.minutes_before_kickoff)) if self.minutes_before_kickoff else None


def due_fixtures(conn: psycopg.Connection[Any], *, at: datetime, limit: int = MAX_PER_RUN,
                 days: int = ASK_WITHIN_DAYS) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DUE_SQL, {"at": at, "days": days, "after": ASK_AFTER_MINUTES, "limit": limit})
        return list(cur.fetchall())


def _write(conn: psycopg.Connection[Any], fixture_id: int, result: FinalPrematch, *, fetched_at: datetime) -> int:
    assert result.update_at is not None
    repo = OddsRepository(conn)
    books = repo.ensure_bookmakers(result.quotes)
    rows = [(fixture_id, books[q.provider_bookmaker_id], q.market_key, q.selection, q.line, q.odds_decimal,
             result.update_at, q.minutes_to_ko, fetched_at, q.payload_hash) for q in result.quotes]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO market.final_prematch_odds (fixture_id, bookmaker_id, market_key, selection, line, "
            "odds_decimal, provider_update_at, minutes_to_ko, fetched_at, payload_hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", rows)
    return len(rows)


def _check(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, outcome: str,
           result: FinalPrematch, quotes: int, payload_hash: str | None) -> None:
    books = len({q.provider_bookmaker_id for q in result.quotes})
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO market.final_prematch_checks (fixture_id, checked_at, outcome, provider_update_at, "
            "bookmakers, quotes, payload_hash) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (fixture_id) DO NOTHING",
            (fixture_id, at, outcome, result.update_at, books, quotes, payload_hash))


async def recover_final_prematch(conn: psycopg.Connection[Any], provider: FinalPrematchSource, *,
                                 at: datetime | None = None, limit: int = MAX_PER_RUN) -> FinalPrematchReport:
    """Ask /odds once for every tracked match played in the last six days and not yet asked."""
    moment = at or now()
    report = FinalPrematchReport()
    due = due_fixtures(conn, at=moment, limit=limit)
    report.due = len(due)
    if not due:
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open("final_prematch", params={"fixtures": len(due)}, scheduled_for=moment)
    report.run_id = run_id
    counters = RunCounters()
    try:
        for f in due:
            fixture_id, kickoff = int(f["id"]), f["kickoff_at"]
            try:
                result = await provider.fetch_final_prematch_odds(
                    provider_fixture_id=int(f["provider_fixture_id"]), kickoff_at=kickoff)
            except ProviderError as exc:
                report.requests += 1
                counters.api_calls += 1
                counters.errors.append(str(exc))
                report.errors.append(str(exc))
                log.warning("final_prematch.fetch_failed", fixture=f["provider_fixture_id"], error=str(exc))
                continue
            report.requests += len(result.raws)
            counters.api_calls += len(result.raws)
            counters.payloads_stored += ledger.record_payloads(run_id, result.raws)
            payload_hash = result.raws[0].payload_hash if result.raws else None
            fetched_at = (ledger.indexed_at(payload_hash) if payload_hash else None) or moment
            report.asked += 1
            if result.quotes:
                if result.update_at is None or result.update_at >= kickoff:  # the provider method refuses these
                    raise AssertionError("a final pre-match price stamped at or after kick-off")
                written = _write(conn, fixture_id, result, fetched_at=fetched_at)
                report.priced += 1
                report.quotes += written
                report.minutes_before_kickoff.append(int((kickoff - result.update_at).total_seconds() // 60))
                _check(conn, fixture_id, at=moment, outcome="priced", result=result, quotes=written,
                       payload_hash=payload_hash)
            elif result.refused_after_kickoff:
                report.after_kickoff += 1
                _check(conn, fixture_id, at=moment, outcome="after_kickoff", result=result, quotes=0,
                       payload_hash=payload_hash)
            else:
                report.empty += 1
                _check(conn, fixture_id, at=moment, outcome="empty", result=result, quotes=0,
                       payload_hash=payload_hash)
            conn.commit()
        counters.rows_inserted = report.quotes
        counters.rows_normalized = report.priced
    finally:
        ledger.close(run_id, counters, notes=(
            f"asked {report.asked} of {report.due}: {report.priced} priced ({report.quotes} prices, median "
            f"{report.median_minutes_before_kickoff} min before kick-off), {report.empty} empty, "
            f"{report.after_kickoff} refused (stamped after kick-off); {report.requests} requests"))
    log.info("final_prematch.done", asked=report.asked, priced=report.priced, empty=report.empty,
             after_kickoff=report.after_kickoff, quotes=report.quotes)
    return report
