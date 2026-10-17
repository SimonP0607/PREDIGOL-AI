"""SQL for the pre-match profile of a team: its newest finished matches before a kick-off, one row each."""

from __future__ import annotations

FIXTURE = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, cs.competition_id
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE f.id = %(f)s
"""

TEAM_MATCHES = """
WITH m AS (
    SELECT f.id, f.kickoff_at, (f.home_team_id = %(team)s) AS at_home,
           CASE WHEN f.home_team_id = %(team)s THEN r.goals_home ELSE r.goals_away END AS gf,
           CASE WHEN f.home_team_id = %(team)s THEN r.goals_away ELSE r.goals_home END AS ga,
           CASE WHEN f.home_team_id = %(team)s THEN r.ht_goals_home ELSE r.ht_goals_away END AS ht_gf,
           CASE WHEN f.home_team_id = %(team)s THEN r.ht_goals_away ELSE r.ht_goals_home END AS ht_ga
      FROM core.fixtures f
      JOIN core.fixture_results r ON r.fixture_id = f.id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
     WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s)
       AND f.status_group = 'finished' AND f.kickoff_at < %(ko)s
       AND (%(competition)s::bigint IS NULL OR cs.competition_id = %(competition)s)
     ORDER BY f.kickoff_at DESC
     LIMIT %(n)s
), st AS (
    -- one source per match and side, API-Football first (REVIEW P0: never two sources mixed)
    SELECT DISTINCT ON (s.fixture_id, s.team_side)
           s.fixture_id, s.team_side, s.shots, s.shots_on_target, s.corners, s.yellow_cards, s.red_cards, s.fouls,
           s.possession_pct, s.expected_goals
      FROM core.fixture_team_stats s
     WHERE s.fixture_id IN (SELECT id FROM m)
     ORDER BY s.fixture_id, s.team_side, (s.source = 'api-football') DESC, s.fetched_at DESC
), ev AS (
    -- goals in play only: a shoot-out is not "scored first", a missed penalty is not a goal
    SELECT e.fixture_id, e.team_side, e.detail,
           row_number() OVER (PARTITION BY e.fixture_id
                              ORDER BY e.minute, COALESCE(e.extra_minute, 0), e.seq) AS k
      FROM core.fixture_events e
     WHERE e.fixture_id IN (SELECT id FROM m) AND e.event_type = 'Goal'
       AND e.detail <> 'Missed Penalty' AND COALESCE(e.comments, '') <> 'Penalty Shootout'
), pens AS (
    SELECT e.fixture_id, e.team_side,
           count(*) FILTER (WHERE e.detail = 'Penalty') AS scored,
           count(*) FILTER (WHERE e.detail = 'Missed Penalty') AS missed
      FROM core.fixture_events e
     WHERE e.fixture_id IN (SELECT id FROM m) AND e.event_type = 'Goal'
       AND COALESCE(e.comments, '') <> 'Penalty Shootout'
     GROUP BY e.fixture_id, e.team_side
)
SELECT m.id, m.kickoff_at, m.at_home, m.gf, m.ga, m.ht_gf, m.ht_ga,
       o.shots, o.shots_on_target, p.shots AS shots_against, o.corners, p.corners AS corners_against,
       o.yellow_cards, o.red_cards, o.fouls, o.possession_pct, o.expected_goals AS xg_for,
       p.expected_goals AS xg_against,
       (SELECT CASE WHEN g.detail = 'Own Goal' THEN 'unknown'
                    WHEN g.team_side = CASE WHEN m.at_home THEN 'home' ELSE 'away' END THEN 'own'
                    ELSE 'opp' END
          FROM ev g WHERE g.fixture_id = m.id AND g.k = 1) AS first_goal,
       EXISTS (SELECT 1 FROM core.fixture_events e WHERE e.fixture_id = m.id) AS has_events,
       COALESCE(ps.scored, 0) AS pens_scored, COALESCE(ps.missed, 0) AS pens_missed
  FROM m
  LEFT JOIN st o ON o.fixture_id = m.id AND o.team_side = CASE WHEN m.at_home THEN 'home' ELSE 'away' END
  LEFT JOIN st p ON p.fixture_id = m.id AND p.team_side = CASE WHEN m.at_home THEN 'away' ELSE 'home' END
  LEFT JOIN pens ps ON ps.fixture_id = m.id AND ps.team_side = CASE WHEN m.at_home THEN 'home' ELSE 'away' END
 ORDER BY m.kickoff_at DESC
"""

MARKET_BOOKS = """
SELECT o.bookmaker_id, b.name AS bookmaker, o.market_key, o.selection, o.line,
       (array_agg(o.odds_decimal ORDER BY o.captured_at DESC))[1] AS odds, max(o.captured_at) AS captured_at,
       (array_agg(o.odds_decimal ORDER BY o.captured_at))[1] AS opening_odds, min(o.captured_at) AS opening_at,
       count(*) AS captures
  FROM market.odds_snapshots o JOIN market.bookmakers b ON b.id = o.bookmaker_id
 WHERE o.fixture_id = %(f)s AND o.source = 'prematch'
 GROUP BY o.bookmaker_id, b.name, o.market_key, o.selection, o.line
 ORDER BY o.market_key, o.line, o.selection, b.name
"""

CAPTURES = """
SELECT captured_at, source, min(minutes_to_ko) AS minutes_to_ko, count(*) AS quotes,
       count(DISTINCT bookmaker_id) AS bookmakers
  FROM market.odds_snapshots WHERE fixture_id = %(f)s
 GROUP BY captured_at, source ORDER BY captured_at
"""

CAPTURES_BY_MARKET = """
SELECT captured_at, source, market_key, count(*) AS quotes
  FROM market.odds_snapshots WHERE fixture_id = %(f)s
 GROUP BY captured_at, source, market_key
"""
