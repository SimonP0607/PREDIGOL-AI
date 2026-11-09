"""SQL of the odds explorer (plan Cuotas, BE-011): the current-price book (``market.book_current``) and the stored history.

The board is one statement over the rows of ONE market in the window (``book_current_definition_kickoff_idx``): the filters on
the match (competition, country, text) join the fixture, its teams and its competition; the filters on the prices read the
chosen line of each row's JSON (``summary.lines``, the line asked for or ``summary.main``) in the database; Python only orders the
matching keys and builds the page it returns. Every value is a bound parameter.

Never prepared (``prepare=False``): psycopg prepares a statement run five times on one connection, and PostgreSQL may then
plan it once for every value - a plan that cannot drop the filters a request did not use (``%(q)s IS NULL OR ...``). Measured
on 600 matches: 1.7 s with the generic plan, 30 ms planned for its values (BE-011). Planning costs about a millisecond.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.rows import dict_row

from fbi.api.repositories import Conn, Row
from fbi.odds.quote_taxonomy import PROVIDER, SCOPE

FAMILIES_SQL = """
WITH m AS (SELECT * FROM unnest(%(defs)s::int[], %(families)s::text[], %(markets)s::text[], %(periods)s::text[])
                 AS m(definition_id, family, market, period))
SELECT m.family, m.market, m.period, count(DISTINCT b.fixture_id) AS fixtures, coalesce(max(b.books), 0) AS max_books
  FROM market.book_current b
  JOIN m ON m.definition_id = b.definition_id
  JOIN core.fixtures f ON f.id = b.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE b.kickoff_at > %(now)s AND b.kickoff_at <= %(until)s
   AND (%(competition)s::bigint IS NULL OR c.id = %(competition)s::bigint)
   AND (%(country)s::text IS NULL OR c.country = %(country)s::text)
 GROUP BY GROUPING SETS ((m.family), (m.family, m.market), (m.family, m.market, m.period))
"""
"""Fixtures and the most bookmakers per family, market and period of the window: the column ``books`` (no JSON is opened)."""

_BOARD_ROWS = """
WITH cand AS (
    SELECT DISTINCT ON (b.fixture_id)
           b.fixture_id, b.kickoff_at, b.checked_at, b.captured_at, b.provider_update_at, b.summary, b.definition_id,
           f.home_team_id, f.away_team_id, th.name AS home_name, th.logo_url AS home_logo, ta.name AS away_name,
           ta.logo_url AS away_logo, c.id AS competition_id, c.provider_league_id, c.name AS competition_name,
           c.country AS competition_country, c.logo_url AS competition_logo, c.flag_url AS competition_flag
      FROM market.book_current b
      JOIN core.fixtures f ON f.id = b.fixture_id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
      JOIN core.teams th ON th.id = f.home_team_id
      JOIN core.teams ta ON ta.id = f.away_team_id
     WHERE b.definition_id = ANY(%(defs)s::int[])
       AND b.kickoff_at > %(now)s AND b.kickoff_at <= %(until)s
       AND (%(fixtures)s::bigint[] IS NULL OR b.fixture_id = ANY(%(fixtures)s::bigint[]))
       AND (%(competition)s::bigint IS NULL OR c.id = %(competition)s::bigint)
       AND (%(country)s::text IS NULL OR c.country = %(country)s::text)
       AND (%(q)s::text IS NULL OR th.name ILIKE %(q)s::text OR ta.name ILIKE %(q)s::text OR c.name ILIKE %(q)s::text)
     ORDER BY b.fixture_id, array_position(%(defs)s::int[], b.definition_id)
), chosen AS (
    SELECT cand.*, g.grp
      FROM cand
      CROSS JOIN LATERAL (
          SELECT x.grp FROM jsonb_array_elements(cand.summary -> 'lines') AS x(grp)
           WHERE (x.grp -> 'line') = coalesce(%(line)s::jsonb, cand.summary -> 'main', 'null'::jsonb)
           ORDER BY (x.grp ? 'ways')
           LIMIT 1) AS g
), measured AS (
    SELECT chosen.*,
           (SELECT count(DISTINCT k.key) FROM jsonb_array_elements(chosen.grp -> 'sels') AS s(sel),
                   jsonb_object_keys(s.sel -> 'odds') AS k(key)) AS books,
           (SELECT coalesce(bool_or(s.sel ? 'fair'), false) FROM jsonb_array_elements(chosen.grp -> 'sels') AS s(sel))
               AS has_fair,
           (SELECT max((s.sel ->> 'edge')::numeric) FROM jsonb_array_elements(chosen.grp -> 'sels') AS s(sel)
             WHERE s.sel ? 'fair' AND NOT coalesce((s.sel ->> 'outlier')::boolean, false)) AS edge,
           (SELECT coalesce(bool_or((s.sel ->> 'best')::numeric
                                    BETWEEN coalesce(%(odds_min)s::numeric, 0) AND coalesce(%(odds_max)s::numeric, 1000000)),
                            false)
              FROM jsonb_array_elements(chosen.grp -> 'sels') AS s(sel)) AS in_range,
           (SELECT coalesce(bool_or((s.sel -> 'odds') ? %(bookmaker)s::text), false)
              FROM jsonb_array_elements(chosen.grp -> 'sels') AS s(sel)) AS quoted_by
      FROM chosen
)
"""

_BOARD_FILTERS = """
 WHERE (%(min_books)s::int IS NULL OR books >= %(min_books)s::int)
   AND ((%(odds_min)s::numeric IS NULL AND %(odds_max)s::numeric IS NULL) OR in_range)
   AND (NOT %(fair_only)s::boolean OR has_fair)
   AND (%(bookmaker)s::text IS NULL OR quoted_by)
"""

BOARD_KEYS_SQL = _BOARD_ROWS + """
SELECT fixture_id, kickoff_at, checked_at, competition_name, provider_league_id, edge FROM measured
""" + _BOARD_FILTERS
"""The keys of every row of the board (no JSON leaves the database): Python orders them and cuts the page."""

BOARD_PAGE_SQL = _BOARD_ROWS + """
SELECT measured.*,
       (SELECT coalesce(array_agg(DISTINCT (x.grp ->> 'line')::numeric ORDER BY (x.grp ->> 'line')::numeric), '{}')
          FROM jsonb_array_elements(measured.summary -> 'lines') AS x(grp)
         WHERE x.grp ->> 'line' IS NOT NULL) AS lines
  FROM measured
""" + _BOARD_FILTERS
"""The rows of one page (``fixtures`` names them), with the chosen line's selections and every line of the row."""

MARKET_SQL = """
SELECT m.period, count(DISTINCT b.fixture_id) AS fixtures, coalesce(max(b.books), 0) AS max_books
  FROM market.book_current b
  JOIN unnest(%(defs)s::int[], %(periods)s::text[]) AS m(definition_id, period) ON m.definition_id = b.definition_id
  JOIN core.fixtures f ON f.id = b.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE b.kickoff_at > %(now)s AND b.kickoff_at <= %(until)s
   AND (%(competition)s::bigint IS NULL OR c.id = %(competition)s::bigint)
   AND (%(country)s::text IS NULL OR c.country = %(country)s::text)
 GROUP BY ROLLUP (m.period)
"""
"""One market of the board, all its periods: which have prices, the matches (any period) and the most bookmakers."""

FIXTURE_SQL = "SELECT id, kickoff_at, provider_fixture_id FROM core.fixtures WHERE id = %(f)s"

MATCH_ROWS_SQL = """
SELECT d.provider_bet_id AS bet_id, b.kickoff_at, b.captured_at, b.provider_update_at, b.checked_at, b.books, b.summary
  FROM market.book_current b JOIN market.market_definitions d ON d.id = b.definition_id
 WHERE b.fixture_id = %(f)s
 ORDER BY d.provider_bet_id
"""

BOOKMAKERS_SQL = """
SELECT provider_bookmaker_id AS id, name FROM market.bookmakers WHERE provider_bookmaker_id = ANY(%(ids)s::int[])
 ORDER BY provider_bookmaker_id
"""

SNAPSHOT_SERIES_SQL = """
SELECT bk.provider_bookmaker_id AS bookmaker, o.selection, o.line, o.odds_decimal AS odds, o.captured_at
  FROM market.odds_snapshots o JOIN market.bookmakers bk ON bk.id = o.bookmaker_id
 WHERE o.fixture_id = %(f)s AND o.market_key = %(market)s AND o.source = 'prematch' AND o.captured_at < %(ko)s
 ORDER BY o.captured_at, bk.provider_bookmaker_id, o.selection, o.line
"""
"""The capture's series of a classic market (the five of ``odds_snapshots``): its primary key (fixture_id, ...) finds them."""

QUOTE_SERIES_SQL = """
SELECT bk.provider_bookmaker_id AS bookmaker, q.selection, q.line, q.odds_decimal AS odds, q.captured_at
  FROM market.odds_quotes q JOIN market.bookmakers bk ON bk.id = q.bookmaker_id
 WHERE q.fixture_id = %(f)s AND q.definition_id = ANY(%(defs)s::int[]) AND q.captured_at < %(ko)s
   AND q.captured_at >= %(lo)s
 ORDER BY q.captured_at, bk.provider_bookmaker_id, q.selection, q.line
"""
"""The price clock's series of an extracted type: the primary key (fixture_id, bookmaker_id, definition_id, ...) and the monthly
partitions (``captured_at`` bounds) find them."""

EXTRACTED_SQL = """
SELECT provider_bet_id, id FROM market.market_definitions
 WHERE provider = %(provider)s AND scope = %(scope)s AND extract AND provider_bet_id = ANY(%(bets)s::int[])
"""

MAIN_LINE_SQL = """
SELECT b.summary -> 'main' AS main FROM market.book_current b
 WHERE b.fixture_id = %(f)s AND b.definition_id = ANY(%(defs)s::int[])
 ORDER BY array_position(%(defs)s::int[], b.definition_id) LIMIT 1
"""

# ── the owner's health panel ──────────────────────────────────────────────────────────────────────────────────────

HEALTH_FIXTURES_SQL = """
SELECT f.id, f.kickoff_at,
       (SELECT min(b.checked_at) FROM market.book_current b WHERE b.fixture_id = f.id) AS checked_at
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked
   AND f.kickoff_at BETWEEN %(from)s AND %(until)s
   AND f.status_group = 'scheduled'
   AND (lc.odds IS NOT FALSE
        OR EXISTS (SELECT 1 FROM market.odds_mapping_seen m WHERE m.provider_fixture_id = f.provider_fixture_id))
"""
"""The matches the capture follows (the WHERE of ``scripts.capture_odds.UPCOMING_SQL``) in the next 72 h, and the ask behind each
one's book."""

EXTRACTION_LAG_SQL = """
SELECT min(p.fetched_at) AS oldest FROM raw.ingestion_payloads p
  LEFT JOIN market.odds_extractions x ON x.payload_hash = p.hash
 WHERE p.endpoint = '/odds' AND p.http_status = 200 AND p.results_count > 0 AND p.fetched_at >= %(since)s AND x.id IS NULL
   AND NOT EXISTS (SELECT 1 FROM raw.ingestion_runs r WHERE r.id = p.run_id AND r.job_type = %(skipped)s)
"""

BOOK_SIZE_SQL = """
SELECT (SELECT count(*) FROM market.book_current) AS book_rows,
       pg_total_relation_size('market.book_current') AS book_bytes
"""

DEFAULT_ROWS_SQL = """
SELECT coalesce((SELECT count(*) FROM (SELECT 1 FROM market.odds_snapshots_default LIMIT %(cap)s) s), 0)
     + coalesce((SELECT count(*) FROM (SELECT 1 FROM market.odds_quotes_default LIMIT %(cap)s) q), 0) AS n
"""
"""Rows the monthly partitions did not take, capped (a count of a full DEFAULT partition must not cost the panel)."""


def fetch_all(conn: Conn, sql: str, params: dict[str, Any] | None = None) -> list[Row]:
    """Rows as dicts, planned for these values every time (never a prepared statement: see the module docstring)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params, prepare=False)
        return [dict(r) for r in cur.fetchall()]


def fetch_one(conn: Conn, sql: str, params: dict[str, Any] | None = None) -> Row | None:
    rows = fetch_all(conn, sql, params)
    return rows[0] if rows else None


def families(conn: Conn, params: dict[str, Any]) -> list[Row]:
    return fetch_all(conn, FAMILIES_SQL, params)


def board_keys(conn: Conn, params: dict[str, Any]) -> list[Row]:
    return fetch_all(conn, BOARD_KEYS_SQL, params)


def board_page(conn: Conn, params: dict[str, Any]) -> list[Row]:
    return fetch_all(conn, BOARD_PAGE_SQL, params)


def market(conn: Conn, params: dict[str, Any]) -> list[Row]:
    return fetch_all(conn, MARKET_SQL, params)


def fixture(conn: Conn, fixture_id: int) -> Row | None:
    return fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})


def match_rows(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(conn, MATCH_ROWS_SQL, {"f": fixture_id})


def bookmakers(conn: Conn, ids: list[int]) -> list[Row]:
    return fetch_all(conn, BOOKMAKERS_SQL, {"ids": sorted(set(ids))}) if ids else []


def snapshot_series(conn: Conn, fixture_id: int, market_key: str, kickoff_at: datetime) -> list[Row]:
    return fetch_all(conn, SNAPSHOT_SERIES_SQL, {"f": fixture_id, "market": market_key, "ko": kickoff_at})


def quote_series(conn: Conn, fixture_id: int, definitions: list[int], kickoff_at: datetime, since: datetime) -> list[Row]:
    return fetch_all(conn, QUOTE_SERIES_SQL, {"f": fixture_id, "defs": definitions, "ko": kickoff_at, "lo": since})


def extracted(conn: Conn, bet_ids: list[int]) -> dict[int, int]:
    return {int(r["provider_bet_id"]): int(r["id"])
            for r in fetch_all(conn, EXTRACTED_SQL, {"bets": bet_ids, "provider": PROVIDER, "scope": SCOPE})}


def main_line(conn: Conn, fixture_id: int, definitions: list[int]) -> Any:
    row = fetch_one(conn, MAIN_LINE_SQL, {"f": fixture_id, "defs": definitions})
    return row["main"] if row else None


def health_fixtures(conn: Conn, *, since: datetime, until: datetime) -> list[Row]:
    return fetch_all(conn, HEALTH_FIXTURES_SQL, {"from": since, "until": until})


def extraction_oldest(conn: Conn, *, since: datetime, skipped: str) -> datetime | None:
    row = fetch_one(conn, EXTRACTION_LAG_SQL, {"since": since, "skipped": skipped})
    return row["oldest"] if row else None


def book_size(conn: Conn) -> Row:
    row = fetch_one(conn, BOOK_SIZE_SQL)
    return row or {"book_rows": 0, "book_bytes": 0}


def default_partition_rows(conn: Conn, *, cap: int) -> int:
    row = fetch_one(conn, DEFAULT_ROWS_SQL, {"cap": cap})
    return int(row["n"]) if row else 0
