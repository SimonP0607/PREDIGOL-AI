"""Settle a match's bets the minute it ends, record how long that took, and measure the line value.

WHY. On 9 Oct 2026 the live follow stored Hangzhou - Shanghai's final whistle at 13:58:18 UTC, but its
pick of the day said "Pendiente" until about 14:07: nothing settled a pick until the next pick-pipeline
pass, and a pass starts every 30 minutes and runs for two to three. Now the live follow and the results
repair hand every match that just ended to ``settle_fixtures``, which settles its picks and the
product's records (picks of the day, parlay legs, users' picks) at once - one match per transaction,
so one slow match never holds the others - and writes how long it took to ``picks.settlement_latency``.
The pipeline's own settlement stays as the safety net, and records its latency too.

TWO PASSES, ONE RESULT. Every write claims its record first (``status <> 'settled'``,
``status = 'PENDING'``), so when the fast path and the pipeline read the same pick, the first to write
settles it and the other skips it. A pick another transaction is settling right now is left to it: the
fast path waits at most ``LOCK_TIMEOUT`` for a row lock, then defers that match to the next pass.

LINE VALUE (``fill_line_value``). For each pick whose match has started, the last pre-match price of the
SAME bookmaker for the same selection: the provider's final pre-match price when we have it
(market.final_prematch_odds, read after the match, stamped before kick-off), else the last pre-match
snapshot we captured. ``lv_raw`` = odds taken / that price - 1; ``lv_devigged`` = odds taken x the last
de-vigged consensus before kick-off - 1. ``is_validated_close`` stays false: neither reference has been
shown to BE the closing line, so this is value against a near-close price, and the screens say so.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

import psycopg
import structlog

from fbi.core import match_state
from fbi.core.clock import now as clock_now
from fbi.picks.engine import settle_open_picks
from fbi.picks.product_settlement import settle_products

log = structlog.get_logger(__name__)

Path = Literal["live_follow", "results_repair", "pipeline"]
LOCK_TIMEOUT = "3s"
LINE_VALUE_WINDOW = timedelta(days=3)
"""Routine passes look at matches started in the last three days; ``since=None`` reaches all history."""
FINAL_PREMATCH_WAIT = timedelta(hours=6)
"""The provider's final pre-match price is asked after the match; past this, the last snapshot is used."""

LATENCY_SQL = """
WITH x AS (
    SELECT f.id, f.status_short, f.kickoff_at,
           (SELECT max(s.observed_at) FROM core.fixture_live_states s
             WHERE s.fixture_id = f.id AND s.status_short = ANY(%(in_play)s)) AS last_in_play_at,
           COALESCE((SELECT min(s.observed_at) FROM core.fixture_live_states s
                      WHERE s.fixture_id = f.id AND s.status_short = ANY(%(ended)s)), r.settled_at) AS observed_at,
           r.settled_at AS result_stored_at, clock_timestamp() AS settled_at
      FROM core.fixtures f LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE f.id = %(fixture)s
)
INSERT INTO picks.settlement_latency (fixture_id, status_short, kickoff_at, last_in_play_at, observed_finished_at,
                                      result_stored_at, settled_at, delay_seconds, path, picks_settled, items_settled)
SELECT id, status_short, kickoff_at, last_in_play_at, observed_at, result_stored_at, settled_at,
       CASE WHEN observed_at IS NULL THEN NULL
            ELSE GREATEST(EXTRACT(EPOCH FROM settled_at - observed_at), 0)::int END,
       %(path)s, %(picks)s, %(items)s
  FROM x
"""


def record_latency(conn: psycopg.Connection[Any], fixture_id: int, *, path: Path, picks: int, items: int) -> None:
    if picks <= 0 and items <= 0:
        return
    with conn.cursor() as cur:
        cur.execute(LATENCY_SQL, {"fixture": fixture_id, "path": path, "picks": picks, "items": items,
                                  "in_play": sorted(match_state.IN_PLAY), "ended": sorted(match_state.ENDED)})


@dataclass
class FastSettlementReport:
    fixtures: int = 0
    picks: int = 0
    items: int = 0
    deferred: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def settle_fixtures(conn: psycopg.Connection[Any], fixture_ids: Iterable[int], *, path: Path,
                    run_id: int | None = None, at: datetime | None = None) -> FastSettlementReport:
    """Settle the bets on these matches now, one match per transaction (a savepoint if the caller has one open).

    A match whose rows another pass holds is deferred, not waited for; any other failure is logged and the
    next match is settled anyway. The pipeline settles whatever is left on its next pass.
    """
    report = FastSettlementReport()
    for fid in sorted(set(fixture_ids)):
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'")
                picks = settle_open_picks(conn, run_id=run_id, fixture_ids=[fid], at=at)
                products = settle_products(conn, at=at or clock_now(), fixture_ids=[fid])
                items = products.by_fixture.get(fid, 0)
                record_latency(conn, fid, path=path, picks=picks.settled, items=items)
        except psycopg.errors.LockNotAvailable:
            report.deferred.append(fid)
            continue
        except psycopg.Error as exc:
            report.errors.append(f"{fid}: {type(exc).__name__}: {exc}"[:300])
            log.error("fast_settlement.failed", fixture=fid, error=type(exc).__name__, detail=str(exc)[:200])
            continue
        if picks.settled or items:
            report.fixtures += 1
            report.picks += picks.settled
            report.items += items
    if report.fixtures or report.deferred or report.errors:
        log.info("fast_settlement.done", path=path, fixtures=report.fixtures, picks=report.picks,
                 items=report.items, deferred=report.deferred, errors=len(report.errors))
    return report


LINE_VALUE_SQL = """
WITH todo AS (
    SELECT p.id, p.fixture_id, p.bookmaker_id, p.market_key, p.selection, p.line, p.market_odds, f.kickoff_at
      FROM picks.picks p
      JOIN core.fixtures f ON f.id = p.fixture_id
      LEFT JOIN picks.pick_line_value lv ON lv.pick_id = p.id
      LEFT JOIN market.final_prematch_checks c ON c.fixture_id = p.fixture_id
     WHERE lv.pick_id IS NULL
       AND f.kickoff_at <= %(at)s
       AND (%(since)s::timestamptz IS NULL OR f.kickoff_at >= %(since)s)
       AND (c.fixture_id IS NOT NULL OR f.kickoff_at <= %(at)s - %(wait)s)
), ref AS (
    SELECT t.id, t.market_odds,
           COALESCE(fp.odds_decimal, sn.odds_decimal) AS close_odds,
           COALESCE(fp.provider_update_at, sn.captured_at) AS close_at,
           COALESCE(fp.minutes_to_ko, sn.minutes_to_ko) AS close_minutes,
           cp.p_fair
      FROM todo t
      LEFT JOIN market.final_prematch_odds fp
        ON fp.fixture_id = t.fixture_id AND fp.bookmaker_id = t.bookmaker_id AND fp.market_key = t.market_key
       AND fp.selection = t.selection AND fp.line = t.line
      LEFT JOIN LATERAL (
          SELECT s.odds_decimal, s.captured_at, s.minutes_to_ko FROM market.odds_snapshots s
           WHERE s.fixture_id = t.fixture_id AND s.market_key = t.market_key AND s.selection = t.selection
             AND s.line = t.line AND s.bookmaker_id = t.bookmaker_id AND s.source = 'prematch'
             AND s.captured_at < t.kickoff_at
           ORDER BY s.captured_at DESC LIMIT 1) sn ON fp.fixture_id IS NULL
      LEFT JOIN LATERAL (
          SELECT m.p_fair FROM market.market_consensus m
           WHERE m.fixture_id = t.fixture_id AND m.market_key = t.market_key AND m.selection = t.selection
             AND m.line = t.line AND m.devig_method = 'shin' AND m.as_of < t.kickoff_at
           ORDER BY m.as_of DESC LIMIT 1) cp ON true
)
INSERT INTO picks.pick_line_value (pick_id, near_close_odds, near_close_captured_at, near_close_source,
                                   near_close_minutes_to_ko, lv_raw, lv_devigged, is_validated_close,
                                   close_validation_method, computed_at)
SELECT id, close_odds, close_at, 'prematch', GREATEST(close_minutes, 0), round(market_odds / close_odds - 1, 6),
       CASE WHEN p_fair IS NULL THEN NULL ELSE round(market_odds * p_fair - 1, 6) END, false, NULL, %(at)s
  FROM ref
 WHERE close_odds IS NOT NULL
ON CONFLICT (pick_id) DO NOTHING
"""


def fill_line_value(conn: psycopg.Connection[Any], *, at: datetime, all_history: bool = False) -> int:
    """Write the line value of every started pick that has none yet; returns how many were written.

    The routine pass looks at the last ``LINE_VALUE_WINDOW``; ``all_history`` reaches every pick."""
    start = None if all_history else at - LINE_VALUE_WINDOW
    with conn.cursor() as cur:
        cur.execute(LINE_VALUE_SQL, {"at": at, "since": start, "wait": FINAL_PREMATCH_WAIT})
        return max(cur.rowcount, 0)
