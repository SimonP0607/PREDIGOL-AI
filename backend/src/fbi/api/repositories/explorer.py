"""SQL for the Analytics page. Plain rows out; the service shapes them."""

from __future__ import annotations

from fbi.api.repositories import Conn, Row, fetch_all, fetch_one

FIXTURE_FLAGS = """
WITH fx AS (
    SELECT f.id, f.status_group, cs.competition_id, cs.season,
           EXISTS (SELECT 1 FROM core.fixture_results r WHERE r.fixture_id = f.id) AS has_result,
           EXISTS (SELECT 1 FROM core.fixture_team_stats t WHERE t.fixture_id = f.id) AS has_stats,
           EXISTS (SELECT 1 FROM core.fixture_events e WHERE e.fixture_id = f.id) AS has_events,
           EXISTS (SELECT 1 FROM core.fixture_lineups l WHERE l.fixture_id = f.id) AS has_lineups,
           EXISTS (SELECT 1 FROM core.fixture_player_stats p WHERE p.fixture_id = f.id) AS has_players,
           EXISTS (SELECT 1 FROM market.historical_odds h WHERE h.fixture_id = f.id) AS has_hist,
           EXISTS (SELECT 1 FROM market.odds_snapshots o WHERE o.fixture_id = f.id) AS has_snap,
           EXISTS (SELECT 1 FROM features.feature_sets s WHERE s.fixture_id = f.id
                   AND s.feature_version = %(fv)s) AS has_features,
           EXISTS (SELECT 1 FROM models.predictions p WHERE p.fixture_id = f.id) AS has_pred
    FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
)
"""


def competition_profiles(conn: Conn, feature_version: str) -> list[Row]:
    return fetch_all(conn, FIXTURE_FLAGS + """
        SELECT c.id AS competition_id, c.name AS competition, c.country, c.competition_type, fx.season,
               count(*) AS fixtures, count(r.fixture_id) AS finished,
               avg((r.outcome_1x2 = 'Home')::int) AS home_win, avg((r.outcome_1x2 = 'Draw')::int) AS draw,
               avg((r.outcome_1x2 = 'Away')::int) AS away_win,
               avg(r.total_goals) AS goals_per_match,
               avg(r.goals_home - coalesce(r.et_goals_home, 0)) AS home_goals_per_match,
               avg(r.goals_away - coalesce(r.et_goals_away, 0)) AS away_goals_per_match,
               avg((r.goals_home - coalesce(r.et_goals_home, 0)) - (r.goals_away - coalesce(r.et_goals_away, 0)))
                   AS home_goal_difference,
               avg(r.btts::int) AS btts, avg((r.total_goals > 2.5)::int) AS over_2_5,
               count(*) FILTER (WHERE fx.has_stats) AS with_team_stats,
               count(*) FILTER (WHERE fx.has_hist) AS with_historical_odds,
               count(*) FILTER (WHERE fx.has_snap) AS with_odds_snapshots,
               count(*) FILTER (WHERE fx.has_features) AS with_features,
               count(*) FILTER (WHERE fx.has_pred) AS with_predictions
        FROM fx
        JOIN core.competitions c ON c.id = fx.competition_id
        LEFT JOIN core.fixture_results r ON r.fixture_id = fx.id
        GROUP BY c.id, c.name, c.country, c.competition_type, fx.season
        ORDER BY c.competition_type DESC, c.name, fx.season DESC
    """, {"fv": feature_version})


def coverage(conn: Conn, feature_version: str) -> list[Row]:
    return fetch_all(conn, FIXTURE_FLAGS + """
        SELECT c.id AS competition_id, c.name AS competition, fx.season, count(*) AS fixtures,
               count(*) FILTER (WHERE fx.status_group = 'finished') AS finished,
               count(*) FILTER (WHERE fx.has_result) AS with_result,
               count(*) FILTER (WHERE fx.has_stats) AS with_team_stats,
               count(*) FILTER (WHERE fx.has_events) AS with_events,
               count(*) FILTER (WHERE fx.has_lineups) AS with_lineups,
               count(*) FILTER (WHERE fx.has_players) AS with_player_stats,
               count(*) FILTER (WHERE fx.has_hist) AS with_historical_odds,
               count(*) FILTER (WHERE fx.has_snap) AS with_odds_snapshots,
               count(*) FILTER (WHERE fx.has_features) AS with_features,
               count(*) FILTER (WHERE fx.has_pred) AS with_predictions
        FROM fx JOIN core.competitions c ON c.id = fx.competition_id
        GROUP BY c.id, c.name, fx.season ORDER BY c.name, fx.season DESC
    """, {"fv": feature_version})


def team(conn: Conn, team_id: int) -> Row | None:
    return fetch_one(conn, "SELECT id, name, provider_team_id FROM core.teams WHERE id = %s", (team_id,))


def team_results(conn: Conn, team_id: int) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT f.home_team_id = %(t)s AS at_home,
               CASE WHEN f.home_team_id = %(t)s THEN r.goals_home - coalesce(r.et_goals_home, 0)
                    ELSE r.goals_away - coalesce(r.et_goals_away, 0) END AS gf,
               CASE WHEN f.home_team_id = %(t)s THEN r.goals_away - coalesce(r.et_goals_away, 0)
                    ELSE r.goals_home - coalesce(r.et_goals_home, 0) END AS ga
        FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
        WHERE %(t)s IN (f.home_team_id, f.away_team_id)
        """,
        {"t": team_id},
    )


def team_elo(conn: Conn, team_id: int) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT DISTINCT ON (e.fixture_id) e.fixture_id, e.kickoff_at, c.name AS competition,
               f.home_team_id = %(t)s AS at_home,
               o.id AS opponent_id, o.name AS opponent_name, o.provider_team_id AS opponent_provider_id,
               e.rating_before, e.rating_after, e.expected_score, e.actual_score
        FROM features.elo_ratings e
        JOIN core.fixtures f ON f.id = e.fixture_id
        JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
        JOIN core.competitions c ON c.id = cs.competition_id
        JOIN core.teams o ON o.id = CASE WHEN f.home_team_id = %(t)s THEN f.away_team_id ELSE f.home_team_id END
        WHERE e.team_id = %(t)s
        ORDER BY e.fixture_id, e.computed_at DESC
        """,
        {"t": team_id},
    )


def team_process(conn: Conn, team_id: int) -> list[Row]:
    """Per fixture, the preferred source that has both sides (API-Football over Football-Data)."""
    return fetch_all(
        conn,
        """
        SELECT DISTINCT ON (f.id) f.id AS fixture_id, f.kickoff_at, mine.source,
               mine.shots AS shots_for, theirs.shots AS shots_against,
               mine.shots_on_target AS shots_on_target_for, theirs.shots_on_target AS shots_on_target_against
        FROM core.fixtures f
        JOIN core.fixture_team_stats mine ON mine.fixture_id = f.id
             AND mine.team_side = CASE WHEN f.home_team_id = %(t)s THEN 'home' ELSE 'away' END
        JOIN core.fixture_team_stats theirs ON theirs.fixture_id = f.id AND theirs.source = mine.source
             AND theirs.team_side <> mine.team_side
        WHERE %(t)s IN (f.home_team_id, f.away_team_id)
        ORDER BY f.id, (mine.source = 'api-football') DESC
        """,
        {"t": team_id},
    )


def team_latest_features(conn: Conn, team_id: int, feature_version: str) -> Row | None:
    return fetch_one(
        conn,
        """
        SELECT s.id, s.fixture_id, s.feature_version, s.data_cutoff,
               CASE WHEN f.home_team_id = %(t)s THEN 'home' ELSE 'away' END AS side,
               (SELECT jsonb_object_agg(ff.name, ff.value) FROM features.fixture_features ff
                WHERE ff.feature_set_id = s.id) AS vals
        FROM features.feature_sets s JOIN core.fixtures f ON f.id = s.fixture_id
        WHERE %(t)s IN (f.home_team_id, f.away_team_id) AND s.feature_version = %(fv)s
        ORDER BY s.data_cutoff DESC, s.n_inputs DESC, s.id DESC LIMIT 1
        """,
        {"t": team_id, "fv": feature_version},
    )


def market_probabilities(conn: Conn, bookmaker: str, kind: str, method: str) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT b.p_home, b.p_draw, b.p_away, r.outcome_1x2 FROM analytics.market_baseline b "
        "JOIN core.fixture_results r ON r.fixture_id = b.fixture_id "
        "WHERE b.market_key = '1X2' AND b.bookmaker_code = %s AND b.price_kind = %s AND b.devig_method = %s",
        (bookmaker, kind, method),
    )


def market_by_season(conn: Conn, bookmaker: str, method: str) -> list[Row]:
    return fetch_all(
        conn,
        """
        WITH scored AS (
            SELECT cs.competition_id, cs.season, b.price_kind, b.overround,
                   -ln(greatest(CASE r.outcome_1x2 WHEN 'Home' THEN b.p_home WHEN 'Draw' THEN b.p_draw
                                     ELSE b.p_away END, 1e-15)) AS loss, b.fixture_id
            FROM analytics.market_baseline b
            JOIN core.fixture_results r ON r.fixture_id = b.fixture_id
            JOIN core.fixtures f ON f.id = b.fixture_id
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            WHERE b.market_key = '1X2' AND b.bookmaker_code = %(bm)s AND b.devig_method = %(m)s
        ), both_kinds AS (
            SELECT fixture_id FROM scored GROUP BY fixture_id HAVING count(DISTINCT price_kind) = 2
        )
        SELECT s.competition_id, c.name AS competition, s.season, count(*) FILTER (WHERE s.price_kind = 'closing') AS n,
               avg(s.loss) FILTER (WHERE s.price_kind = 'closing') AS closing_logloss,
               avg(s.loss) FILTER (WHERE s.price_kind = 'pre_closing') AS pre_closing_logloss,
               avg(s.overround) FILTER (WHERE s.price_kind = 'closing') AS mean_overround_closing
        FROM scored s JOIN both_kinds k ON k.fixture_id = s.fixture_id
        JOIN core.competitions c ON c.id = s.competition_id
        GROUP BY s.competition_id, c.name, s.season ORDER BY c.name, s.season DESC
        """,
        {"bm": bookmaker, "m": method},
    )


def experiments(conn: Conn) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT id, experiment_uuid::text AS uuid, name, model_family, research_status, gate, metrics, "
        "reproduced_from, backtest_session_id, code_version, dataset_hash, feature_version, test_from, test_to, "
        "finished_at FROM analytics.experiments WHERE status = 'completed' ORDER BY id DESC",
    )


def reproductions(conn: Conn) -> dict[int, int]:
    rows = fetch_all(conn, "SELECT reproduced_from, id FROM analytics.experiments WHERE reproduced_from IS NOT NULL "
                           "AND (metrics->'reproduction'->>'identical')::boolean ORDER BY id")
    return {int(r["reproduced_from"]): int(r["id"]) for r in rows}


def migration_plan(conn: Conn) -> Row | None:
    return fetch_one(conn, "SELECT id, name, created_at, summary FROM raw.migration_plans ORDER BY id DESC LIMIT 1")


def migration_units(conn: Conn) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT kind, status, coalesce(tier, 0) AS tier, count(*) AS units, coalesce(sum(requests_spent), 0) AS spent, "
        "coalesce(sum(rows_written), 0) AS rows, max(greatest(started_at, completed_at, updated_at)) AS last_at "
        "FROM raw.backfill_tasks GROUP BY kind, status, coalesce(tier, 0)",
    )
