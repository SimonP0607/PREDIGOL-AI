"""Competitions and teams."""

from __future__ import annotations

from fbi.api.repositories import Conn, Row, fetch_all, fetch_one

_COMPETITIONS = """
SELECT c.id, c.provider_league_id, c.name, c.country, c.type, c.competition_type, c.tier, c.is_tracked,
       c.logo_url, c.flag_url, c.country_code,
       count(DISTINCT cs.id) AS seasons,
       max(cs.season) FILTER (WHERE cs.is_current) AS current_season,
       count(DISTINCT f.id) AS fixtures,
       count(DISTINCT t.team_id) AS teams
FROM core.competitions c
LEFT JOIN core.competition_seasons cs ON cs.competition_id = c.id
LEFT JOIN core.fixtures f ON f.competition_season_id = cs.id
LEFT JOIN LATERAL (VALUES (f.home_team_id), (f.away_team_id)) AS t(team_id) ON f.id IS NOT NULL
WHERE (%(tracked)s::boolean IS NULL OR c.is_tracked = %(tracked)s::boolean)
  AND (%(q)s::text IS NULL OR c.name ILIKE %(q)s::text OR c.country ILIKE %(q)s::text)
  AND (%(competition_id)s::bigint IS NULL OR c.id = %(competition_id)s::bigint)
GROUP BY c.id
ORDER BY c.is_tracked DESC, (count(DISTINCT f.id) > 0) DESC, c.tier NULLS LAST, c.country NULLS LAST, c.name
LIMIT %(limit)s OFFSET %(offset)s
"""


def list_competitions(
    conn: Conn, *, tracked: bool | None, q: str | None, limit: int, offset: int, competition_id: int | None = None
) -> list[Row]:
    return fetch_all(conn, _COMPETITIONS, {
        "tracked": tracked, "q": f"%{q}%" if q else None, "limit": limit, "offset": offset,
        "competition_id": competition_id,
    })


def count_competitions(conn: Conn, *, tracked: bool | None, q: str | None) -> int:
    r = fetch_one(conn, """
        SELECT count(*) AS n FROM core.competitions c
        WHERE (%(tracked)s::boolean IS NULL OR c.is_tracked = %(tracked)s::boolean)
          AND (%(q)s::text IS NULL OR c.name ILIKE %(q)s::text OR c.country ILIKE %(q)s::text)
    """, {"tracked": tracked, "q": f"%{q}%" if q else None})
    return int(r["n"]) if r else 0


def seasons_of(conn: Conn, competition_id: int) -> list[Row]:
    return fetch_all(conn, """
        SELECT cs.id, cs.season, cs.start_date, cs.end_date, cs.is_current, cs.has_odds,
               count(f.id) AS fixtures,
               count(f.id) FILTER (WHERE f.status_group = 'finished') AS finished,
               count(r.fixture_id) AS with_results
        FROM core.competition_seasons cs
        LEFT JOIN core.fixtures f ON f.competition_season_id = cs.id
        LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
        WHERE cs.competition_id = %s
        GROUP BY cs.id ORDER BY cs.season DESC
    """, (competition_id,))


def teams_of(conn: Conn, competition_id: int) -> list[Row]:
    return fetch_all(conn, """
        SELECT DISTINCT t.id, t.name, t.provider_team_id, t.logo_url
        FROM core.fixtures f
        JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
        JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
        WHERE cs.competition_id = %s
        ORDER BY t.name
    """, (competition_id,))


_TEAMS = """
-- Appearances as two plain joins (home side, away side) aggregated once. The
-- previous form joined teams to fixtures ON t.id IN (home, away): a nested loop
-- of 8,165 teams by 216,000 fixtures that hit the 10 s statement timeout, so the
-- Teams page answered 500.
WITH apps AS (
    SELECT f.home_team_id AS team_id, f.id AS fixture_id, cs.competition_id
      FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
    UNION ALL
    SELECT f.away_team_id, f.id, cs.competition_id
      FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
), agg AS (
    SELECT a.team_id, count(DISTINCT a.fixture_id) AS fixtures, count(DISTINCT r.fixture_id) AS results
      FROM apps a LEFT JOIN core.fixture_results r ON r.fixture_id = a.fixture_id
     WHERE %(competition_id)s::bigint IS NULL OR a.competition_id = %(competition_id)s::bigint
     GROUP BY a.team_id
)
SELECT t.id, t.provider_team_id, t.name, t.country, t.venue_id, t.logo_url,
       COALESCE(agg.fixtures, 0) AS fixtures, COALESCE(agg.results, 0) AS results
FROM core.teams t
LEFT JOIN agg ON agg.team_id = t.id
WHERE (%(q)s::text IS NULL OR t.name ILIKE %(q)s::text)
  AND (%(team_id)s::bigint IS NULL OR t.id = %(team_id)s::bigint)
  AND (%(competition_id)s::bigint IS NULL OR agg.fixtures > 0)
ORDER BY COALESCE(agg.fixtures, 0) DESC, t.name
LIMIT %(limit)s OFFSET %(offset)s
"""


def list_teams(
    conn: Conn, *, q: str | None, competition_id: int | None, limit: int, offset: int, team_id: int | None = None
) -> list[Row]:
    return fetch_all(conn, _TEAMS, {
        "q": f"%{q}%" if q else None, "competition_id": competition_id, "limit": limit,
        "offset": offset, "team_id": team_id,
    })


TEAM_RECORDS = """
-- One row per competition-season of the team's recorded results (final score, extra time included).
WITH games AS (
    SELECT cs.id AS cs_id, c.name AS competition, c.type AS competition_type, cs.season, f.kickoff_at,
           CASE WHEN f.home_team_id = %(t)s THEN r.goals_home ELSE r.goals_away END AS gf,
           CASE WHEN f.home_team_id = %(t)s THEN r.goals_away ELSE r.goals_home END AS ga
      FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
     WHERE %(t)s IN (f.home_team_id, f.away_team_id) AND r.goals_home IS NOT NULL AND r.goals_away IS NOT NULL
)
SELECT competition, competition_type, season, count(*) AS played, count(*) FILTER (WHERE gf > ga) AS won,
       count(*) FILTER (WHERE gf = ga) AS drawn, count(*) FILTER (WHERE gf < ga) AS lost,
       sum(gf) AS goals_for, sum(ga) AS goals_against, min(kickoff_at) AS first, max(kickoff_at) AS last
  FROM games GROUP BY cs_id, competition, competition_type, season
 ORDER BY max(kickoff_at) DESC
"""


def team_records(conn: Conn, team_id: int) -> list[Row]:
    """The team's record per competition and season, newest first."""
    return fetch_all(conn, TEAM_RECORDS, {"t": team_id})


def team_record(conn: Conn, team_id: int) -> Row | None:
    """W/D/L and goals over RECORDED results only, every competition and season (the lifetime figure)."""
    rows = team_records(conn, team_id)
    if not rows:
        return None
    keys = ("played", "won", "drawn", "lost", "goals_for", "goals_against")
    out: Row = {k: sum(int(r[k] or 0) for r in rows) for k in keys}
    return {**out, "since": min(r["first"] for r in rows), "competitions": len({r["competition"] for r in rows})}
