"""Models, backtests, picks and their results."""

from __future__ import annotations

from fbi.api.repositories import Conn, Row, fetch_all, fetch_one


def model_versions(conn: Conn) -> list[Row]:
    return fetch_all(conn, """
        SELECT m.id AS model_id, m.name, m.family, m.description, v.id AS version_id, v.version, v.status,
               v.train_from, v.train_to, v.n_train, v.code_version, v.created_at
        FROM models.model_versions v JOIN models.model_registry m ON m.id = v.model_id
        ORDER BY m.family, m.name, v.created_at DESC
    """)


def latest_backtests(conn: Conn) -> dict[int, Row]:
    rows = fetch_all(conn, """
        SELECT DISTINCT ON (model_version_id) model_version_id, id AS run_id, name, protocol, test_from, test_to,
               n_samples, brier_score AS brier, logloss, ece, odds_source, n_bets, roi_pct, yield_pct,
               near_close_lv_mean, code_version, finished_at
        FROM analytics.backtest_runs WHERE status = 'completed'
        ORDER BY model_version_id, finished_at DESC NULLS LAST, id DESC
    """)
    return {int(r["model_version_id"]): r for r in rows}


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
        SELECT p.id, p.fixture_id, p.market_key, p.selection, p.line, p.mode,
               COALESCE(pr.result_status, 'pending') AS status, p.model_version_id, p.decision_rule_version,
               p.market_odds, p.odds_captured_at, p.p_calibrated, p.p_market_fair, p.edge, p.price_edge, p.ev,
               p.stake_units, p.data_cutoff_ts, p.created_at, pr.result_status, pr.profit_units
        FROM picks.picks p LEFT JOIN picks.pick_results pr ON pr.pick_id = p.id
        ORDER BY p.created_at DESC, p.id DESC LIMIT %s OFFSET %s
    """, (limit, offset))


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
