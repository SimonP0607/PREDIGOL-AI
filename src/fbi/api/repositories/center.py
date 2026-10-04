"""SQL for the Match Center detail, Live, Players and Admin endpoints."""

from __future__ import annotations

FIXTURE = """
SELECT f.id, f.kickoff_at, f.status_group, f.competition_season_id, f.home_team_id, f.away_team_id,
       th.name AS home, ta.name AS away, th.provider_team_id AS home_pid, ta.provider_team_id AS away_pid
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.id = %(f)s
"""

TEAM_STATS = """
SELECT team_side AS side, shots, shots_on_target, shots_off_target, shots_blocked, shots_inside_box,
       shots_outside_box, corners, fouls, offsides, yellow_cards, red_cards, saves, possession_pct, passes,
       passes_accurate, expected_goals, goals_prevented, fetched_at
  FROM core.fixture_team_stats WHERE fixture_id = %(f)s AND team_side IN ('home', 'away')
 ORDER BY team_side DESC
"""

EVENTS = """
SELECT e.seq, e.minute, e.extra_minute, e.team_side AS side, e.player_name AS player, p.id AS player_id,
       e.assist_name AS assist, e.event_type AS type, e.detail, e.comments
  FROM core.fixture_events e
  LEFT JOIN core.players p ON p.provider_player_id = e.provider_player_id
 WHERE e.fixture_id = %(f)s
 ORDER BY e.minute, COALESCE(e.extra_minute, 0), e.seq
"""

LINEUPS = """
SELECT team_side AS side, formation, coach_name AS coach
  FROM core.fixture_lineups WHERE fixture_id = %(f)s AND team_side IN ('home', 'away') ORDER BY team_side DESC
"""

LINEUP_PLAYERS = """
SELECT lp.team_side AS side, lp.provider_player_id, p.id AS player_id, lp.player_name AS name,
       lp.shirt_number AS number, lp.position, lp.grid, lp.is_starter AS starter
  FROM core.fixture_lineup_players lp
  LEFT JOIN core.players p ON p.provider_player_id = lp.provider_player_id
 WHERE lp.fixture_id = %(f)s
 ORDER BY lp.team_side DESC, lp.is_starter DESC, lp.grid NULLS LAST, lp.shirt_number NULLS LAST
"""

PLAYER_STATS = """
SELECT ps.provider_player_id, p.id AS player_id, ps.team_side AS side, ps.player_name AS name, ps.minutes,
       ps.rating, ps.goals, ps.assists, ps.shots_total AS shots, ps.shots_on, ps.passes_total AS passes,
       ps.passes_key AS key_passes, ps.tackles, ps.yellow_cards, ps.red_cards, ps.saves,
       ps.is_substitute AS substitute
  FROM core.fixture_player_stats ps
  LEFT JOIN core.players p ON p.provider_player_id = ps.provider_player_id
 WHERE ps.fixture_id = %(f)s AND ps.team_side IN ('home', 'away')
 ORDER BY ps.team_side DESC, ps.minutes DESC NULLS LAST, ps.rating DESC NULLS LAST
"""

ABSENCES = """
SELECT CASE a.provider_team_id WHEN %(home_pid)s THEN 'home' WHEN %(away_pid)s THEN 'away' END AS side,
       a.player_name AS player, p.id AS player_id, a.absence_type AS type, a.reason
  FROM core.player_absences a
  LEFT JOIN core.players p ON p.provider_player_id = a.provider_player_id
 WHERE a.fixture_id = %(f)s
 ORDER BY 1 DESC NULLS LAST, a.player_name
"""

STANDINGS = """
SELECT DISTINCT ON (s.team_id)
       CASE s.team_id WHEN %(home)s THEN 'home' ELSE 'away' END AS side, t.name AS team, s.rank, s.points,
       s.played, s.wins, s.draws, s.losses, s.goals_for, s.goals_against, s.form, s."group",
       s.snapshot_at, s.snapshot_at <= %(ko)s AS before_kickoff, s.description, s.provider_updated_at,
       k.checked_at,
       (SELECT max(f.kickoff_at) FROM core.fixtures f
         WHERE f.competition_season_id = s.competition_season_id AND f.status_group = 'finished'
           AND f.kickoff_at < %(ko)s) AS last_finished_before
  FROM core.standings s JOIN core.teams t ON t.id = s.team_id
  LEFT JOIN core.context_checks k ON k.competition_season_id = s.competition_season_id AND k.dataset = 'standings'
 WHERE s.competition_season_id = %(cs)s AND s.team_id IN (%(home)s, %(away)s)
 ORDER BY s.team_id, (s.snapshot_at <= %(ko)s) DESC,
          CASE WHEN s.snapshot_at <= %(ko)s THEN s.snapshot_at END DESC NULLS LAST, s.snapshot_at
"""

FORM = """
SELECT f.id AS fixture_id, f.kickoff_at,
       CASE WHEN f.home_team_id = %(team)s THEN ta.name ELSE th.name END AS opponent,
       CASE WHEN f.home_team_id = %(team)s THEN 'H' ELSE 'A' END AS venue,
       CASE WHEN f.home_team_id = %(team)s THEN r.goals_home ELSE r.goals_away END AS goals_for,
       CASE WHEN f.home_team_id = %(team)s THEN r.goals_away ELSE r.goals_home END AS goals_against
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s)
   AND f.status_group = 'finished' AND f.kickoff_at < %(ko)s
   AND r.goals_home IS NOT NULL AND r.goals_away IS NOT NULL
 ORDER BY f.kickoff_at DESC LIMIT 6
"""

H2H = """
SELECT f.id AS fixture_id, f.kickoff_at, c.name AS competition, th.name AS home, ta.name AS away,
       r.goals_home, r.goals_away
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE ((f.home_team_id = %(home)s AND f.away_team_id = %(away)s)
     OR (f.home_team_id = %(away)s AND f.away_team_id = %(home)s))
   AND f.status_group = 'finished' AND f.kickoff_at < %(ko)s
   AND r.goals_home IS NOT NULL AND r.goals_away IS NOT NULL
 ORDER BY f.kickoff_at DESC LIMIT 8
"""

LIVE_STATES = """
SELECT observed_at, 'fixture_feed' AS source, status_short AS status, elapsed, extra, goals_home, goals_away
  FROM core.fixture_live_states WHERE fixture_id = %(f)s
UNION ALL
SELECT captured_at, 'odds_feed', COALESCE(status_long, '?'), elapsed_minute, NULL, score_home, score_away
  FROM (SELECT *, lag((elapsed_minute, score_home, score_away, status_long))
                    OVER (ORDER BY captured_at) AS prev
          FROM market.live_fixture_states WHERE fixture_id = %(f)s) s
 WHERE prev IS DISTINCT FROM (elapsed_minute, score_home, score_away, status_long)
ORDER BY 1 DESC LIMIT 400
"""

LIVE_LATEST_QUOTES = """
SELECT DISTINCT ON (provider_bet_id, selection, line)
       market_key, provider_bet_id, selection, line, odds_decimal AS odds, is_suspended AS suspended,
       is_main_line AS main_line, captured_at, elapsed_minute AS minute
  FROM market.live_odds_snapshots
 WHERE fixture_id = %(f)s AND captured_at > %(since)s
 ORDER BY provider_bet_id, selection, line, captured_at DESC
"""

LIVE_MOVEMENT = """
SELECT market_key, selection, line, captured_at, elapsed_minute AS minute,
       CASE WHEN score_home IS NULL THEN NULL ELSE score_home || '-' || score_away END AS score,
       previous_odds, odds, odds_delta AS delta,
       CASE WHEN became_withdrawn THEN 'withdrawn' WHEN became_offered THEN 'offered'
            WHEN became_suspended THEN 'suspended' WHEN became_available THEN 'available'
            WHEN price_moved THEN 'moved' ELSE 'other' END AS kind
  FROM market.live_market_movement
 WHERE fixture_id = %(f)s AND market_key IS NOT NULL
   AND (price_moved OR became_withdrawn OR became_offered OR became_suspended OR became_available)
 ORDER BY captured_at DESC LIMIT %(limit)s
"""

# ── Live board ─────────────────────────────────────────────────────────────

LIVE_BOARD = """
WITH feed AS (
    SELECT DISTINCT ON (fixture_id) fixture_id, observed_at AS at, status_short AS status, elapsed, extra,
           goals_home, goals_away
      FROM core.fixture_live_states WHERE observed_at > %(at)s - interval '4 hours'
     ORDER BY fixture_id, observed_at DESC
), odds AS (
    SELECT DISTINCT ON (fixture_id) fixture_id, captured_at AS at, status_long, elapsed_minute, score_home,
           score_away, is_finished, markets_offered, values_suspended
      FROM market.live_fixture_states WHERE captured_at > %(at)s - interval '30 minutes'
     ORDER BY fixture_id, captured_at DESC
), live AS (
    SELECT fixture_id FROM feed WHERE status IN ('1H','HT','2H','ET','BT','P','LIVE','INT','SUSP')
    UNION
    SELECT fixture_id FROM odds WHERE NOT COALESCE(is_finished, false) AND at > %(at)s - interval '5 minutes'
)
SELECT f.id AS fixture_id, f.kickoff_at, c.name AS competition, c.country,
       c.id AS competition_id, c.logo_url AS competition_logo, c.flag_url AS competition_flag,
       th.id AS home_id, th.name AS home_name, th.logo_url AS home_logo,
       ta.id AS away_id, ta.name AS away_name, ta.logo_url AS away_logo,
       EXISTS (SELECT 1 FROM core.fixture_lineups l WHERE l.fixture_id = f.id) AS has_lineups,
       EXISTS (SELECT 1 FROM core.fixture_player_stats ps WHERE ps.fixture_id = f.id) AS has_player_stats,
       feed.at AS feed_at, feed.status AS feed_status, feed.elapsed AS feed_elapsed, feed.extra AS feed_extra,
       feed.goals_home AS feed_gh, feed.goals_away AS feed_ga,
       odds.at AS odds_at, odds.status_long AS odds_status, odds.elapsed_minute AS odds_elapsed,
       odds.score_home AS odds_gh, odds.score_away AS odds_ga, odds.markets_offered, odds.values_suspended
  FROM live
  JOIN core.fixtures f ON f.id = live.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN feed ON feed.fixture_id = f.id
  LEFT JOIN odds ON odds.fixture_id = f.id
 ORDER BY c.tier NULLS LAST, c.name, f.kickoff_at, f.id
"""

LIVE_BOARD_EVENTS = """
SELECT e.fixture_id, e.seq, e.minute, e.extra_minute, e.team_side AS side, e.player_name AS player,
       p.id AS player_id, e.assist_name AS assist, e.event_type AS type, e.detail, e.comments
  FROM core.fixture_events e
  LEFT JOIN core.players p ON p.provider_player_id = e.provider_player_id
 WHERE e.fixture_id = ANY(%(ids)s) AND e.event_type IN ('Goal', 'Card', 'Var')
 ORDER BY e.fixture_id, e.minute, COALESCE(e.extra_minute, 0), e.seq
"""

LIVE_BOARD_STATS = """
SELECT fixture_id, team_side AS side, shots, shots_on_target, shots_off_target, shots_blocked, shots_inside_box,
       shots_outside_box, corners, fouls, offsides, yellow_cards, red_cards, saves, possession_pct, passes,
       passes_accurate, expected_goals, goals_prevented, fetched_at
  FROM core.fixture_team_stats WHERE fixture_id = ANY(%(ids)s) AND team_side IN ('home', 'away')
 ORDER BY fixture_id, team_side DESC
"""

LIVE_BOARD_ODDS = """
SELECT DISTINCT ON (fixture_id, provider_bet_id, selection, line)
       fixture_id, market_key, provider_bet_id, selection, line, odds_decimal AS odds,
       is_suspended AS suspended, is_main_line AS main_line, captured_at, elapsed_minute AS minute
  FROM market.live_odds_snapshots
 WHERE fixture_id = ANY(%(ids)s) AND captured_at > %(at)s - interval '30 minutes'
   AND market_key IN ('1X2', 'OU') AND COALESCE(is_main_line, market_key = '1X2')
 ORDER BY fixture_id, provider_bet_id, selection, line, captured_at DESC
"""

LIVE_FEEDS = """
SELECT (SELECT max(observed_at) FROM core.fixture_live_states) AS fixture_feed_at,
       (SELECT max(captured_at) FROM market.live_fixture_states) AS odds_feed_at,
       (SELECT count(DISTINCT fixture_id) FROM market.live_fixture_states
         WHERE captured_at > %(at)s - interval '5 minutes') AS priced
"""

# ── Players ────────────────────────────────────────────────────────────────

# A player's figures and his three teams (data truth audit V2, 4 Oct 2026):
# * an appearance is a match he PLAYED (minutes > 0): the provider lists unused substitutes in
#   /fixtures/players with no minutes, and counting those rows called a bench an appearance;
# * club = the club whose newest squad (/players/squads) lists him, else the club of his last
#   appearance; national_team likewise among national sides; last_team = his last appearance,
#   whoever it was for. The old single "team" was the last appearance - Spain, Norway, England
#   after an international window.
PLAYER_AGG = """
SELECT count(*) FILTER (WHERE ps.minutes > 0)::int AS apps, sum(ps.minutes)::int AS minutes,
       sum(ps.goals)::int AS goals, sum(ps.assists)::int AS assists,
       round(avg(ps.rating) FILTER (WHERE ps.minutes > 0), 2) AS avg_rating,
       max(f.kickoff_at) FILTER (WHERE ps.minutes > 0) AS last_played,
       (array_agg(t.id ORDER BY f.kickoff_at DESC) FILTER (WHERE ps.minutes > 0))[1] AS last_team_id,
       (array_agg(t.id ORDER BY f.kickoff_at DESC) FILTER (WHERE ps.minutes > 0 AND NOT COALESCE(t.is_national, false)))[1]
           AS last_club_id,
       (array_agg(t.id ORDER BY f.kickoff_at DESC) FILTER (WHERE ps.minutes > 0 AND COALESCE(t.is_national, false)))[1]
           AS last_national_id
  FROM core.fixture_player_stats ps JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.teams t ON t.id = CASE ps.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
 WHERE ps.provider_player_id = p.provider_player_id AND f.kickoff_at > %(since)s
"""

SQUAD_OF = """
SELECT m.team_id FROM core.squad_members m JOIN core.teams st ON st.id = m.team_id
 WHERE m.provider_player_id = p.provider_player_id AND COALESCE(st.is_national, false) = {national}
   AND m.last_seen_at = st.squad_checked_at
 ORDER BY m.last_seen_at DESC LIMIT 1
"""

TEAMS_OF_PLAYER = """
  LEFT JOIN LATERAL (""" + SQUAD_OF.format(national="false") + """) sq ON true
  LEFT JOIN LATERAL (""" + SQUAD_OF.format(national="true") + """) nsq ON true
  LEFT JOIN core.teams club ON club.id = COALESCE(sq.team_id, a.last_club_id)
  LEFT JOIN core.teams nat ON nat.id = COALESCE(nsq.team_id, a.last_national_id)
  LEFT JOIN core.teams last ON last.id = a.last_team_id
"""

PLAYER_TEAMS_COLUMNS = """
       club.id AS team_id, club.name AS team,
       CASE WHEN sq.team_id IS NOT NULL THEN 'squad' WHEN a.last_club_id IS NOT NULL THEN 'appearances' END
           AS club_source,
       nat.id AS national_team_id, nat.name AS national_team, last.id AS last_team_id, last.name AS last_team"""

PLAYERS_SEARCH = """
SELECT p.id, p.provider_player_id, p.name, p.nationality, p.position, p.birth_date,""" + PLAYER_TEAMS_COLUMNS + """,
       COALESCE(a.apps, 0) AS apps, a.minutes, a.goals, a.assists, a.avg_rating, a.last_played
  FROM core.players p
  LEFT JOIN LATERAL (""" + PLAYER_AGG + """) a ON true""" + TEAMS_OF_PLAYER + """
 WHERE p.name ILIKE %(q)s OR p.lastname ILIKE %(q)s
 ORDER BY COALESCE(a.apps, 0) DESC, p.name
 LIMIT %(limit)s OFFSET %(offset)s
"""

PLAYERS_OF_TEAM = """
-- Figures FOR THIS TEAM only: a player's appearances elsewhere (an earlier club,
-- the national side) are not this squad's. An appearance is a match played (minutes > 0).
WITH squad AS (
    SELECT ps.provider_player_id, count(*) FILTER (WHERE ps.minutes > 0)::int AS apps,
           sum(ps.minutes)::int AS minutes, sum(ps.goals)::int AS goals, sum(ps.assists)::int AS assists,
           round(avg(ps.rating) FILTER (WHERE ps.minutes > 0), 2) AS avg_rating,
           max(f.kickoff_at) FILTER (WHERE ps.minutes > 0) AS last_played
      FROM core.fixture_player_stats ps JOIN core.fixtures f ON f.id = ps.fixture_id
     WHERE f.kickoff_at > %(since)s
       AND ((ps.team_side = 'home' AND f.home_team_id = %(team)s) OR (ps.team_side = 'away' AND f.away_team_id = %(team)s))
     GROUP BY ps.provider_player_id
)
SELECT p.id, p.provider_player_id, p.name, p.nationality, p.position, p.birth_date,
       %(team)s::bigint AS team_id, t.name AS team, NULL::text AS club_source, NULL::bigint AS national_team_id,
       NULL::text AS national_team, NULL::bigint AS last_team_id, NULL::text AS last_team,
       squad.apps, squad.minutes, squad.goals, squad.assists, squad.avg_rating, squad.last_played
  FROM squad JOIN core.players p ON p.provider_player_id = squad.provider_player_id
  LEFT JOIN core.teams t ON t.id = %(team)s::bigint
 WHERE squad.apps > 0
 ORDER BY squad.minutes DESC NULLS LAST, p.name
 LIMIT %(limit)s OFFSET %(offset)s
"""

PLAYERS_ACTIVE = """
WITH recent AS (
    SELECT ps.provider_player_id, count(*)::int AS apps, sum(ps.minutes)::int AS minutes,
           sum(ps.goals)::int AS goals, sum(ps.assists)::int AS assists, round(avg(ps.rating), 2) AS avg_rating,
           max(f.kickoff_at) AS last_played,
           (array_agg(t.id ORDER BY f.kickoff_at DESC))[1] AS last_team_id,
           (array_agg(t.id ORDER BY f.kickoff_at DESC) FILTER (WHERE NOT COALESCE(t.is_national, false)))[1] AS last_club_id,
           (array_agg(t.id ORDER BY f.kickoff_at DESC) FILTER (WHERE COALESCE(t.is_national, false)))[1] AS last_national_id
      FROM core.fixtures f JOIN core.fixture_player_stats ps ON ps.fixture_id = f.id
      JOIN core.teams t ON t.id = CASE ps.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
     WHERE f.kickoff_at > %(recent)s AND f.kickoff_at <= %(at)s AND ps.minutes > 0
     GROUP BY ps.provider_player_id
)
SELECT p.id, p.provider_player_id, p.name, p.nationality, p.position, p.birth_date,""" + PLAYER_TEAMS_COLUMNS + """,
       a.apps, a.minutes, a.goals, a.assists, a.avg_rating, a.last_played
  FROM recent a JOIN core.players p ON p.provider_player_id = a.provider_player_id""" + TEAMS_OF_PLAYER + """
 ORDER BY a.goals DESC NULLS LAST, a.avg_rating DESC NULLS LAST, p.name
 LIMIT %(limit)s OFFSET %(offset)s
"""

PLAYER = """
SELECT p.id, p.provider_player_id, p.name, p.nationality, p.position, p.birth_date, p.firstname, p.lastname,
       p.height_cm, p.weight_kg,""" + PLAYER_TEAMS_COLUMNS + """,
       COALESCE(a.apps, 0) AS apps, a.minutes, a.goals, a.assists, a.avg_rating, a.last_played
  FROM core.players p
  LEFT JOIN LATERAL (""" + PLAYER_AGG + """) a ON true""" + TEAMS_OF_PLAYER + """
 WHERE p.id = %(id)s
"""

PLAYER_SEASONS = """
-- One row per competition, season AND team - the provider's own scope (a transfer gives two).
SELECT c.name AS competition, cs.season, t.name AS team, COALESCE(t.is_national, false) AS national,
       count(*) FILTER (WHERE ps.minutes > 0)::int AS apps,
       count(*) FILTER (WHERE ps.minutes > 0 AND NOT COALESCE(ps.is_substitute, false))::int AS starts,
       sum(ps.minutes)::int AS minutes, sum(ps.goals)::int AS goals, sum(ps.assists)::int AS assists,
       sum(ps.yellow_cards)::int AS yellow_cards, sum(ps.red_cards)::int AS red_cards,
       round(avg(ps.rating) FILTER (WHERE ps.minutes > 0), 2) AS avg_rating
  FROM core.fixture_player_stats ps
  JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id = CASE ps.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
 WHERE ps.provider_player_id = %(pid)s
 GROUP BY c.name, cs.season, t.name, COALESCE(t.is_national, false)
HAVING count(*) FILTER (WHERE ps.minutes > 0) > 0
 ORDER BY cs.season DESC, count(*) FILTER (WHERE ps.minutes > 0) DESC
"""

PLAYER_MATCHES = """
SELECT f.id AS fixture_id, f.kickoff_at, c.name AS competition,
       CASE ps.team_side WHEN 'home' THEN th.name ELSE ta.name END AS team,
       CASE ps.team_side WHEN 'home' THEN ta.name ELSE th.name END AS opponent,
       ps.minutes, ps.rating, ps.goals, ps.assists, ps.is_substitute AS substitute
  FROM core.fixture_player_stats ps
  JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE ps.provider_player_id = %(pid)s
 ORDER BY f.kickoff_at DESC LIMIT 25
"""

PLAYER_ABSENCES = """
SELECT a.fixture_id, f.kickoff_at, a.absence_type AS type, a.reason
  FROM core.player_absences a LEFT JOIN core.fixtures f ON f.id = a.fixture_id
 WHERE a.provider_player_id = %(pid)s
 ORDER BY f.kickoff_at DESC NULLS LAST LIMIT 25
"""

# ── Admin ──────────────────────────────────────────────────────────────────

ADMIN_FACTS = """
SELECT (SELECT version_num FROM public.alembic_version LIMIT 1) AS schema_revision,
       pg_database_size(current_database()) AS database_bytes
"""

BACKFILL_PROGRESS = """
SELECT kind, count(*)::int AS total,
       count(*) FILTER (WHERE status = 'done')::int AS done,
       count(*) FILTER (WHERE status = 'pending')::int AS pending,
       count(*) FILTER (WHERE status = 'running')::int AS running,
       count(*) FILTER (WHERE status = 'failed')::int AS failed,
       count(*) FILTER (WHERE status NOT IN ('done', 'pending', 'running', 'failed'))::int AS other,
       max(completed_at) AS last_completed_at
  FROM raw.backfill_tasks GROUP BY kind ORDER BY kind
"""

CAPTURES = """
SELECT
  (SELECT count(*) FROM market.odds_snapshots WHERE captured_at > %(at)s - interval '1 hour') AS prematch_1h,
  (SELECT count(*) FROM market.odds_snapshots WHERE captured_at > %(at)s - interval '24 hours') AS prematch_24h,
  (SELECT max(captured_at) FROM market.odds_snapshots WHERE captured_at > %(at)s - interval '7 days') AS prematch_last,
  (SELECT count(*) FROM market.live_odds_snapshots WHERE captured_at > %(at)s - interval '1 hour') AS live_1h,
  (SELECT count(*) FROM market.live_odds_snapshots WHERE captured_at > %(at)s - interval '24 hours') AS live_24h,
  (SELECT max(captured_at) FROM market.live_odds_snapshots WHERE captured_at > %(at)s - interval '7 days') AS live_last,
  (SELECT count(DISTINCT fixture_id) FROM market.live_fixture_states
    WHERE captured_at > %(at)s - interval '5 minutes') AS live_priced_now,
  (SELECT count(*) FROM core.fixture_live_states WHERE observed_at > %(at)s - interval '24 hours') AS match_states_24h,
  (SELECT max(observed_at) FROM core.fixture_live_states) AS match_states_last,
  (SELECT count(*) FROM core.fixtures WHERE kickoff_at BETWEEN %(at)s AND %(at)s + interval '7 days') AS upcoming_7d,
  (SELECT count(*) FROM core.fixtures WHERE status_group = 'finished') AS finished_total,
  (SELECT count(*) FROM core.fixtures WHERE status_group = 'scheduled' AND kickoff_at < %(at)s - interval '3 hours'
     AND kickoff_at > %(at)s - interval '7 days') AS awaiting_result,
  (SELECT count(*) FROM models.predictions WHERE created_at > %(at)s - interval '24 hours') AS predictions_24h,
  (SELECT count(*) FROM picks.pick_candidates WHERE evaluated_at > %(at)s - interval '24 hours') AS candidates_24h
"""

RECENT_ERRORS = """
SELECT id AS run_id, job_type, status, started_at, last_error AS error
  FROM raw.ingestion_runs
 WHERE started_at > %(at)s - interval '72 hours' AND status IN ('failed', 'partial', 'aborted', 'interrupted')
 ORDER BY started_at DESC LIMIT 30
"""

QUALITY_COUNTS = """
SELECT severity, count(*)::int AS n, max(last_seen_at) AS at
  FROM audit.data_quality_issues WHERE status = 'open' GROUP BY severity
"""


COMPETITION_TABLE = """
WITH cs AS (
    SELECT cs.id, cs.season FROM core.competition_seasons cs
     WHERE cs.competition_id = %(c)s AND (%(season)s::int IS NULL OR cs.season = %(season)s::int)
       AND EXISTS (SELECT 1 FROM core.standings s WHERE s.competition_season_id = cs.id)
     ORDER BY cs.season DESC LIMIT 1
), snap AS (
    SELECT s.competition_season_id, max(s.snapshot_at) AS at
      FROM core.standings s JOIN cs ON cs.id = s.competition_season_id GROUP BY 1
)
SELECT cs.season, s.snapshot_at, s.rank, s.team_id, t.name AS team, s.played, s.wins, s.draws, s.losses,
       s.goals_for, s.goals_against, s.points, s.form, s."group"
  FROM core.standings s
  JOIN snap ON snap.competition_season_id = s.competition_season_id AND snap.at = s.snapshot_at
  JOIN cs ON cs.id = s.competition_season_id
  JOIN core.teams t ON t.id = s.team_id
 ORDER BY s."group" NULLS FIRST, s.rank
"""
