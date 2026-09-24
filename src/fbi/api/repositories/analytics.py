"""Models, backtests, picks and their results."""

from __future__ import annotations

from fbi.api.repositories import Conn, Row, fetch_all, fetch_one


def model_versions(conn: Conn) -> list[Row]:
    """The newest version of every registered model."""
    return fetch_all(conn, """
        SELECT DISTINCT ON (m.id) m.id AS model_id, m.name, m.family, m.description, v.id AS version_id, v.version,
               v.status, v.hyperparameters, v.train_from, v.train_to, v.n_train, v.code_version, v.created_at
        FROM models.model_versions v JOIN models.model_registry m ON m.id = v.model_id
        ORDER BY m.id, v.created_at DESC, v.id DESC
    """)


def latest_backtests(conn: Conn) -> dict[int, Row]:
    rows = fetch_all(conn, """
        SELECT DISTINCT ON (model_version_id) model_version_id, id AS run_id, name, protocol, session_id, test_from,
               test_to, n_samples, brier_score AS brier, logloss, ece, accuracy_pct, odds_source, n_bets,
               total_stake_units, total_profit_units, roi_pct, yield_pct, roi_ci_low, roi_ci_high,
               max_drawdown_units, near_close_lv_mean, code_version, finished_at, details
        FROM analytics.backtest_runs WHERE status = 'completed'
        ORDER BY model_version_id, finished_at DESC NULLS LAST, id DESC
    """)
    return {int(r["model_version_id"]): r for r in rows}


def comparisons(conn: Conn, run_ids: list[int]) -> list[Row]:
    if not run_ids:
        return []
    return fetch_all(conn, """
        SELECT backtest_run_id, baseline_key, market_key, line, n_common, model_logloss, baseline_logloss,
               logloss_diff, logloss_diff_ci_low, logloss_diff_ci_high, model_brier, baseline_brier, brier_diff,
               brier_diff_ci_low, brier_diff_ci_high, verdict
        FROM analytics.backtest_comparisons WHERE backtest_run_id = ANY(%s)
        ORDER BY backtest_run_id, market_key, baseline_logloss
    """, (run_ids,))


def latest_session(conn: Conn) -> Row | None:
    return fetch_one(conn, """
        SELECT id, session_uuid::text AS session_uuid, name, protocol, competition_ids, validation_season,
               test_season, test_from, test_to, n_targets, primary_baseline, dataset_hash, code_version, finished_at,
               selection, config
        FROM analytics.backtest_sessions WHERE status = 'completed'
        ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 1
    """)


def competition_names(conn: Conn, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = fetch_all(conn, "SELECT id, name FROM core.competitions WHERE id = ANY(%s)", (ids,))
    return {int(r["id"]): str(r["name"]) for r in rows}


def baseline_evaluations(conn: Conn, session_id: int) -> list[Row]:
    return fetch_all(conn, """
        SELECT baseline_key, source, bookmaker_code, price_kind, devig_method, market_key, line, n_samples,
               brier_score AS brier, logloss, ece, mean_overround
        FROM analytics.baseline_evaluations WHERE session_id = %s ORDER BY market_key, logloss
    """, (session_id,))


def market_baseline(conn: Conn) -> Row:
    r = fetch_one(conn, """
        SELECT count(DISTINCT fixture_id) AS fixtures_with_consensus,
               COALESCE(array_agg(DISTINCT devig_method) FILTER (WHERE devig_method IS NOT NULL), '{}') AS methods,
               max(as_of) AS last_as_of
        FROM market.market_consensus
    """)
    assert r is not None
    return r


def candidate_counts(conn: Conn) -> dict[str, int]:
    rows = fetch_all(conn, "SELECT decision, count(*) AS n FROM picks.pick_candidates GROUP BY decision")
    return {str(r["decision"]): int(r["n"]) for r in rows}


def pick_counts(conn: Conn) -> dict[str, int]:
    rows = fetch_all(conn, "SELECT mode, count(*) AS n FROM picks.picks GROUP BY mode")
    return {str(r["mode"]): int(r["n"]) for r in rows}


def picks(conn: Conn, *, limit: int, offset: int) -> list[Row]:
    return fetch_all(conn, """
        SELECT p.id, p.fixture_id, th.name || ' v ' || ta.name AS fixture, c.name AS competition, f.kickoff_at,
               p.market_key, p.selection, p.line, p.status, p.mode, m.name AS model, v.version AS model_version,
               p.prediction_id, p.data_cutoff_ts, p.feature_set_hash, p.calibrator_id IS NOT NULL AS calibrated,
               b.name AS bookmaker, p.market_odds, p.odds_captured_at, p.odds_payload_hash,
               p.p_calibrated AS p_model, p.p_calibrated_lo AS p_lo, p.p_calibrated_hi AS p_hi, p.p_market_fair,
               p.consensus_method, p.consensus_as_of, p.fair_odds, p.edge AS probability_edge, p.price_edge, p.ev,
               p.ev_adjusted AS ev_at_lower_bound, p.kelly_fraction, p.stake_units, p.stake_policy,
               p.decision_rule_version, p.code_version, p.qualification,
               COALESCE(pr.result_status, 'pending') AS result_status, pr.profit_units, pr.settled_at,
               pr.settlement_basis, pr.review_reason, p.created_at
        FROM picks.picks p
        JOIN core.fixtures f ON f.id = p.fixture_id
        JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
        JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
        JOIN core.competitions c ON c.id = cs.competition_id
        JOIN models.model_versions v ON v.id = p.model_version_id JOIN models.model_registry m ON m.id = v.model_id
        JOIN market.bookmakers b ON b.id = p.bookmaker_id
        LEFT JOIN picks.pick_results pr ON pr.pick_id = p.id
        ORDER BY p.created_at DESC, p.id DESC LIMIT %s OFFSET %s
    """, (limit, offset))


def pick_events(conn: Conn, pick_ids: list[int]) -> list[Row]:
    if not pick_ids:
        return []
    return fetch_all(conn, "SELECT pick_id, from_status, to_status, at, reason FROM picks.pick_events "
                           "WHERE pick_id = ANY(%s) ORDER BY pick_id, at, id", (pick_ids,))


def recent_candidates(conn: Conn, *, limit: int) -> list[Row]:
    return fetch_all(conn, """
        SELECT pc.id, pc.fixture_id, th.name || ' v ' || ta.name AS fixture, pc.market_key, pc.selection, pc.line,
               m.name AS model, b.name AS bookmaker, pc.market_odds, pc.p_calibrated AS p_model, pc.p_market_fair,
               pc.edge AS probability_edge, pc.ev, pc.decision, pc.rejection_reason, pc.decision_rule_version,
               pc.odds_captured_at, pc.evaluated_at
        FROM picks.pick_candidates pc
        JOIN core.fixtures f ON f.id = pc.fixture_id
        JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
        JOIN models.predictions pd ON pd.id = pc.prediction_id
        JOIN models.model_versions v ON v.id = pd.model_version_id JOIN models.model_registry m ON m.id = v.model_id
        LEFT JOIN market.bookmakers b ON b.id = pc.bookmaker_id
        ORDER BY pc.evaluated_at DESC, pc.id DESC LIMIT %s
    """, (limit,))


def lifecycle(conn: Conn) -> Row:
    r = fetch_one(conn, """
        SELECT (SELECT count(*) FROM picks.pick_candidates) AS candidates,
               (SELECT count(*) FROM picks.pick_candidates WHERE decision = 'rejected') AS rejected,
               (SELECT count(*) FROM picks.picks WHERE status = 'shadow') AS shadow,
               (SELECT count(*) FROM picks.picks WHERE status = 'qualified') AS qualified,
               (SELECT count(*) FROM picks.picks WHERE status = 'published') AS published,
               (SELECT count(*) FROM picks.picks WHERE status = 'settled') AS settled
    """)
    assert r is not None
    return r


def rejection_reasons(conn: Conn) -> dict[str, int]:
    rows = fetch_all(conn, r"""
        SELECT split_part(rejection_reason, ' (observed ', 1) AS reason, count(*) AS n
        FROM picks.pick_candidates WHERE decision = 'rejected' GROUP BY 1 ORDER BY 2 DESC
    """)
    return {str(r["reason"]): int(r["n"]) for r in rows}


def settled_summary(conn: Conn) -> Row:
    r = fetch_one(conn, """
        SELECT count(*) FILTER (WHERE pr.result_status NOT IN ('pending')) AS settled,
               count(*) FILTER (WHERE pr.result_status = 'pending' OR pr.result_status IS NULL) AS pending,
               sum(p.stake_units) FILTER (WHERE pr.result_status NOT IN ('pending','void')) AS staked,
               sum(pr.profit_units) FILTER (WHERE pr.result_status NOT IN ('pending')) AS profit,
               count(*) FILTER (WHERE pr.result_status IN ('win','half_win')) AS wins
        FROM picks.picks p LEFT JOIN picks.pick_results pr ON pr.pick_id = p.id
    """)
    assert r is not None
    return r
