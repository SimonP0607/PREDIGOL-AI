"""Odds snapshots, near-close captures and market consensus."""

from __future__ import annotations

from fbi.api.repositories import Conn, Row, fetch_all


def fixtures_with_odds(conn: Conn, *, limit: int, offset: int) -> list[int]:
    rows = fetch_all(conn, """
        SELECT f.id FROM core.fixtures f
        WHERE EXISTS (SELECT 1 FROM market.odds_snapshots o WHERE o.fixture_id = f.id)
        ORDER BY f.kickoff_at DESC, f.id DESC LIMIT %s OFFSET %s
    """, (limit, offset))
    return [int(r["id"]) for r in rows]


def count_fixtures_with_odds(conn: Conn) -> int:
    rows = fetch_all(conn, "SELECT count(DISTINCT fixture_id) AS n FROM market.odds_snapshots")
    return int(rows[0]["n"]) if rows else 0


def series(conn: Conn, fixture_id: int, market_key: str | None) -> list[Row]:
    return fetch_all(conn, """
        SELECT o.bookmaker_id, b.name AS bookmaker, o.market_key, o.selection, o.line,
               o.captured_at, o.odds_decimal, o.minutes_to_ko, o.source, o.payload_hash
        FROM market.odds_snapshots o JOIN market.bookmakers b ON b.id = o.bookmaker_id
        WHERE o.fixture_id = %s AND (%s::text IS NULL OR o.market_key = %s::text)
        ORDER BY o.market_key, o.selection, o.line, b.name, o.captured_at
    """, (fixture_id, market_key, market_key))


def near_close(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(conn, """
        SELECT b.name AS bookmaker, n.market_key, n.selection, n.line, n.odds_decimal, n.captured_at,
               n.minutes_to_ko, n.source, n.is_validated_close, n.close_validation_method
        FROM market.near_close_snapshots n JOIN market.bookmakers b ON b.id = n.bookmaker_id
        WHERE n.fixture_id = %s ORDER BY n.market_key, n.selection, n.line, b.name
    """, (fixture_id,))


def consensus(conn: Conn, fixture_id: int) -> list[Row]:
    """The newest consensus per market/selection/line/method."""
    return fetch_all(conn, """
        SELECT DISTINCT ON (m.market_key, m.selection, m.line, m.devig_method)
               m.market_key, m.selection, m.line, m.as_of, m.devig_method, m.p_fair, m.n_bookmakers,
               m.overround, m.best_odds, b.name AS best_bookmaker, m.dispersion
        FROM market.market_consensus m JOIN market.bookmakers b ON b.id = m.best_bookmaker_id
        WHERE m.fixture_id = %s
        ORDER BY m.market_key, m.selection, m.line, m.devig_method, m.as_of DESC
    """, (fixture_id,))
