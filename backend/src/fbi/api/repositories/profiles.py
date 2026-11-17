"""SQL of the profiles (C-09; AD-H07 ``IA-090``, AD-H05 ``IA-091``, AD-H06 ``IA-092``). Plain rows out; every query is bounded by
the entity asked for (its id, its fixtures, its season) and by time - never a sweep of a whole table.

The facts of the press are read through ``fbi.ai.evidence.CONTEXT_SQL`` (v1's items only: a claim of research v2, in shadow, never
reaches a profile; and this module adds no reader of ``ai.evidence``). What is never selected here: the text of a claim, the provider's reason of an absence beyond
what tells a suspension from an injury (read and dropped in ``fbi.people.availability``), a sidelined episode's type or dates,
and the provider's photos. A sheet line with ``provider_player_id = 0`` (a man the provider did not identify) never makes a
leader.
"""

from __future__ import annotations

from typing import Final

TEAM: Final = """
SELECT t.id, t.provider_team_id, t.name, t.short_name, t.country, t.founded, t.venue_id, t.logo_url,
       COALESCE(k.is_national, t.is_national, false) AS national
  FROM core.teams t LEFT JOIN core.team_kind k ON k.team_id = t.id
 WHERE t.id = %(id)s
"""

VENUE: Final = "SELECT v.id, v.name, v.city, v.capacity FROM core.venues v WHERE v.id = %(id)s"

VENUE_ALTITUDE: Final = "SELECT g.elevation_m FROM core.venue_geo_live g WHERE g.venue_id = %(id)s LIMIT 1"
"""AD-H04 (migration 0144): read inside a savepoint - a database without it answers «sin_datos»."""

_TEAM_MATCH: Final = """
SELECT f.id AS fixture_id, f.kickoff_at, c.id AS competition_id, c.name AS competition, (f.home_team_id = %(id)s) AS home,
       o.id AS opponent_id, o.name AS opponent, r.goals_home, r.goals_away, f.competition_season_id
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams o ON o.id = CASE WHEN f.home_team_id = %(id)s THEN f.away_team_id ELSE f.home_team_id END
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE (f.home_team_id = %(id)s OR f.away_team_id = %(id)s)
"""

FORM: Final = _TEAM_MATCH + """
   AND f.status_group = 'finished' AND r.goals_home IS NOT NULL AND r.goals_away IS NOT NULL AND f.kickoff_at <= %(now)s
 ORDER BY f.kickoff_at DESC LIMIT %(limit)s
"""

UPCOMING: Final = _TEAM_MATCH + """
   AND f.status_group = 'scheduled' AND f.kickoff_at > %(now)s
 ORDER BY f.kickoff_at ASC LIMIT %(limit)s
"""

CAMPAIGN: Final = _TEAM_MATCH + """
   AND f.status_group = 'finished' AND r.goals_home IS NOT NULL AND r.goals_away IS NOT NULL
   AND f.kickoff_at > %(since)s AND f.kickoff_at <= %(now)s
 ORDER BY f.kickoff_at DESC
"""
"""The team's finished matches of the last ``CAMPAIGN_DAYS``: the record per competition and the headline season."""

SEASONS: Final = """
SELECT cs.id, cs.season, c.competition_type, c.type FROM core.competition_seasons cs
  JOIN core.competitions c ON c.id = cs.competition_id WHERE cs.id = ANY(%(ids)s)
"""

SEASON_TEAM_STATS: Final = """
SELECT f.id AS fixture_id, (f.home_team_id = %(id)s) AS home,
       mine.expected_goals AS xg_for, opp.expected_goals AS xg_against, mine.shots AS shots_for,
       mine.shots_on_target AS shots_on_target_for, mine.corners AS corners_for, mine.yellow_cards AS yellow_cards_for
  FROM core.fixtures f
  LEFT JOIN LATERAL (SELECT s.* FROM core.fixture_team_stats s WHERE s.fixture_id = f.id
                        AND s.team_side = CASE WHEN f.home_team_id = %(id)s THEN 'home' ELSE 'away' END
                      ORDER BY s.fetched_at DESC LIMIT 1) mine ON true
  LEFT JOIN LATERAL (SELECT s.* FROM core.fixture_team_stats s WHERE s.fixture_id = f.id
                        AND s.team_side = CASE WHEN f.home_team_id = %(id)s THEN 'away' ELSE 'home' END
                      ORDER BY s.fetched_at DESC LIMIT 1) opp ON true
 WHERE f.id = ANY(%(fixtures)s)
"""

TEAM_STANDING: Final = """
SELECT DISTINCT ON (s.competition_season_id) s.competition_season_id, s.rank, s.points
  FROM core.standings s
 WHERE s.team_id = %(id)s AND s.competition_season_id = ANY(%(seasons)s)
 ORDER BY s.competition_season_id, s.snapshot_at DESC
"""

HONOURS: Final = """
WITH won AS (SELECT DISTINCT s.competition_season_id FROM core.standings s WHERE s.team_id = %(id)s AND s.rank = 1),
     last AS (SELECT s.competition_season_id, max(s.snapshot_at) AS at FROM core.standings s
               WHERE s.competition_season_id IN (SELECT competition_season_id FROM won) GROUP BY 1)
SELECT c.id AS competition_id, c.name AS competition, cs.season
  FROM last
  JOIN core.standings s ON s.competition_season_id = last.competition_season_id AND s.snapshot_at = last.at
  JOIN core.competition_seasons cs ON cs.id = s.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE s.team_id = %(id)s AND s.rank = 1 AND c.type = 'league' AND cs.end_date < %(today)s
   AND (SELECT count(DISTINCT COALESCE(x.group_key, '')) FROM core.standings x
         WHERE x.competition_season_id = s.competition_season_id AND x.snapshot_at = last.at) = 1
   AND EXISTS (SELECT 1 FROM core.competition_stages st WHERE st.competition_season_id = cs.id)
   AND NOT EXISTS (SELECT 1 FROM core.competition_stages st WHERE st.competition_season_id = cs.id
                    AND st.role IS DISTINCT FROM 'league')
 ORDER BY cs.season DESC
"""
"""A league title: the team first in the FINAL table of a league season that has ended, played as one table and with no stage
other than the league itself (no play-off, no final: where a play-off decides the champion, the table's first is not)."""

FIRST_SEASON: Final = """
SELECT least((SELECT min(cs.season) FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
               WHERE (f.home_team_id = %(id)s OR f.away_team_id = %(id)s) AND f.status_group = 'finished'),
             (SELECT min(cs.season) FROM core.standings s JOIN core.competition_seasons cs ON cs.id = s.competition_season_id
               WHERE s.team_id = %(id)s))
"""

SQUAD: Final = """
SELECT p.id AS player_id, sm.provider_player_id, sm.player_name, sm.shirt_number, core.position_group(sm.position) AS position,
       sm.age, sm.last_seen_at
  FROM core.squad_members sm
  LEFT JOIN core.players p ON p.provider_player_id = sm.provider_player_id
 WHERE sm.team_id = %(id)s
   AND sm.last_seen_at >= (SELECT max(x.last_seen_at) - interval '1 day' FROM core.squad_members x WHERE x.team_id = %(id)s)
 ORDER BY core.position_group(sm.position) NULLS LAST, sm.shirt_number NULLS LAST, sm.player_name
"""
"""The newest squad answer of the provider for the team (the rows seen within a day of its newest)."""

PLAYER_IDS: Final = "SELECT provider_player_id, id FROM core.players WHERE provider_player_id = ANY(%(pids)s)"

SEASON_OF_FIXTURE: Final = "SELECT competition_season_id FROM core.fixtures WHERE id = %(id)s"

SHADOW_SELECTIONS: Final = """
SELECT * FROM (
  SELECT DISTINCT ON (l.chain_key) l.fixture_id, l.market_key, l.selection, l.line, l.state, l.evaluation, l.known_at
    FROM intel.selection_lifecycle l
   WHERE l.fixture_id = ANY(%(fixtures)s)
   ORDER BY l.chain_key, l.known_at DESC, l.id DESC) x
 ORDER BY x.known_at DESC LIMIT 50
"""

TEAM_FIXTURE_IDS: Final = """
SELECT f.id FROM core.fixtures f
 WHERE (f.home_team_id = %(id)s OR f.away_team_id = %(id)s) AND f.kickoff_at > %(from)s AND f.kickoff_at <= %(to)s
"""

IDENTITY: Final = """
SELECT i.system, i.external_id, i.method, i.confidence, i.state FROM core.entity_ids_live i
 WHERE i.entity_type = %(type)s AND i.entity_id = %(id)s ORDER BY i.system, i.external_id
"""

OPEN_REVIEWS: Final = """
SELECT count(*) FROM core.entity_identity_queue_open q
 WHERE q.entity_type = %(type)s AND (q.entity_a = %(id)s OR q.entity_b = %(id)s)
"""

# ── national teams ──────────────────────────────────────────────────────────────────────────────────────────────────

LAST_MATCH_SQUAD: Final = """
WITH m AS (
  SELECT f.id, f.kickoff_at, CASE WHEN f.home_team_id = %(id)s THEN 'home' ELSE 'away' END AS side
    FROM core.fixtures f
   WHERE (f.home_team_id = %(id)s OR f.away_team_id = %(id)s) AND f.kickoff_at <= %(now)s
     AND EXISTS (SELECT 1 FROM core.fixture_lineup_players lp WHERE lp.fixture_id = f.id
                  AND lp.team_side = CASE WHEN f.home_team_id = %(id)s THEN 'home' ELSE 'away' END)
   ORDER BY f.kickoff_at DESC LIMIT 1)
SELECT m.id AS fixture_id, m.kickoff_at, p.id AS player_id, lp.provider_player_id, lp.player_name,
       core.position_group(COALESCE(p.position, lp.position)) AS position
  FROM m JOIN core.fixture_lineup_players lp ON lp.fixture_id = m.id AND lp.team_side = m.side
  LEFT JOIN core.players p ON p.provider_player_id = lp.provider_player_id
 ORDER BY lp.is_starter DESC, lp.shirt_number NULLS LAST, lp.player_name
"""
"""The matchday squad (starters and bench) of the side's newest match with a line-up."""

CLUBS_OF: Final = """
SELECT DISTINCT ON (sm.provider_player_id) sm.provider_player_id, t.id, t.name
  FROM core.squad_members sm
  JOIN core.teams t ON t.id = sm.team_id
  LEFT JOIN core.team_kind k ON k.team_id = t.id
 WHERE sm.provider_player_id = ANY(%(pids)s) AND NOT COALESCE(k.is_national, t.is_national, false)
 ORDER BY sm.provider_player_id, sm.last_seen_at DESC
"""
"""Each man's club: the club whose newest squad lists him."""

CAPS_LEADERS: Final = """
SELECT c.provider_player_id, p.id AS player_id, COALESCE(p.name, c.provider_player_id::text) AS name,
       count(DISTINCT c.fixture_id)::int AS value
  FROM core.player_national_caps c
  LEFT JOIN core.players p ON p.provider_player_id = c.provider_player_id
 WHERE c.team_id = %(id)s AND c.appeared AND c.provider_player_id > 0
 GROUP BY c.provider_player_id, p.id, p.name
 ORDER BY count(DISTINCT c.fixture_id) DESC, 3 LIMIT %(limit)s
"""

SCORERS: Final = """
SELECT ps.provider_player_id, p.id AS player_id, COALESCE(p.name, max(ps.player_name)) AS name, sum(ps.goals)::int AS value
  FROM core.fixtures f
  JOIN core.fixture_player_stats ps ON ps.fixture_id = f.id
   AND ps.team_side = CASE WHEN f.home_team_id = %(id)s THEN 'home' ELSE 'away' END
  LEFT JOIN core.players p ON p.provider_player_id = ps.provider_player_id
 WHERE (f.home_team_id = %(id)s OR f.away_team_id = %(id)s) AND f.status_group = 'finished'
   AND f.kickoff_at > %(since)s AND f.kickoff_at <= %(now)s AND ps.provider_player_id > 0
 GROUP BY ps.provider_player_id, p.id, p.name
HAVING sum(ps.goals) > 0
 ORDER BY sum(ps.goals) DESC, 3 LIMIT %(limit)s
"""

# ── players ─────────────────────────────────────────────────────────────────────────────────────────────────────────

PLAYER_LINES: Final = """
SELECT f.id AS fixture_id, f.kickoff_at, c.id AS competition_id, c.name AS competition, cs.season,
       t.id AS team_id, t.name AS team, o.id AS opponent_id, o.name AS opponent,
       ps.minutes, NOT COALESCE(ps.is_substitute, false) AS started, ps.goals, ps.assists, ps.shots_total, ps.shots_on,
       ps.fouls_committed, ps.yellow_cards, ps.red_cards, ps.saves
  FROM core.fixture_player_stats ps
  JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id = CASE ps.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
  JOIN core.teams o ON o.id = CASE ps.team_side WHEN 'home' THEN f.away_team_id ELSE f.home_team_id END
 WHERE ps.provider_player_id = %(pid)s AND ps.minutes > 0 AND f.kickoff_at > %(since)s AND f.kickoff_at <= %(now)s
 ORDER BY f.kickoff_at DESC
"""
"""His appearances (minutes > 0) of the window, newest first: form, season lines and rates all come from these rows."""

PLAYER_SHIRT: Final = """
SELECT sm.shirt_number FROM core.squad_members sm WHERE sm.provider_player_id = %(pid)s AND sm.team_id = %(team)s
 ORDER BY sm.last_seen_at DESC LIMIT 1
"""

PLAYER_SPELLS: Final = """
SELECT t.id AS team_id, s.team_name, s.valid_from, s.valid_to, s.matches
  FROM core.player_spells s LEFT JOIN core.teams t ON t.provider_team_id = s.provider_team_id
 WHERE s.provider_player_id = %(pid)s ORDER BY s.valid_from DESC, s.ordinal DESC LIMIT 40
"""

PLAYER_CAPS: Final = """
SELECT c.team_id, t.name, count(*)::int AS matches, count(*) FILTER (WHERE c.appeared)::int AS appeared,
       count(*) FILTER (WHERE c.is_starter)::int AS starts, COALESCE(sum(c.minutes), 0)::int AS minutes,
       max(f.kickoff_at) AS last_at
  FROM core.player_national_caps c JOIN core.teams t ON t.id = c.team_id JOIN core.fixtures f ON f.id = c.fixture_id
 WHERE c.provider_player_id = %(pid)s
 GROUP BY c.team_id, t.name ORDER BY count(*) DESC LIMIT 1
"""

# ── competitions ────────────────────────────────────────────────────────────────────────────────────────────────────

COMPETITION: Final = """
SELECT c.id, c.provider_league_id, c.name, c.country, c.type, c.gender, c.age_group, c.is_tracked, c.logo_url
  FROM core.competitions c WHERE c.id = %(id)s
"""

CURRENT_SEASON: Final = """
SELECT cs.id, cs.season, cs.start_date, cs.end_date, cs.is_current FROM core.competition_seasons cs
 WHERE cs.competition_id = %(id)s
 ORDER BY cs.is_current DESC, cs.season DESC LIMIT 1
"""

STANDINGS: Final = """
SELECT s.rank, s.team_id, t.name, s.group_key, s."group", s.played, s.points, s.goals_for, s.goals_against, s.snapshot_at
  FROM core.standings s JOIN core.teams t ON t.id = s.team_id
 WHERE s.competition_season_id = %(season)s
   AND s.snapshot_at = (SELECT max(x.snapshot_at) FROM core.standings x WHERE x.competition_season_id = %(season)s)
 ORDER BY s.group_key NULLS FIRST, s.rank LIMIT 60
"""

COMPETITION_UPCOMING: Final = """
SELECT f.id AS fixture_id, f.kickoff_at, h.id AS home_id, h.name AS home, a.id AS away_id, a.name AS away
  FROM core.fixtures f JOIN core.teams h ON h.id = f.home_team_id JOIN core.teams a ON a.id = f.away_team_id
 WHERE f.competition_season_id = %(season)s AND f.status_group = 'scheduled' AND f.kickoff_at > %(now)s
 ORDER BY f.kickoff_at LIMIT %(limit)s
"""

COMPETITION_SCORERS: Final = """
SELECT ps.provider_player_id, p.id AS player_id, COALESCE(p.name, max(ps.player_name)) AS name, sum(ps.goals)::int AS value
  FROM core.fixtures f JOIN core.fixture_player_stats ps ON ps.fixture_id = f.id
  LEFT JOIN core.players p ON p.provider_player_id = ps.provider_player_id
 WHERE f.competition_season_id = %(season)s AND f.status_group = 'finished' AND ps.provider_player_id > 0
 GROUP BY ps.provider_player_id, p.id, p.name
HAVING sum(ps.goals) > 0
 ORDER BY sum(ps.goals) DESC, 3 LIMIT %(limit)s
"""

COMPETITION_COVERAGE: Final = """
SELECT count(*)::int AS finished,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM core.fixture_player_stats ps WHERE ps.fixture_id = f.id))::int AS players,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM core.fixture_team_stats ts WHERE ts.fixture_id = f.id))::int AS teams
  FROM core.fixtures f WHERE f.competition_season_id = %(season)s AND f.status_group = 'finished'
"""
