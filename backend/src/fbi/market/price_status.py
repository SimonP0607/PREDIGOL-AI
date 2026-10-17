"""Whether an upcoming match has a price in each market, and if not, why.

A pick is a comparison with a price, so "no pick" has several honest causes that the
product must not blur into one, and none of them may be papered over with an invented or
estimated price:

  PRICED             priced by at least MIN_BOOKMAKERS bookmakers at the latest capture
  THIN_PRICE         priced by a single bookmaker
  PRICE_PENDING      not priced yet, and not for lack of the provider: no capture window has
                     reached the match, or one has and the capture is still due
  PRICE_UNAVAILABLE  asked for at a capture window, and the provider had no price for this
                     market (none at all, or other markets only)
  NOT_COVERED        the provider's coverage flag says no odds for this competition, and
                     nothing was ever priced

Database only: no provider request.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth.gate import MIN_BOOKMAKERS

CORE_MARKETS: tuple[tuple[str, Decimal], ...] = (("1X2", Decimal("0")), ("OU", Decimal("2.5")),
                                                 ("BTTS", Decimal("0")))
"""The markets the product shows first; Over/Under at its 2.5 line."""


class PriceStatus(StrEnum):
    PRICED = "PRICED"
    THIN_PRICE = "THIN_PRICE"
    PRICE_PENDING = "PRICE_PENDING"
    PRICE_UNAVAILABLE = "PRICE_UNAVAILABLE"
    NOT_COVERED = "NOT_COVERED"


ASKED_LOOKBACK = timedelta(days=20)
"""Pre-match prices appear up to ~19 days before kick-off (measured); nothing is asked earlier,
and the bound lets the payload index serve the lookup."""

UNPRICED = frozenset({PriceStatus.PRICE_PENDING, PriceStatus.PRICE_UNAVAILABLE, PriceStatus.NOT_COVERED})


@dataclass(frozen=True, slots=True)
class MarketPrice:
    fixture_id: int
    market_key: str
    line: Decimal
    status: PriceStatus
    bookmakers: int
    last_capture: datetime | None
    last_asked: datetime | None


FIXTURES_SQL = """
SELECT f.id, f.provider_fixture_id, f.kickoff_at,
       CASE WHEN EXISTS (SELECT 1 FROM market.odds_mapping_seen m WHERE m.provider_fixture_id = f.provider_fixture_id)
            THEN true ELSE lc.odds END AS covered
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE f.id = ANY(%(ids)s)
"""
"""``covered``: the provider's coverage flag for the season, overruled by /odds/mapping when it lists the fixture."""

ASKED_SQL = """
SELECT pid AS provider_fixture_id, max(at) AS last_asked FROM (
    SELECT (p.params->>'fixture')::bigint AS pid, p.fetched_at AS at
      FROM raw.ingestion_payloads p
     WHERE p.endpoint = '/odds' AND p.fetched_at >= %(since)s
       AND p.params ? 'fixture' AND p.params->>'fixture' = ANY(%(pids)s)
    UNION ALL
    SELECT a.provider_fixture_id, a.asked_at FROM market.odds_asks a
     WHERE a.asked_at >= %(since)s AND a.provider_fixture_id = ANY(%(ipids)s)) x
 GROUP BY 1
"""
"""When /odds was last asked for each fixture. The RAW index keeps one row per distinct answer, so an empty answer
asked again leaves no new row there; market.odds_asks (0064, 5 Oct 2026) records every ask."""

BOOKS_SQL = """
WITH latest AS (
    SELECT fixture_id, market_key, line, max(captured_at) AS last_capture
      FROM market.odds_snapshots
     WHERE fixture_id = ANY(%(ids)s) AND source = 'prematch'
     GROUP BY 1, 2, 3
)
SELECT l.fixture_id, l.market_key, l.line, l.last_capture,
       (SELECT count(DISTINCT s.bookmaker_id) FROM market.odds_snapshots s
         WHERE s.fixture_id = l.fixture_id AND s.market_key = l.market_key AND s.line = l.line
           AND s.source = 'prematch' AND s.captured_at > l.last_capture - interval '20 minutes') AS bookmakers
  FROM latest l
"""


def market_prices(conn: psycopg.Connection[Any], fixture_ids: list[int], *, at: datetime,
                  markets: tuple[tuple[str, Decimal], ...] = CORE_MARKETS) -> list[MarketPrice]:
    """The status of each requested market of each fixture, as of ``at``."""
    from fbi.truth.freshness import Freshness, price_state

    if not fixture_ids:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"ids": fixture_ids})
        fixtures = {int(r["id"]): r for r in cur.fetchall()}
        if not fixtures:
            return []
        pids = [str(r["provider_fixture_id"]) for r in fixtures.values()]
        since = min(r["kickoff_at"] for r in fixtures.values()) - ASKED_LOOKBACK
        cur.execute(ASKED_SQL, {"pids": pids, "ipids": [int(p) for p in pids], "since": since})
        asked = {int(r["provider_fixture_id"]): r["last_asked"] for r in cur.fetchall()}
        cur.execute(BOOKS_SQL, {"ids": fixture_ids})
        books: dict[int, dict[tuple[str, Decimal], dict[str, Any]]] = defaultdict(dict)
        for r in cur.fetchall():
            books[int(r["fixture_id"])][(str(r["market_key"]), Decimal(r["line"]))] = r
    out: list[MarketPrice] = []
    for fid in fixture_ids:
        f = fixtures.get(fid)
        if f is None:
            continue
        last_asked = asked.get(int(f["provider_fixture_id"]))
        priced_any = bool(books.get(fid))
        last_any = max((b["last_capture"] for b in books.get(fid, {}).values()), default=None)
        fixture_state, _ = price_state(kickoff=f["kickoff_at"], at=at, last_capture=last_any,
                                       last_asked=last_asked, covered=f["covered"])
        for market, line in markets:
            b = books.get(fid, {}).get((market, line))
            n = int(b["bookmakers"]) if b else 0
            if n >= MIN_BOOKMAKERS:
                status = PriceStatus.PRICED
            elif n == 1:
                status = PriceStatus.THIN_PRICE
            elif f["covered"] is False and not priced_any:
                status = PriceStatus.NOT_COVERED
            elif (priced_any and last_asked is not None) or fixture_state is Freshness.UNAVAILABLE:
                status = PriceStatus.PRICE_UNAVAILABLE
            else:
                status = PriceStatus.PRICE_PENDING
            out.append(MarketPrice(fid, market, line, status, n, b["last_capture"] if b else None, last_asked))
    return out
