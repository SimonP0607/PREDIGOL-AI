"""SQL for the Match Center detail, Live, Players and Admin endpoints."""

from __future__ import annotations

FIXTURE = """
SELECT f.id, f.kickoff_at, f.status_group, f.round, f.competition_season_id, f.home_team_id, f.away_team_id,
       th.name AS home, ta.name AS away, th.provider_team_id AS home_pid, ta.provider_team_id AS away_pid
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.id = %(f)s
"""

TEAM_STATS = """
WITH src AS (
    SELECT source FROM core.fixture_team_stats WHERE fixture_id = %(f)s AND team_side IN ('home', 'away')
     GROUP BY source ORDER BY (source = 'api-football') DESC, count(*) DESC, max(fetched_at) DESC LIMIT 1
)
SELECT team_side AS side, shots, shots_on_target, shots_off_target, shots_blocked, shots_inside_box,
       shots_outside_box, corners, fouls, offsides, yellow_cards, red_cards, saves, possession_pct, passes,
       passes_accurate, expected_goals, goals_prevented, fetched_at, s.source
  FROM core.fixture_team_stats s JOIN src USING (source)
 WHERE s.fixture_id = %(f)s AND s.team_side IN ('home', 'away')
 ORDER BY team_side DESC
"""
"""One source per match: API-Football first (it has possession, xG and passes), football-data.co.uk only when it is
all there is. Both are stored for 5.329 matches (11 Oct 2026); before this the page got four rows for two teams and
could show the second source's empty possession and xG."""

EVENTS = """
SELECT e.seq, e.minute, e.extra_minute, e.team_side AS side, e.player_name AS player, p.id AS player_id,
       e.assist_name AS assist, e.event_type AS type, e.detail, e.comments
  FROM core.fixture_events e
  LEFT JOIN core.players p ON p.provider_player_id = e.provider_player_id
 WHERE e.fixture_id = %(f)s
 ORDER BY e.minute, COALESCE(e.extra_minute, 0), e.seq
"""

LINEUPS = """
SELECT l.team_side AS side, l.formation, l.coach_name AS coach, l.provider_coach_id AS coach_provider_id,
       cp.photo_url AS coach_photo_url
  FROM core.fixture_lineups l
  LEFT JOIN core.coach_profiles_latest cp ON cp.provider_coach_id = l.provider_coach_id AND l.provider_coach_id > 0
 WHERE l.fixture_id = %(f)s AND l.team_side IN ('home', 'away') ORDER BY l.team_side DESC
"""

LINEUP_PLAYERS = """
SELECT lp.team_side AS side, lp.provider_player_id, p.id AS player_id, lp.player_name AS name,
       lp.shirt_number AS number, lp.position, lp.grid, lp.is_starter AS starter, p.photo_url
  FROM core.fixture_lineup_players lp
  LEFT JOIN core.players p ON p.provider_player_id = lp.provider_player_id
 WHERE lp.fixture_id = %(f)s
 ORDER BY lp.team_side DESC, lp.is_starter DESC, lp.grid NULLS LAST, lp.shirt_number NULLS LAST
"""

RATING_NOTE = """The provider sends a rating of 0 for a player it did not rate (4 Oct 2026: 13,788 match rows, 999 of
them with minutes - UEFA Champions League 2026 qualifiers among them) and averages those zeros into its season
rating (Reinaldo, 2026: 3.98 = (0 + 0 + 7.3 + 6.3 + 6.3) / 5). Rows keep the value as sent; every product
read shows no rating for a 0 (NULLIF) and averages only real ratings."""

PLAYER_STATS = """
SELECT ps.provider_player_id, p.id AS player_id, ps.team_side AS side, ps.player_name AS name, ps.minutes,
       NULLIF(ps.rating, 0) AS rating, ps.goals, ps.assists, ps.shots_total AS shots, ps.shots_on,
       ps.passes_total AS passes,
       ps.passes_key AS key_passes, ps.tackles, ps.yellow_cards, ps.red_cards, ps.saves,
       ps.is_substitute AS substitute, p.photo_url, x.position_played, x.offsides, x.dribbled_past,
       x.penalties_won, x.penalties_committed, x.penalties_saved
  FROM core.fixture_player_stats ps
  LEFT JOIN core.players p ON p.provider_player_id = ps.provider_player_id
  LEFT JOIN core.fixture_player_extras_latest x
         ON x.fixture_id = ps.fixture_id AND x.provider_player_id = ps.provider_player_id
 WHERE ps.fixture_id = %(f)s AND ps.team_side IN ('home', 'away')
 ORDER BY ps.team_side DESC, ps.minutes DESC NULLS LAST, NULLIF(ps.rating, 0) DESC NULLS LAST
"""

ABSENCES = """
WITH latest AS (
    SELECT k.payload_hash FROM core.context_checks k JOIN core.fixtures f ON f.competition_season_id = k.competition_season_id
     WHERE f.id = %(f)s AND k.dataset = 'injuries'
)
SELECT CASE a.provider_team_id WHEN %(home_pid)s THEN 'home' WHEN %(away_pid)s THEN 'away' END AS side,
       a.player_name AS player, p.id AS player_id, a.absence_type AS type, a.reason, p.photo_url,
       p.position, a.fetched_at
  FROM core.player_absences a
  LEFT JOIN core.players p ON p.provider_player_id = a.provider_player_id
 WHERE a.fixture_id = %(f)s
   AND (NOT %(current_only)s
        OR (EXISTS (SELECT 1 FROM latest) AND a.payload_hash = (SELECT payload_hash FROM latest))
        OR (NOT EXISTS (SELECT 1 FROM latest)
            AND a.fetched_at = (SELECT max(b.fetched_at) FROM core.player_absences b WHERE b.fixture_id = %(f)s)))
 ORDER BY 1 DESC NULLS LAST, a.player_name
"""
"""The absences of a match. Before it is over, only the provider's CURRENT list: a season's injuries come in one
/injuries answer (fbi.ingestion.context_refresh) and a player the newest answer no longer names has recovered or
was never out - 44 such rows were shown on upcoming matches on 11 Oct 2026. After the match, every row reported
for it, as the record of who was missing."""

FIXTURE_FACTS = """
SELECT referee, referee_country, home_winner, away_winner, first_half_at, second_half_at, observed_at, payload_hash,
       normalizer_version
  FROM core.fixture_facts_latest WHERE fixture_id = %(f)s
"""

STANDING_ROWS = """
SELECT s.team_id, s.group_key, t.name AS team, t.logo_url AS team_logo, s.rank, s.points, s.played, s.wins,
       s.draws, s.losses, s.goals_for, s.goals_against, s.form, s."group", s.description
  FROM core.standings s JOIN core.teams t ON t.id = s.team_id
 WHERE s.competition_season_id = %(cs)s AND s.snapshot_at = %(at)s AND s.team_id = ANY(%(teams)s)
"""
"""Both teams' rows of one snapshot; ``fbi.competitions.tables.match_tables`` says which table each
row must come from (until 4 Oct 2026 this query took each team's newest row across ALL the season's
tables with DISTINCT ON (team): a Clausura row for one side and an Apertura row for the other)."""

TABLE_CHECKED = """
SELECT checked_at FROM core.context_checks WHERE competition_season_id = %(cs)s AND dataset = 'standings'
"""

SEASON_HAS_TABLE = "SELECT EXISTS (SELECT 1 FROM core.standings WHERE competition_season_id = %(cs)s) AS has_table"

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
  FROM market.live_fixture_current WHERE fixture_id = %(f)s
ORDER BY 1 DESC LIMIT 400
"""
"""The match as it was played comes from the fixture feed, kept permanently (core.fixture_live_states). The odds
feed adds at most ONE row - its state now, while the match is in the live book: since revision 0068 the in-play
book keeps no history."""

LIVE_LATEST_QUOTES = """
SELECT o.market_key, o.provider_bet_id, o.selection, o.line, o.odds_decimal AS odds, o.is_suspended AS suspended,
       o.is_main_line AS main_line, o.changed_at AS captured_at, o.changed_minute AS minute
  FROM market.live_odds_current o
 WHERE o.fixture_id = %(f)s AND o.changed_at > %(since)s
"""
"""The in-play prices being quoted NOW (market.live_odds_current), each with the instant and minute its price was
set. Empty once the match has left the live book: in-play prices are shown while the match is played and not kept
afterwards (revision 0068)."""

LIVE_MOVEMENT = """
SELECT market_key, selection, line, changed_at AS captured_at, changed_minute AS minute,
       CASE WHEN changed_score_home IS NULL THEN NULL ELSE changed_score_home || '-' || changed_score_away END AS score,
       previous_odds, odds_decimal AS odds,
       CASE WHEN change_kind = 'moved' THEN odds_decimal - previous_odds END AS delta,
       change_kind AS kind
  FROM market.live_odds_current
 WHERE fixture_id = %(f)s AND market_key IS NOT NULL AND change_kind <> 'offered'
 ORDER BY changed_at DESC LIMIT %(limit)s
"""
"""The LAST change of each of our markets' selections still in the book - which price moved, from what, at which
minute and score - newest first. One row per selection at most: the in-play book keeps the price a key replaced,
not a series (revision 0068)."""

# ── Live board ─────────────────────────────────────────────────────────────

LIVE_BOARD = """
WITH feed AS (
    SELECT DISTINCT ON (fixture_id) fixture_id, observed_at AS at, status_short AS status, elapsed, extra,
           goals_home, goals_away
      FROM core.fixture_live_states WHERE observed_at > %(at)s - interval '4 hours'
     ORDER BY fixture_id, observed_at DESC
), odds AS (
    SELECT fixture_id, captured_at AS at, status_long, elapsed_minute, score_home,
           score_away, is_finished, markets_offered, values_suspended
      FROM market.live_fixture_current WHERE captured_at > %(at)s - interval '30 minutes'
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
SELECT DISTINCT ON (fixture_id, team_side)
       fixture_id, team_side AS side, shots, shots_on_target, shots_off_target, shots_blocked, shots_inside_box,
       shots_outside_box, corners, fouls, offsides, yellow_cards, red_cards, saves, possession_pct, passes,
       passes_accurate, expected_goals, goals_prevented, fetched_at, source
  FROM core.fixture_team_stats WHERE fixture_id = ANY(%(ids)s) AND team_side IN ('home', 'away')
 ORDER BY fixture_id, team_side DESC, (source = 'api-football') DESC, fetched_at DESC
"""

LIVE_BOARD_ODDS = """
SELECT o.fixture_id, o.market_key, o.provider_bet_id, o.selection, o.line, o.odds_decimal AS odds,
       o.is_suspended AS suspended, o.is_main_line AS main_line, o.changed_at AS captured_at,
       o.changed_minute AS minute
  FROM market.live_odds_current o
  JOIN market.live_fixture_current s ON s.fixture_id = o.fixture_id
 WHERE o.fixture_id = ANY(%(ids)s) AND s.captured_at > %(at)s - interval '30 minutes'
   AND o.market_key IN ('1X2', 'OU') AND COALESCE(o.is_main_line, o.market_key = '1X2')
 ORDER BY o.fixture_id, o.provider_bet_id, o.selection, o.line
"""

LIVE_FEEDS = """
SELECT (SELECT max(observed_at) FROM core.fixture_live_states) AS fixture_feed_at,
       (SELECT max(captured_at) FROM market.live_fixture_current) AS odds_feed_at,
       (SELECT count(*) FROM market.live_fixture_current
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
       round(avg(NULLIF(ps.rating, 0)) FILTER (WHERE ps.minutes > 0), 2) AS avg_rating,
       max(f.kickoff_at) FILTER (WHERE ps.minutes > 0) AS last_played,
       (array_agg(t.id ORDER BY f.kickoff_at DESC) FILTER (WHERE ps.minutes > 0))[1] AS last_team_id,
       (array_agg(t.id ORDER BY f.kickoff_at DESC)
            FILTER (WHERE ps.minutes > 0 AND NOT COALESCE(k.is_national, t.is_national, false)))[1] AS last_club_id,
       (array_agg(t.id ORDER BY f.kickoff_at DESC)
            FILTER (WHERE ps.minutes > 0 AND COALESCE(k.is_national, t.is_national, false)))[1] AS last_national_id
  FROM core.fixture_player_stats ps JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.teams t ON t.id = CASE ps.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
  LEFT JOIN core.team_kind k ON k.team_id = t.id
 WHERE ps.provider_player_id = p.provider_player_id AND f.kickoff_at > %(since)s
"""

SQUAD_OF = """
SELECT m.team_id FROM core.squad_members m JOIN core.teams st ON st.id = m.team_id
  LEFT JOIN core.team_kind sk ON sk.team_id = st.id
 WHERE m.provider_player_id = p.provider_player_id AND COALESCE(sk.is_national, st.is_national, false) = {national}
   AND m.last_seen_at = st.squad_checked_at
 ORDER BY m.last_seen_at DESC LIMIT 1
"""

TEAMS_OF_PLAYER = """
  LEFT JOIN LATERAL (""" + SQUAD_OF.format(national="false") + """) sq ON true
  LEFT JOIN LATERAL (""" + SQUAD_OF.format(national="true") + """) nsq ON true
  LEFT JOIN core.teams club ON club.id = COALESCE(sq.team_id, a.last_club_id)
  LEFT JOIN core.teams nat ON nat.id = COALESCE(nsq.team_id, a.last_national_id)
  LEFT JOIN core.teams last ON last.id = a.last_team_id
  LEFT JOIN core.team_kind ck ON ck.team_id = club.id
  LEFT JOIN core.team_kind nk ON nk.team_id = nat.id
"""
"""National or club is PrediGol's classification (core.team_kind: from the competitions a side plays), the
provider's flag where there is none yet - the provider flags some youth national sides as clubs."""

PLAYER_TEAMS_COLUMNS = """
       club.id AS team_id, club.name AS team, club.logo_url AS team_logo, nat.logo_url AS national_team_logo,
       CASE WHEN sq.team_id IS NOT NULL THEN 'squad' WHEN a.last_club_id IS NOT NULL THEN 'appearances' END
           AS club_source,
       nat.id AS national_team_id, nat.name AS national_team, last.id AS last_team_id, last.name AS last_team"""

PLAYERS_SEARCH = """
SELECT p.id, p.provider_player_id, p.name, p.nationality, p.position, p.birth_date, p.photo_url,""" + PLAYER_TEAMS_COLUMNS + """,
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
           round(avg(NULLIF(ps.rating, 0)) FILTER (WHERE ps.minutes > 0), 2) AS avg_rating,
           max(f.kickoff_at) FILTER (WHERE ps.minutes > 0) AS last_played
      FROM core.fixture_player_stats ps JOIN core.fixtures f ON f.id = ps.fixture_id
     WHERE f.kickoff_at > %(since)s
       AND ((ps.team_side = 'home' AND f.home_team_id = %(team)s) OR (ps.team_side = 'away' AND f.away_team_id = %(team)s))
     GROUP BY ps.provider_player_id
)
SELECT p.id, p.provider_player_id, p.name, p.nationality, p.position, p.birth_date, p.photo_url,
       %(team)s::bigint AS team_id, t.name AS team, t.logo_url AS team_logo, NULL::text AS national_team_logo,
       NULL::text AS club_source, NULL::bigint AS national_team_id,
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
           sum(ps.goals)::int AS goals, sum(ps.assists)::int AS assists,
           round(avg(NULLIF(ps.rating, 0)), 2) AS avg_rating,
           max(f.kickoff_at) AS last_played,
           (array_agg(t.id ORDER BY f.kickoff_at DESC))[1] AS last_team_id,
           (array_agg(t.id ORDER BY f.kickoff_at DESC)
                FILTER (WHERE NOT COALESCE(k.is_national, t.is_national, false)))[1] AS last_club_id,
           (array_agg(t.id ORDER BY f.kickoff_at DESC)
                FILTER (WHERE COALESCE(k.is_national, t.is_national, false)))[1] AS last_national_id
      FROM core.fixtures f JOIN core.fixture_player_stats ps ON ps.fixture_id = f.id
      JOIN core.teams t ON t.id = CASE ps.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
      LEFT JOIN core.team_kind k ON k.team_id = t.id
     WHERE f.kickoff_at > %(recent)s AND f.kickoff_at <= %(at)s AND ps.minutes > 0
     GROUP BY ps.provider_player_id
)
SELECT p.id, p.provider_player_id, p.name, p.nationality, p.position, p.birth_date, p.photo_url,""" + PLAYER_TEAMS_COLUMNS + """,
       a.apps, a.minutes, a.goals, a.assists, a.avg_rating, a.last_played
  FROM recent a JOIN core.players p ON p.provider_player_id = a.provider_player_id""" + TEAMS_OF_PLAYER + """
 ORDER BY a.goals DESC NULLS LAST, a.avg_rating DESC NULLS LAST, p.name
 LIMIT %(limit)s OFFSET %(offset)s
"""

PLAYER = """
SELECT p.id, p.provider_player_id, p.name, p.nationality, p.position, p.birth_date, p.photo_url, p.firstname,
       p.lastname, p.height_cm, p.weight_kg,""" + PLAYER_TEAMS_COLUMNS + """,
       COALESCE(a.apps, 0) AS apps, a.minutes, a.goals, a.assists, a.avg_rating, a.last_played
  FROM core.players p
  LEFT JOIN LATERAL (""" + PLAYER_AGG + """) a ON true""" + TEAMS_OF_PLAYER + """
 WHERE p.id = %(id)s
"""

PLAYER_SEASONS = """
-- One row per competition, season AND team - the provider's own scope (a transfer gives two).
SELECT c.name AS competition, cs.season, t.name AS team, COALESCE(k.is_national, t.is_national, false) AS national,
       count(*) FILTER (WHERE ps.minutes > 0)::int AS apps,
       count(*) FILTER (WHERE ps.minutes > 0 AND NOT COALESCE(ps.is_substitute, false))::int AS starts,
       sum(ps.minutes)::int AS minutes, sum(ps.goals)::int AS goals, sum(ps.assists)::int AS assists,
       sum(ps.yellow_cards)::int AS yellow_cards, sum(ps.red_cards)::int AS red_cards,
       round(avg(NULLIF(ps.rating, 0)) FILTER (WHERE ps.minutes > 0), 2) AS avg_rating
  FROM core.fixture_player_stats ps
  JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id = CASE ps.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
  LEFT JOIN core.team_kind k ON k.team_id = t.id
 WHERE ps.provider_player_id = %(pid)s
 GROUP BY c.name, cs.season, t.name, COALESCE(k.is_national, t.is_national, false)
HAVING count(*) FILTER (WHERE ps.minutes > 0) > 0
 ORDER BY cs.season DESC, count(*) FILTER (WHERE ps.minutes > 0) DESC
"""

PLAYER_MATCHES = """
SELECT f.id AS fixture_id, f.kickoff_at, c.name AS competition,
       CASE ps.team_side WHEN 'home' THEN th.name ELSE ta.name END AS team,
       CASE ps.team_side WHEN 'home' THEN ta.name ELSE th.name END AS opponent,
       ps.minutes, NULLIF(ps.rating, 0) AS rating, ps.goals, ps.assists, ps.is_substitute AS substitute
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

PLAYER_TRANSFERS = """
SELECT x.transfer_date, x.type, ti.id AS team_in_id, x.team_in_id AS team_in_provider_id, x.team_in_name AS team_in,
       tout.id AS team_out_id, x.team_out_id AS team_out_provider_id, x.team_out_name AS team_out,
       x.observed_at, x.payload_hash, x.normalizer_version
  FROM core.player_transfers_latest x
  LEFT JOIN core.teams ti ON ti.provider_team_id = x.team_in_id
  LEFT JOIN core.teams tout ON tout.provider_team_id = x.team_out_id
 WHERE x.provider_player_id = %(pid)s
 ORDER BY x.ordinal
"""

PLAYER_SIDELINED = """
SELECT type, start_date AS start, end_date AS "end", observed_at, payload_hash, normalizer_version
  FROM core.person_sidelined_latest WHERE person_kind = 'player' AND provider_person_id = %(pid)s ORDER BY ordinal
"""

PLAYER_TROPHIES = """
SELECT t.league, t.country, t.season, t.place, t.observed_at, t.payload_hash, t.normalizer_version
  FROM core.person_trophies_latest t
 WHERE t.person_kind = 'player' AND t.provider_person_id = %(pid)s
   AND NOT (t.season IS NULL AND EXISTS (
        SELECT 1 FROM core.person_trophies_latest d
         WHERE d.person_kind = t.person_kind AND d.provider_person_id = t.provider_person_id AND d.season IS NOT NULL
           AND d.league IS NOT DISTINCT FROM t.league AND d.country IS NOT DISTINCT FROM t.country
           AND d.place IS NOT DISTINCT FROM t.place))
 ORDER BY t.ordinal
"""
"""The provider's trophies, without its group rows: /trophies follows the dated entries of a competition and
place with one more entry whose season is null (4 Oct 2026: 672 of 1,285 groups, never a group on its own) - a
summary of the group, not another trophy. Stored as sent; a season-less entry with no dated sibling is shown."""

PERSON_CHECKS = """
SELECT feed, max(checked_at) AS checked_at FROM core.reference_checks
 WHERE target = %(key)s AND feed IN ('sidelined_players', 'trophies_players', 'players_teams') GROUP BY feed
"""

PLAYER_PROVIDER_SEASONS = """
SELECT s.season, s.provider_league_id, c.id AS competition_id, c.name AS competition, s.provider_team_id,
       t.id AS team_id, t.name AS team, COALESCE(k.is_national, t.is_national) AS national, s.appearances, s.lineups,
       s.minutes, s.goals, s.assists, s.yellow_cards, s.red_cards, NULLIF(s.rating, 0) AS rating, s.observed_at,
       s.payload_hash, s.normalizer_version
  FROM core.player_season_stats_latest s
  LEFT JOIN core.competitions c ON c.provider_league_id = s.provider_league_id
  LEFT JOIN core.teams t ON t.provider_team_id = s.provider_team_id
  LEFT JOIN core.team_kind k ON k.team_id = t.id
 WHERE s.provider_player_id = %(pid)s
 ORDER BY s.season DESC, s.appearances DESC NULLS LAST, c.name, s.provider_team_id
"""
"""The provider's season aggregates of a player (newest row per player, competition, season and team). A rating of 0
is the provider's "not rated", shown as none."""

PLAYER_CAREER = """
SELECT x.provider_team_id, t.id AS team_id, COALESCE(x.team_name, t.name) AS team,
       COALESCE(x.team_logo, t.logo_url) AS team_logo, COALESCE(k.is_national, t.is_national) AS national, x.seasons,
       x.observed_at, x.payload_hash, x.normalizer_version
  FROM core.player_team_seasons_latest x
  LEFT JOIN core.teams t ON t.provider_team_id = x.provider_team_id
  LEFT JOIN core.team_kind k ON k.team_id = t.id
 WHERE x.provider_player_id = %(pid)s
 ORDER BY x.ordinal
"""

REFERENCE_SEASONS = """
SELECT cs.id, cs.season, cs.is_current FROM core.competition_seasons cs WHERE cs.competition_id = %(c)s
 ORDER BY (EXISTS (SELECT 1 FROM core.season_leaders l WHERE l.competition_season_id = cs.id)
           OR EXISTS (SELECT 1 FROM core.season_rounds r WHERE r.competition_season_id = cs.id)) DESC,
          cs.is_current DESC, cs.season DESC
"""

COMPETITION_LEADERS = """
SELECT l.list, l.ordinal + 1 AS rank, l.provider_player_id, p.id AS player_id, l.player_name AS name,
       coalesce(l.photo_url, p.photo_url) AS photo_url, t.id AS team_id, l.provider_team_id, l.team_name AS team,
       t.logo_url AS team_logo, l.appearances, l.minutes, l.goals, l.assists, l.penalties_scored, l.yellow_cards,
       l.yellowred_cards, l.red_cards, NULLIF(l.rating, 0) AS rating,
       (SELECT count(*)::int FROM core.fixture_player_stats ps JOIN core.fixtures f ON f.id = ps.fixture_id
         WHERE f.competition_season_id = l.competition_season_id AND ps.provider_player_id = l.provider_player_id
           AND ps.rating = 0 AND COALESCE(ps.minutes, 0) > 0) AS unrated_matches,
       l.observed_at, l.payload_hash, l.normalizer_version
  FROM core.season_leaders_latest l
  LEFT JOIN core.players p ON p.provider_player_id = l.provider_player_id
  LEFT JOIN core.teams t ON t.provider_team_id = l.provider_team_id
 WHERE l.competition_season_id = %(cs)s
 ORDER BY l.list, l.ordinal
"""

COMPETITION_ROUNDS = """
SELECT ordinal, round, dates, observed_at, payload_hash, normalizer_version
  FROM core.season_rounds_latest WHERE competition_season_id = %(cs)s ORDER BY ordinal
"""

CURRENT_ROUNDS = """
SELECT rounds, observed_at FROM core.season_current_round WHERE competition_season_id = %(cs)s
 ORDER BY observed_at DESC LIMIT 1
"""

REFERENCE_CHECK = """
SELECT max(checked_at) AS checked_at FROM core.reference_checks WHERE feed = %(feed)s AND target = %(key)s
"""

PROVIDER_PREDICTIONS = """
SELECT observed_at, winner_team_id, winner_name, winner_comment, win_or_draw, under_over, goals_home, goals_away,
       advice, percent_home, percent_draw, percent_away, comparison, payload_hash, normalizer_version
  FROM core.provider_predictions WHERE fixture_id = %(f)s ORDER BY observed_at
"""

PREDICTION_CHECKS = """
SELECT count(*) AS n FROM core.reference_checks
 WHERE feed = 'predictions' AND target LIKE 'fixture:' || %(pf)s || ':%%'
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
  (SELECT count(*) FROM market.live_odds_current) AS live_quotes_now,
  (SELECT max(captured_at) FROM market.live_fixture_current) AS live_last,
  (SELECT count(*) FROM market.live_fixture_current
    WHERE captured_at > %(at)s - interval '5 minutes') AS live_priced_now,
  (SELECT max(finished_at) FROM raw.ingestion_runs
    WHERE job_type = 'live_odds_capture' AND status = 'completed') AS live_tick_last,
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
 WHERE started_at > %(at)s - interval '72 hours' AND status IN ('failed', 'partial', 'aborted', 'interrupted', 'stale')
 ORDER BY started_at DESC LIMIT 30
"""

QUALITY_COUNTS = """
SELECT severity, count(*)::int AS n, max(last_seen_at) AS at
  FROM audit.data_quality_issues WHERE status = 'open' GROUP BY severity
"""


COMPETITION_SEASONS = """
SELECT cs.id, cs.season FROM core.competition_seasons cs
 WHERE cs.competition_id = %(c)s
   AND EXISTS (SELECT 1 FROM core.standings s WHERE s.competition_season_id = cs.id)
 ORDER BY cs.season DESC
"""

COMPETITION_TABLE = """
SELECT s.group_key, s.rank, s.team_id, t.name AS team, t.logo_url AS team_logo, s.played, s.wins, s.draws,
       s.losses, s.goals_for, s.goals_against, s.points, s.form, s."group", s.goals_diff, s.description,
       s.zone_status, s.home_played, s.home_wins, s.home_draws, s.home_losses, s.home_goals_for,
       s.home_goals_against, s.away_played, s.away_wins, s.away_draws, s.away_losses, s.away_goals_for,
       s.away_goals_against
  FROM core.standings s JOIN core.teams t ON t.id = s.team_id
 WHERE s.competition_season_id = %(cs)s AND s.snapshot_at = %(at)s
 ORDER BY s.group_key, s.rank NULLS LAST, t.name
"""
"""One snapshot's rows of every table; the service keeps each table apart (``group_key``)."""
