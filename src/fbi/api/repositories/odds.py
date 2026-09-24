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


def historical_prices(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(conn, """
        SELECT source, bookmaker_code, price_kind, market_key, line, selection, odds_decimal
        FROM market.historical_odds WHERE fixture_id = %s
        ORDER BY market_key, line, price_kind, bookmaker_code, selection
    """, (fixture_id,))


def historical_fair(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(conn, """
        SELECT bookmaker_code, price_kind, devig_method, p_home, p_draw, p_away, overround
        FROM analytics.market_baseline WHERE fixture_id = %s AND market_key = '1X2'
        ORDER BY bookmaker_code, price_kind, devig_method
    """, (fixture_id,))


def historical_coverage(conn: Conn) -> Row:
    rows = fetch_all(conn, """
        SELECT count(DISTINCT h.fixture_id) AS fixtures, COALESCE(array_agg(DISTINCT cs.season), '{}') AS seasons,
               max(h.source) AS source
        FROM market.historical_odds h
        JOIN core.fixtures f ON f.id = h.fixture_id
        JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
    """)
    return rows[0]


def bookmaker_margins(conn: Conn) -> list[Row]:
    """Mean and median overround per book, kind and market (1X2 and OU 2.5), and how
    often each named book had the best 1X2 price."""
    return fetch_all(conn, """
        WITH books AS (
            SELECT fixture_id, bookmaker_code, price_kind, market_key, line, sum(1 / odds_decimal) AS overround
            FROM market.historical_odds
            GROUP BY fixture_id, bookmaker_code, price_kind, market_key, line
            HAVING (market_key = '1X2' AND count(*) = 3) OR (market_key = 'OU' AND count(*) = 2)
        ),
        margins AS (
            SELECT bookmaker_code, price_kind, market_key, count(*) AS fixtures,
                   avg(overround) AS mean_overround,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY overround) AS median_overround
            FROM books WHERE bookmaker_code NOT IN ('MAX')
            GROUP BY bookmaker_code, price_kind, market_key
        ),
        named AS (
            SELECT fixture_id, price_kind, selection, bookmaker_code, odds_decimal,
                   max(odds_decimal) OVER (PARTITION BY fixture_id, price_kind, selection) AS top
            FROM market.historical_odds
            WHERE market_key = '1X2' AND bookmaker_code NOT IN ('MAX', 'AVG')
        ),
        best AS (
            SELECT bookmaker_code, price_kind,
                   avg(CASE WHEN odds_decimal = top THEN 1.0 ELSE 0.0 END) AS best_price_share
            FROM named GROUP BY bookmaker_code, price_kind
        )
        SELECT m.bookmaker_code, m.price_kind, m.market_key, m.fixtures,
               round(m.mean_overround::numeric, 5) AS mean_overround,
               round(m.median_overround::numeric, 5) AS median_overround,
               CASE WHEN m.market_key = '1X2' THEN round(b.best_price_share, 4) END AS best_price_share
        FROM margins m LEFT JOIN best b ON b.bookmaker_code = m.bookmaker_code AND b.price_kind = m.price_kind
        ORDER BY m.market_key, m.price_kind, m.mean_overround
    """)


def movement(conn: Conn) -> list[Row]:
    """Pinnacle pre-closing -> closing (Shin), per competition and season, with how
    each price scored against the result."""
    return fetch_all(conn, """
        WITH pairs AS (
            SELECT c.id AS competition_id, c.name AS competition, cs.season, pre.fixture_id,
                   pre.p_home AS ph0, pre.p_draw AS pd0, pre.p_away AS pa0,
                   cl.p_home AS ph1, cl.p_draw AS pd1, cl.p_away AS pa1,
                   CASE WHEN r.goals_home > r.goals_away THEN 0 WHEN r.goals_home = r.goals_away THEN 1 ELSE 2 END AS y
            FROM analytics.market_baseline pre
            JOIN analytics.market_baseline cl ON cl.fixture_id = pre.fixture_id AND cl.bookmaker_code = 'pinnacle'
                 AND cl.price_kind = 'closing' AND cl.devig_method = 'shin' AND cl.market_key = '1X2'
            JOIN core.fixtures f ON f.id = pre.fixture_id AND f.status_group = 'finished'
            JOIN core.fixture_results r ON r.fixture_id = f.id
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE pre.bookmaker_code = 'pinnacle' AND pre.price_kind = 'pre_closing' AND pre.devig_method = 'shin'
              AND pre.market_key = '1X2'
        )
        SELECT competition_id, competition, season, count(*) AS fixtures,
               round(avg(abs(ph1 - ph0)), 5) AS mean_abs_home_shift,
               round(avg(CASE
                   WHEN ph0 >= pd0 AND ph0 >= pa0 THEN (ph1 > ph0)::int
                   WHEN pa0 >= pd0 THEN (pa1 > pa0)::int
                   ELSE (pd1 > pd0)::int END), 4) AS favourite_shortened_share,
               round(avg(-ln(GREATEST(CASE y WHEN 0 THEN ph0 WHEN 1 THEN pd0 ELSE pa0 END, 1e-15))), 5)
                   AS pre_closing_logloss,
               round(avg(-ln(GREATEST(CASE y WHEN 0 THEN ph1 WHEN 1 THEN pd1 ELSE pa1 END, 1e-15))), 5)
                   AS closing_logloss
        FROM pairs GROUP BY competition_id, competition, season ORDER BY competition, season
    """)


def live_counts(conn: Conn) -> Row:
    rows = fetch_all(conn, """
        SELECT (SELECT count(*) FROM market.odds_snapshots) AS snapshots,
               (SELECT count(DISTINCT fixture_id) FROM market.odds_snapshots) AS fixtures,
               (SELECT count(*) FROM market.near_close_snapshots) AS near_close,
               (SELECT count(DISTINCT fixture_id) FROM market.market_consensus) AS consensus_fixtures
    """)
    return rows[0]
