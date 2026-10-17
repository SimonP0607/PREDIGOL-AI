"""SQL for the Match Center audit trail. Plain rows; the service interprets."""

from __future__ import annotations

from fbi.api.repositories import Conn, Row, fetch_all, fetch_one

PAYLOAD_REFS = """
WITH refs(hash, role) AS (
    SELECT source_payload_hash, 'fixture' FROM core.fixtures WHERE id = %(f)s AND source_payload_hash IS NOT NULL
    UNION ALL SELECT source_payload_hash, 'result' FROM core.fixture_results
        WHERE fixture_id = %(f)s AND source_payload_hash IS NOT NULL
    UNION ALL SELECT payload_hash, 'team_stats:' || source FROM core.fixture_team_stats WHERE fixture_id = %(f)s
    UNION ALL SELECT payload_hash, 'events' FROM core.fixture_events WHERE fixture_id = %(f)s
    UNION ALL SELECT payload_hash, 'lineups' FROM core.fixture_lineups WHERE fixture_id = %(f)s
    UNION ALL SELECT payload_hash, 'player_stats' FROM core.fixture_player_stats WHERE fixture_id = %(f)s
    UNION ALL SELECT payload_hash, 'odds_snapshot' FROM market.odds_snapshots WHERE fixture_id = %(f)s
    UNION ALL SELECT source_payload_hash, 'historical_odds:' || source FROM market.historical_odds
        WHERE fixture_id = %(f)s AND source_payload_hash IS NOT NULL
    UNION ALL SELECT odds_payload_hash, 'pick_candidate_odds' FROM picks.pick_candidates
        WHERE fixture_id = %(f)s AND odds_payload_hash IS NOT NULL
    UNION ALL SELECT r.result_payload_hash, 'settlement' FROM picks.pick_results r JOIN picks.picks p ON p.id = r.pick_id
        WHERE p.fixture_id = %(f)s AND r.result_payload_hash IS NOT NULL
    UNION ALL SELECT payload_hash, 'facts' FROM core.fixture_facts WHERE fixture_id = %(f)s
    UNION ALL SELECT DISTINCT payload_hash, 'player_extras' FROM core.fixture_player_extras WHERE fixture_id = %(f)s
    UNION ALL SELECT payload_hash, 'provider_prediction (auxiliary)' FROM core.provider_predictions
        WHERE fixture_id = %(f)s
    UNION ALL SELECT DISTINCT s.payload_hash, 'standings (newest table of the season)' FROM core.standings s
        JOIN core.fixtures fx ON fx.competition_season_id = s.competition_season_id AND fx.id = %(f)s
        WHERE s.payload_hash IS NOT NULL AND s.snapshot_at = (SELECT max(snapshot_at) FROM core.standings x
                                                               WHERE x.competition_season_id = s.competition_season_id)
)
SELECT r.hash, array_agg(DISTINCT r.role ORDER BY r.role) AS roles, count(*) AS references,
       p.provider, p.endpoint, p.params, p.fetched_at, p.http_status, p.file_path, p.bytes, p.run_id,
       run.job_type, run.status AS run_status
FROM refs r
LEFT JOIN raw.ingestion_payloads p ON p.hash = r.hash
LEFT JOIN raw.ingestion_runs run ON run.id = p.run_id
GROUP BY r.hash, p.provider, p.endpoint, p.params, p.fetched_at, p.http_status, p.file_path, p.bytes, p.run_id,
         run.job_type, run.status
ORDER BY p.fetched_at NULLS LAST, r.hash
"""


def payloads(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(conn, PAYLOAD_REFS, {"f": fixture_id})


def fixture(conn: Conn, fixture_id: int) -> Row | None:
    return fetch_one(
        conn,
        "SELECT f.id, f.provider_fixture_id, f.kickoff_at, f.status_short, f.status_group, f.created_at, f.updated_at, "
        "f.source_payload_hash, f.source_fetched_at, c.name AS competition, cs.season "
        "FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
        "JOIN core.competitions c ON c.id = cs.competition_id WHERE f.id = %s", (fixture_id,))


def result(conn: Conn, fixture_id: int) -> Row | None:
    return fetch_one(conn, "SELECT goals_home, goals_away, reg_goals_home, reg_goals_away, outcome_1x2, "
                           "source_payload_hash, source_fetched_at, settled_at FROM core.fixture_results "
                           "WHERE fixture_id = %s", (fixture_id,))


def detail_counts(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT 'team_stats' AS kind, source, count(*) AS n, max(fetched_at) AS at,
               min(payload_hash) AS payload_hash FROM core.fixture_team_stats WHERE fixture_id = %(f)s GROUP BY source
        UNION ALL SELECT 'events', source, count(*), max(fetched_at), min(payload_hash) FROM core.fixture_events
            WHERE fixture_id = %(f)s GROUP BY source
        UNION ALL SELECT 'lineups', source, count(*), max(fetched_at), min(payload_hash) FROM core.fixture_lineups
            WHERE fixture_id = %(f)s GROUP BY source
        UNION ALL SELECT 'player_stats', source, count(*), max(fetched_at), min(payload_hash)
            FROM core.fixture_player_stats WHERE fixture_id = %(f)s GROUP BY source
        UNION ALL SELECT 'facts', 'api-football', count(*), max(observed_at),
               (array_agg(payload_hash ORDER BY observed_at DESC))[1] FROM core.fixture_facts WHERE fixture_id = %(f)s
            HAVING count(*) > 0
        UNION ALL SELECT 'player_extras', 'api-football', count(*), max(observed_at),
               (array_agg(payload_hash ORDER BY observed_at DESC))[1] FROM core.fixture_player_extras
            WHERE fixture_id = %(f)s HAVING count(*) > 0
        ORDER BY 1, 2
        """,
        {"f": fixture_id},
    )


def feature_sets(conn: Conn, fixture_id: int) -> list[Row]:
    """The newest feature set per version (the one a model would read), and how many exist."""
    return fetch_all(
        conn,
        """
        SELECT DISTINCT ON (feature_version) id, feature_version, data_cutoff, generated_at, code_version, run_id,
               input_hash, n_inputs, newest_input_at,
               count(*) OVER (PARTITION BY feature_version) AS versions_computed
        FROM features.feature_sets WHERE fixture_id = %s
        ORDER BY feature_version, n_inputs DESC, generated_at DESC, id DESC
        """,
        (fixture_id,),
    )


def predictions(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT p.id, p.model_version_id, m.name AS model, m.family, v.version, v.code_version AS model_code_version,
               v.train_from, v.train_to, v.n_train, v.status AS version_status, p.market_key, p.selection, p.line,
               p.p_calibrated, p.p_lo, p.p_hi, p.feature_set_hash, p.data_cutoff_ts, p.backtest_session_id, p.created_at
        FROM models.predictions p
        JOIN models.model_versions v ON v.id = p.model_version_id
        JOIN models.model_registry m ON m.id = v.model_id
        WHERE p.fixture_id = %s
        ORDER BY p.backtest_session_id NULLS FIRST, m.name, p.market_key, p.line, p.selection
        """,
        (fixture_id,),
    )


def experiments(conn: Conn, version_ids: list[int]) -> list[Row]:
    if not version_ids:
        return []
    return fetch_all(
        conn,
        "SELECT id, experiment_uuid::text AS uuid, model_version_id, research_status, (gate->>'passed')::boolean "
        "AS gate_passed, backtest_session_id, code_version, dataset_hash, finished_at FROM analytics.experiments "
        "WHERE model_version_id = ANY(%s) AND reproduced_from IS NULL ORDER BY id",
        (version_ids,),
    )


def odds_summary(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT source, count(*) AS quotes, count(DISTINCT bookmaker_id) AS bookmakers, "
        "count(DISTINCT market_key) AS markets, count(DISTINCT captured_at) AS captures, "
        "count(DISTINCT payload_hash) AS payloads, min(captured_at) AS first_at, max(captured_at) AS last_at, "
        "min(minutes_to_ko) AS closest_minutes_to_ko FROM market.odds_snapshots WHERE fixture_id = %s "
        "GROUP BY source ORDER BY source",
        (fixture_id,),
    )


def near_close(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT source, count(*) AS quotes, count(DISTINCT bookmaker_id) AS bookmakers, max(captured_at) AS last_at, "
        "min(minutes_to_ko) AS closest_minutes_to_ko, bool_or(is_validated_close) AS any_validated_close "
        "FROM market.near_close_snapshots WHERE fixture_id = %s GROUP BY source ORDER BY source",
        (fixture_id,),
    )


def historical_odds(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT source, bookmaker_code, price_kind, count(*) AS quotes, min(source_payload_hash) AS payload_hash "
        "FROM market.historical_odds WHERE fixture_id = %s GROUP BY source, bookmaker_code, price_kind "
        "ORDER BY source, bookmaker_code, price_kind",
        (fixture_id,),
    )


def baselines(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT source, bookmaker_code, price_kind, market_key, devig_method, p_home, p_draw, p_away, overround, "
        "computed_at FROM analytics.market_baseline WHERE fixture_id = %s AND market_key = '1X2' "
        "ORDER BY bookmaker_code, price_kind, devig_method",
        (fixture_id,),
    )


def consensus(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT DISTINCT ON (market_key, selection, line) market_key, selection, line, as_of, devig_method, p_fair, "
        "n_bookmakers, overround FROM market.market_consensus WHERE fixture_id = %s "
        "ORDER BY market_key, selection, line, as_of DESC",
        (fixture_id,),
    )


def candidates(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(
        conn,
        "SELECT id, run_id, prediction_id, market_key, selection, line, market_odds, p_calibrated, p_market_fair, "
        "ev, ev_adjusted, decision, rejection_reason, evaluated_at, decision_rule_version, odds_captured_at, "
        "odds_payload_hash, data_cutoff_ts FROM picks.pick_candidates WHERE fixture_id = %s "
        "ORDER BY evaluated_at DESC, id DESC",
        (fixture_id,),
    )


def picks(conn: Conn, fixture_id: int) -> list[Row]:
    return fetch_all(
        conn,
        """
        SELECT p.id, p.candidate_id, p.prediction_id, p.model_version_id, p.feature_set_hash, p.market_key,
               p.selection, p.line, p.market_odds, p.p_calibrated, p.p_market_fair, p.ev, p.stake_units, p.mode,
               p.status, p.created_at, p.decision_rule_version, p.code_version, p.odds_payload_hash,
               r.result_status, r.profit_units, r.settled_at, r.settled_by, r.settlement_basis, r.rule_version,
               r.result_payload_hash,
               lv.near_close_odds, lv.lv_devigged, lv.is_validated_close, lv.near_close_source
        FROM picks.picks p
        LEFT JOIN picks.pick_results r ON r.pick_id = p.id
        LEFT JOIN picks.pick_line_value lv ON lv.pick_id = p.id
        WHERE p.fixture_id = %s ORDER BY p.created_at, p.id
        """,
        (fixture_id,),
    )
