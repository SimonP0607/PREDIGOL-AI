"""SQL for the product's own endpoints: picks re-priced now, best prices, upcoming."""

from __future__ import annotations

from datetime import datetime

from fbi.api.repositories import Conn, Row, fetch_all, fetch_one

CONSENSUS_METHOD = "shin"
"""The de-vigging the pick engine compares against (fbi.picks.engine.CONSENSUS_METHOD)."""

POPULAR_MARKETS = ("1X2", "OU", "BTTS", "AH", "DC")

_BADGES = """
       f.kickoff_at, f.status_group AS fixture_status, f.home_team_id, f.away_team_id,
       th.name AS home_name, th.logo_url AS home_logo, ta.name AS away_name, ta.logo_url AS away_logo,
       c.id AS competition_id, c.name AS competition_name, c.country AS competition_country,
       c.logo_url AS competition_logo, c.flag_url AS competition_flag
"""

_BADGE_JOINS = """
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
"""

# The newest de-vigged consensus per selection, for the fixtures in the window. Its
# best_odds / best_bookmaker are the best price on offer at that capture.
_LATEST_CONSENSUS = """
lc AS (
    SELECT DISTINCT ON (m.fixture_id, m.market_key, m.selection, m.line)
           m.fixture_id, m.market_key, m.selection, m.line, m.p_fair, m.best_odds, m.best_bookmaker_id,
           m.n_bookmakers, m.as_of
      FROM market.market_consensus m JOIN fx ON fx.id = m.fixture_id
     WHERE m.devig_method = %(method)s AND m.as_of <= %(now)s AND m.as_of >= %(since)s
     ORDER BY m.fixture_id, m.market_key, m.selection, m.line, m.as_of DESC
)
"""

PICK_CANDIDATES = """
WITH fx AS (
    SELECT f.id FROM core.fixtures f WHERE f.kickoff_at >= %(now)s AND f.kickoff_at < %(until)s
), """ + _LATEST_CONSENSUS + """
SELECT p.id AS pick_id, p.fixture_id, """ + _BADGES + """,
       p.market_key, p.selection, p.line, p.status AS pick_status, p.created_at AS pick_created_at,
       v.status AS model_status, m.name AS model, p.p_calibrated AS p_model, p.p_push,
       lc.p_fair, lc.best_odds, b.name AS bookmaker, lc.as_of AS price_at, lc.n_bookmakers
  FROM picks.picks p
  JOIN fx ON fx.id = p.fixture_id
  JOIN core.fixtures f ON f.id = p.fixture_id
""" + _BADGE_JOINS + """
  JOIN models.model_versions v ON v.id = p.model_version_id
  JOIN models.model_registry m ON m.id = v.model_id
  LEFT JOIN lc ON lc.fixture_id = p.fixture_id AND lc.market_key = p.market_key
              AND lc.selection = p.selection AND lc.line = p.line
  LEFT JOIN market.bookmakers b ON b.id = lc.best_bookmaker_id
 WHERE (p.status IN ('qualified', 'published') OR (%(include_shadow)s AND p.status = 'shadow'))
   AND NOT EXISTS (SELECT 1 FROM picks.pick_results pr WHERE pr.pick_id = p.id AND pr.result_status <> 'pending')
 ORDER BY f.kickoff_at, p.id
"""

BEST_PRICES = """
WITH fx AS (
    SELECT f.id FROM core.fixtures f
     WHERE f.status_group = 'scheduled' AND f.kickoff_at >= %(now)s AND f.kickoff_at < %(until)s
), """ + _LATEST_CONSENSUS + """
SELECT lc.fixture_id, lc.market_key, lc.selection, lc.line, lc.p_fair, lc.best_odds, lc.n_bookmakers, lc.as_of,
       b.name AS bookmaker, """ + _BADGES + """
  FROM lc
  JOIN core.fixtures f ON f.id = lc.fixture_id
""" + _BADGE_JOINS + """
  LEFT JOIN market.bookmakers b ON b.id = lc.best_bookmaker_id
 WHERE lc.market_key = ANY(%(markets)s)
 ORDER BY f.kickoff_at, f.id, lc.market_key, lc.line, lc.selection
"""

UPCOMING = """
WITH nxt AS (
    SELECT f.id FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
     WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at >= %(now)s AND f.kickoff_at < %(until)s
     ORDER BY f.kickoff_at, f.id LIMIT 120
)
SELECT f.id AS fixture_id, """ + _BADGES + """, COALESCE(o.bookmakers, 0)::int AS bookmakers
  FROM nxt JOIN core.fixtures f ON f.id = nxt.id
""" + _BADGE_JOINS + """
  LEFT JOIN LATERAL (
      SELECT count(DISTINCT s.bookmaker_id) AS bookmakers FROM market.odds_snapshots s
       WHERE s.fixture_id = f.id AND s.captured_at > %(now)s - interval '2 days'
  ) o ON true
 ORDER BY COALESCE(o.bookmakers, 0) = 0, c.tier NULLS LAST, f.kickoff_at, f.id
 LIMIT %(limit)s
"""

LIVE_FRESHNESS = """
SELECT (SELECT max(observed_at) FROM core.fixture_live_states
         WHERE observed_at > %(now)s - interval '1 day') AS live_at
"""


def pick_candidates(conn: Conn, *, now: datetime, until: datetime, since: datetime,
                    include_shadow: bool) -> list[Row]:
    return fetch_all(conn, PICK_CANDIDATES, {"now": now, "until": until, "since": since,
                                             "include_shadow": include_shadow, "method": CONSENSUS_METHOD})


def best_prices(conn: Conn, *, now: datetime, until: datetime, since: datetime,
                markets: tuple[str, ...] = POPULAR_MARKETS) -> list[Row]:
    return fetch_all(conn, BEST_PRICES, {"now": now, "until": until, "since": since, "markets": list(markets),
                                         "method": CONSENSUS_METHOD})


def upcoming(conn: Conn, *, now: datetime, until: datetime, limit: int) -> list[Row]:
    return fetch_all(conn, UPCOMING, {"now": now, "until": until, "limit": limit})


def live_freshness(conn: Conn, *, now: datetime) -> datetime | None:
    row = fetch_one(conn, LIVE_FRESHNESS, {"now": now})
    return row["live_at"] if row else None
