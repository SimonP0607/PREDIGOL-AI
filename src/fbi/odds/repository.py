"""Persistence for the odds time series.

Idempotency is a property of the schema, not of this code: the primary key of
``market.odds_snapshots`` includes ``captured_at``, so writes use
``ON CONFLICT DO NOTHING``. Re-running a capture can never corrupt history and
can never silently overwrite a price - the failure that cost the legacy system
its entire odds history.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.providers.base import OddsQuote

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WriteResult:
    offered: int
    written: int
    skipped_existing: int
    skipped_unknown_fixture: int
    skipped_unknown_market: int


class OddsRepository:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def ensure_bookmakers(self, quotes: Sequence[OddsQuote]) -> dict[int, int]:
        """Upsert bookmakers, returning provider_id -> internal id."""
        seen = {q.provider_bookmaker_id: q.bookmaker_name for q in quotes}
        if not seen:
            return {}
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.executemany(
                "INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) "
                "ON CONFLICT (provider_bookmaker_id) DO UPDATE SET name = EXCLUDED.name",
                list(seen.items()),
            )
            cur.execute(
                "SELECT provider_bookmaker_id, id FROM market.bookmakers "
                "WHERE provider_bookmaker_id = ANY(%s)",
                (list(seen),),
            )
            return dict(cur.fetchall())

    def _fixture_ids(self, quotes: Sequence[OddsQuote]) -> dict[int, int]:
        provider_ids = sorted({q.provider_fixture_id for q in quotes})
        if not provider_ids:
            return {}
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT provider_fixture_id, id FROM core.fixtures WHERE provider_fixture_id = ANY(%s)",
                (provider_ids,),
            )
            return dict(cur.fetchall())

    def fixture_ids_of(self, quotes: Sequence[OddsQuote]) -> list[int]:
        """Our fixture ids for the provider fixtures these quotes belong to."""
        return sorted(set(self._fixture_ids(quotes).values())) if quotes else []

    def _known_markets(self) -> set[str]:
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT key FROM market.markets WHERE is_tracked")
            return {row[0] for row in cur.fetchall()}

    def write_snapshots(self, quotes: Sequence[OddsQuote]) -> WriteResult:
        if not quotes:
            return WriteResult(0, 0, 0, 0, 0)

        bookmakers = self.ensure_bookmakers(quotes)
        fixtures = self._fixture_ids(quotes)
        markets = self._known_markets()

        rows: list[tuple[object, ...]] = []
        unknown_fixture = unknown_market = 0
        for q in quotes:
            fixture_id = fixtures.get(q.provider_fixture_id)
            if fixture_id is None:
                unknown_fixture += 1
                continue
            if q.market_key not in markets:
                unknown_market += 1
                continue
            rows.append(
                (
                    fixture_id,
                    bookmakers[q.provider_bookmaker_id],
                    q.market_key,
                    q.selection,
                    q.line,
                    q.odds_decimal,
                    q.captured_at,
                    q.minutes_to_ko,
                    q.source,
                    q.payload_hash,
                )
            )

        written = 0
        if rows:
            with self._conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO market.odds_snapshots "
                    "(fixture_id,bookmaker_id,market_key,selection,line,odds_decimal,"
                    " captured_at,minutes_to_ko,source,payload_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    rows,
                    returning=False,
                )
                written = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        result = WriteResult(
            offered=len(quotes),
            written=written,
            skipped_existing=max(0, len(rows) - written),
            skipped_unknown_fixture=unknown_fixture,
            skipped_unknown_market=unknown_market,
        )
        if unknown_fixture or unknown_market:
            log.warning(
                "odds.rows_dropped",
                unknown_fixture=unknown_fixture,
                unknown_market=unknown_market,
            )
        return result

    def upsert_near_close(self, quotes: Sequence[OddsQuote]) -> int:
        """Materialise the latest pre-kickoff price we managed to capture.

        A PROJECTION OF THE SERIES, NOT A SECOND RECORDING. The values are read
        back out of ``market.odds_snapshots`` rather than taken from the quote in
        memory, so the near-close row cannot disagree with the price the series
        holds - which is also what the schema now insists on, with a composite
        foreign key onto the series and a trigger comparing the values.

        Deliberately NOT called a closing line. ``is_validated_close`` stays
        false and ``minutes_to_ko`` records how far from kick-off this actually
        was, so nobody downstream has to guess.
        """
        if not quotes:
            return 0
        bookmakers = self.ensure_bookmakers(quotes)
        fixtures = self._fixture_ids(quotes)
        markets = self._known_markets()

        keys = [
            (fixtures[q.provider_fixture_id], bookmakers[q.provider_bookmaker_id], q.market_key,
             q.selection, q.line, q.captured_at)
            for q in quotes
            if q.provider_fixture_id in fixtures and q.market_key in markets
        ]
        if not keys:
            return 0
        columns = list(zip(*keys, strict=True))
        with self._conn.cursor() as cur:
            cur.execute(
                """
                WITH wanted AS (
                    SELECT * FROM unnest(%s::bigint[], %s::integer[], %s::text[], %s::text[],
                                         %s::numeric[], %s::timestamptz[])
                        AS k(fixture_id, bookmaker_id, market_key, selection, line, captured_at)
                )
                INSERT INTO market.near_close_snapshots
                    (fixture_id, bookmaker_id, market_key, selection, line, odds_decimal,
                     captured_at, minutes_to_ko, source, payload_hash)
                SELECT o.fixture_id, o.bookmaker_id, o.market_key, o.selection, o.line,
                       o.odds_decimal, o.captured_at, o.minutes_to_ko, o.source, o.payload_hash
                  FROM market.odds_snapshots o
                  JOIN wanted k USING (fixture_id, bookmaker_id, market_key, selection, line,
                                       captured_at)
                ON CONFLICT (fixture_id, bookmaker_id, market_key, selection, line) DO UPDATE SET
                    odds_decimal    = EXCLUDED.odds_decimal,
                    captured_at     = EXCLUDED.captured_at,
                    minutes_to_ko   = EXCLUDED.minutes_to_ko,
                    source          = EXCLUDED.source,
                    payload_hash    = EXCLUDED.payload_hash,
                    materialised_at = now()
                WHERE market.near_close_snapshots.minutes_to_ko > EXCLUDED.minutes_to_ko
                """,
                [list(col) for col in columns],
            )
            affected = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        if affected < len(keys):
            log.info("near_close.kept_closer_snapshot", offered=len(keys), written=affected)
        return affected

    def last_asked(self, *, provider_fixture_ids: Sequence[int], since: datetime) -> dict[int, datetime]:
        """When /odds was last asked for each fixture since ``since`` (provider id -> instant),
        answered or not: the planner's catch-up asks a missed window once, not every tick.

        Read from market.odds_asks, which records every request. The RAW index is read too, for asks made before
        that table existed - but alone it cannot answer: it keeps one row per distinct answer, so an empty answer
        repeated left the first ask as the "last" one and the fixture was asked again on every tick (5 Oct 2026)."""
        if not provider_fixture_ids:
            return {}
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT fid, max(at) FROM ("
                "  SELECT provider_fixture_id AS fid, asked_at AS at FROM market.odds_asks "
                "   WHERE asked_at >= %(since)s AND provider_fixture_id = ANY(%(ids)s) "
                "  UNION ALL "
                "  SELECT (params->>'fixture')::bigint, fetched_at FROM raw.ingestion_payloads "
                "   WHERE endpoint = '/odds' AND fetched_at >= %(since)s AND params ? 'fixture' "
                "     AND params->>'fixture' = ANY(%(texts)s)) x GROUP BY 1",
                {"since": since, "ids": list(provider_fixture_ids), "texts": [str(i) for i in provider_fixture_ids]},
            )
            return {int(a): b for a, b in cur.fetchall()}

    def record_ask(self, *, provider_fixture_id: int, asked_at: datetime, minutes_to_ko: int,
                   window_minutes: int | None, results: int, quotes: int, payload_hash: str | None,
                   run_id: int | None) -> None:
        """One /odds request of the capture, whatever came back."""
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO market.odds_asks (provider_fixture_id, asked_at, minutes_to_ko, window_minutes, results, "
                "quotes, payload_hash, run_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (provider_fixture_id, asked_at) DO NOTHING",
                (provider_fixture_id, asked_at, minutes_to_ko, window_minutes, results, quotes, payload_hash, run_id),
            )

    def window_observations_since(
        self, *, since: datetime, provider_fixture_ids: Sequence[int] | None = None
    ) -> list[tuple[int, str, int]]:
        """What the planner marks windows done from: every price stored AND every ask made, as
        (provider_fixture_id, source, minutes_to_ko). A window asked in its band is done even when the provider had
        nothing; the next window asks again, because a fixture can be priced later."""
        out = self.observations_since(since=since, provider_fixture_ids=provider_fixture_ids)
        sql = "SELECT DISTINCT provider_fixture_id, minutes_to_ko FROM market.odds_asks WHERE asked_at >= %s"
        params: list[object] = [since]
        if provider_fixture_ids:
            sql += " AND provider_fixture_id = ANY(%s)"
            params.append(list(provider_fixture_ids))
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(sql, params)
            out.extend((int(a), "prematch", int(b)) for a, b in cur.fetchall())
        return out

    def observations_since(
        self, *, since: datetime, provider_fixture_ids: Sequence[int] | None = None
    ) -> list[tuple[int, str, int]]:
        """(provider_fixture_id, source, minutes_to_ko) already on record.

        The planner turns these into window keys. Deriving coverage from what is
        actually stored - rather than from a separate "we ran this" table - means
        the idempotency check can never disagree with reality.
        """
        sql = (
            "SELECT DISTINCT f.provider_fixture_id, o.source, o.minutes_to_ko "
            "FROM market.odds_snapshots o JOIN core.fixtures f ON f.id = o.fixture_id "
            "WHERE o.captured_at >= %s"
        )
        params: list[object] = [since]
        if provider_fixture_ids:
            sql += " AND f.provider_fixture_id = ANY(%s)"
            params.append(list(provider_fixture_ids))
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(sql, params)
            return [(int(a), str(b), int(c)) for a, b, c in cur.fetchall()]
