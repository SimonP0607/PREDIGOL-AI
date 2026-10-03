"""A scored session is stored whole, traceably, and the schema refuses a
comparison or an interval that says more than the numbers do."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.backtesting.data import BacktestData, MarketTriplet
from fbi.backtesting.evaluate import BET_PRICE_KEY, PRIMARY_BASELINE, evaluate_session
from fbi.backtesting.persist import (
    VersionConflictError,
    config_hash,
    config_json,
    ensure_model_version,
    find_completed_session,
    store_session,
)
from fbi.backtesting.walkforward import ModelRun, Prediction, PredRow, WalkForwardConfig
from fbi.features.data import MatchRecord
from fbi.models.scoring import MARKET_ROWS
from tests.integration.conftest import Seed
from tests.integration.helpers import must_be_accepted, must_be_rejected, scalar
from tests.integration.signed_in import SAME_SITE, signed_in

KO = datetime(2025, 3, 1, 15, 0, tzinfo=UTC)
SCORES = [(2, 1), (0, 0), (1, 3), (1, 1), (4, 0), (0, 2)]


@pytest.fixture()
def league(db: psycopg.Connection, seed: Seed) -> Iterator[list[MatchRecord]]:
    """Six finished fixtures between the seed's two teams."""
    records: list[MatchRecord] = []
    with db.cursor() as cur:
        cur.execute("INSERT INTO market.markets (key,name,n_outcomes,has_line,is_exclusive) VALUES "
                    "('OU','Over/Under',2,true,true),('BTTS','Both teams to score',2,false,true) "
                    "ON CONFLICT DO NOTHING RETURNING key")
        added_markets = [r[0] for r in cur.fetchall()]
        for i, (gh, ga) in enumerate(SCORES):
            ko = KO + timedelta(days=7 * i)
            home, away = (seed.home_team_id, seed.away_team_id) if i % 2 == 0 else (seed.away_team_id, seed.home_team_id)
            cur.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_short, status_group) VALUES (%s,%s,%s,%s,%s,'FT','finished') RETURNING id",
                (77000 + i, seed.season_id, home, away, ko),
            )
            fid = scalar(cur)
            records.append(MatchRecord(fid, ko, seed.competition_id, "domestic_league", 2024, home, away, gh, ga,
                                       False, "finished"))
    db.commit()
    yield records
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM analytics.backtest_sessions")
        cur.execute("DELETE FROM models.predictions WHERE backtest_session_id IS NULL AND model_version_id <> %s",
                    (seed.model_version_id,))
        cur.execute("DELETE FROM models.model_versions WHERE id <> %s", (seed.model_version_id,))
        cur.execute("DELETE FROM models.model_registry WHERE name <> 'dixon_coles'")
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 77000 AND 77999")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'backtest'")
        cur.execute("DELETE FROM market.markets WHERE key = ANY(%s)", (added_markets,))
    db.commit()


def _run(matches: list[MatchRecord], model: str, sharp: float) -> ModelRun:
    run = ModelRun(model, "test")
    for m in matches:
        y = 0 if (m.goals_home or 0) > (m.goals_away or 0) else 1 if m.goals_home == m.goals_away else 2
        p = [(1 - sharp) / 2] * 3
        p[y] = sharp
        rows = tuple(PredRow(mk, sel, line, p[k] if k < 3 else 0.5, None, None) for k, (mk, sel, line)
                     in enumerate(MARKET_ROWS))
        run.predictions[m.fixture_id] = Prediction(m.fixture_id, model, m.kickoff_at - timedelta(hours=1),
                                                   (p[0], p[1], p[2]), rows, "train-hash", 120)
    run.note_training([replace_ko(m, days=-60) for m in matches])
    return run


def replace_ko(m: MatchRecord, *, days: int) -> MatchRecord:
    from dataclasses import replace

    return replace(m, kickoff_at=m.kickoff_at + timedelta(days=days))


def _data(matches: list[MatchRecord]) -> BacktestData:
    market = {m.fixture_id: MarketTriplet(0.45, 0.27, 0.28, 1.025) for m in matches}
    prices = {m.fixture_id: {"Home": 2.1, "Draw": 3.5, "Away": 3.4} for m in matches}
    return BacktestData(matches, {}, {}, {}, {PRIMARY_BASELINE: market}, {BET_PRICE_KEY: prices})


def test_a_session_is_stored_whole_and_found_again(db: psycopg.Connection, league: list[MatchRecord]) -> None:
    data = _data(league)
    runs = [_run(league, "poisson", 0.6), _run(league, "elo_ologit", 0.4)]
    evaluation = evaluate_session(data, league, runs)
    cfg = WalkForwardConfig(competition_ids=(league[0].competition_id,))
    hypers: dict[str, dict[str, object]] = {"poisson": {"xi": 0.002}, "elo_ologit": {"elo": "v2"}}
    h = config_hash({"cfg": config_json(cfg), "hypers": hypers})
    session_id = store_session(db, name="test-session", cfg=cfg, data=data, evaluation=evaluation,
                               selection={"poisson": {"chosen": {"xi": 0.002}}}, hypers=hypers,
                               code_version="abc1234def", cfg_hash=h)
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT status, n_targets, primary_baseline FROM analytics.backtest_sessions WHERE id = %s",
                    (session_id,))
        assert cur.fetchone() == ("completed", len(league), PRIMARY_BASELINE)
        cur.execute("SELECT count(*) FROM analytics.backtest_runs WHERE session_id = %s", (session_id,))
        assert scalar(cur) == 2
        cur.execute("SELECT count(*) FROM analytics.baseline_evaluations WHERE session_id = %s", (session_id,))
        assert scalar(cur) == 1
        cur.execute(
            "SELECT r.name, c.verdict, c.n_common FROM analytics.backtest_comparisons c "
            "JOIN analytics.backtest_runs r ON r.id = c.backtest_run_id WHERE r.session_id = %s ORDER BY r.name",
            (session_id,))
        rows = cur.fetchall()
        assert [r[2] for r in rows] == [len(league)] * 2
        cur.execute("SELECT count(*), count(*) FILTER (WHERE p_lo IS NULL) FROM models.predictions "
                    "WHERE backtest_session_id = %s", (session_id,))
        total, no_interval = cur.fetchone() or (0, 0)
        assert total == 2 * len(league) * len(MARKET_ROWS) and no_interval == total, "no interval is NULL, not zero"
        cur.execute(
            "SELECT count(*), sum(p_actual) FROM analytics.backtest_samples s JOIN analytics.backtest_runs r "
            "ON r.id = s.backtest_run_id WHERE r.session_id = %s AND s.market_key = '1X2'", (session_id,))
        n, happened = cur.fetchone() or (0, 0)
        assert n == 2 * 3 * len(league) and happened == 2 * len(league), "exactly one 1X2 outcome per fixture"
        cur.execute("SELECT data_cutoff_ts < f.kickoff_at FROM models.predictions p JOIN core.fixtures f "
                    "ON f.id = p.fixture_id WHERE backtest_session_id = %s", (session_id,))
        assert all(r[0] for r in cur.fetchall())
    assert find_completed_session(db, name="test-session", dataset_hash=evaluation.dataset_hash,
                                  code_version="abc1234def", cfg_hash=h) == session_id
    assert find_completed_session(db, name="test-session", dataset_hash="other", code_version="abc1234def",
                                  cfg_hash=h) is None


def test_a_model_version_is_immutable(db: psycopg.Connection, league: list[MatchRecord]) -> None:
    run = _run(league, "poisson", 0.6)
    first = ensure_model_version(db, run, hyper={"xi": 0.002}, code_version="abc1234", feature_names=[])
    assert ensure_model_version(db, run, hyper={"xi": 0.002}, code_version="abc1234", feature_names=[]) == first
    with pytest.raises(VersionConflictError):
        ensure_model_version(db, run, hyper={"xi": 0.004}, code_version="abc1234", feature_names=[])


def test_the_schema_refuses_a_verdict_its_interval_does_not_support(db: psycopg.Connection, seed: Seed) -> None:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO analytics.backtest_sessions (name, protocol, competition_ids, test_season, test_from, "
            "test_to, primary_baseline, n_targets, dataset_hash, code_version) VALUES "
            "('s','walk_forward','{1}',2024,'2024-08-01','2025-05-31','pinnacle/closing/shin',10,'h','c') RETURNING id")
        session_id = scalar(cur)
        cur.execute(
            "INSERT INTO analytics.backtest_runs (name, model_version_id, competition_ids, test_from, test_to, "
            "protocol, train_window, code_version, dataset_hash, n_samples, accuracy_pct, brier_score, logloss, ece, "
            "session_id) VALUES ('r',%s,'{1}','2024-08-01','2025-05-31','walk_forward','w','c','h',10,50,0.6,1.0,"
            "0.01,%s) RETURNING id", (seed.model_version_id, session_id))
        run_id = scalar(cur)
    insert = ("INSERT INTO analytics.backtest_comparisons (backtest_run_id, baseline_key, market_key, n_common, "
              "model_logloss, baseline_logloss, logloss_diff, logloss_diff_ci_low, logloss_diff_ci_high, model_brier, "
              "baseline_brier, brier_diff, brier_diff_ci_low, brier_diff_ci_high, verdict) VALUES "
              "(%s,'m','1X2',10,1.0,0.99,%s,%s,%s,0.6,0.59,0.01,0.0,0.02,%s)")
    with must_be_rejected(db, "'better' with an interval that crosses zero") as cur:
        cur.execute(insert, (run_id, -0.01, -0.02, 0.005, "better"))
    with must_be_rejected(db, "'indistinguishable' with an interval entirely above zero") as cur:
        cur.execute(insert, (run_id, 0.01, 0.005, 0.02, "indistinguishable"))
    with must_be_rejected(db, "a mean outside its own interval") as cur:
        cur.execute(insert, (run_id, 0.05, 0.005, 0.02, "worse"))
    with must_be_accepted(db) as cur:
        cur.execute(insert, (run_id, 0.01, 0.005, 0.02, "worse"))
    db.rollback()


def test_an_interval_is_both_bounds_or_none(db: psycopg.Connection, seed: Seed) -> None:
    insert = ("INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, p_raw, "
              "p_calibrated, p_lo, p_hi, feature_set_hash, data_cutoff_ts) VALUES "
              "(%s,%s,'1X2','Home',0.5,0.5,%s,%s,'h','2026-09-15 18:00Z')")
    with must_be_rejected(db, "a lower bound without an upper one") as cur:
        cur.execute(insert, (seed.fixture_id, seed.model_version_id, 0.4, None))
    with must_be_rejected(db, "a point outside its interval") as cur:
        cur.execute(insert, (seed.fixture_id, seed.model_version_id, 0.55, 0.6))
    with must_be_accepted(db) as cur:
        cur.execute(insert, (seed.fixture_id, seed.model_version_id, None, None))


def test_the_models_endpoint_shows_the_market_first_and_labels_betting_hypothetical(
    db: psycopg.Connection, league: list[MatchRecord], migrated_database: str
) -> None:
    from fastapi.testclient import TestClient

    from fbi.core.config import reset_cache

    data = _data(league)
    evaluation = evaluate_session(data, league, [_run(league, "poisson", 0.6)])
    cfg = WalkForwardConfig(competition_ids=(league[0].competition_id,))
    hypers: dict[str, dict[str, object]] = {"poisson": {"xi": 0.002}}
    store_session(db, name="api-session", cfg=cfg, data=data, evaluation=evaluation, selection={}, hypers=hypers,
                  code_version="feedbeef", cfg_hash="x")
    db.commit()
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    try:
        from fbi.api.app import create_app

        with TestClient(signed_in(create_app()), headers=SAME_SITE) as client:
            body = client.get("/api/v1/admin/models").json()
    finally:
        mp.undo()
        reset_cache()
    d = body["data"]
    assert d["backtest"]["status"] == "ok" and d["backtest"]["data"]["name"] == "api-session"
    baselines = d["historical_baselines"]["data"]
    assert [b["baseline_key"] for b in baselines if b["is_primary"]] == [PRIMARY_BASELINE]
    assert all(b["price_kind"] == "closing" for b in baselines)
    poisson = next(m for m in d["models"]["data"] if m["name"] == "poisson")
    bt = poisson["latest_backtest"]
    assert bt["primary"]["baseline_key"] == PRIMARY_BASELINE and bt["primary"]["n_common"] == len(league)
    assert bt["betting"]["hypothetical"] is True and "Hypothetical" in bt["betting"]["note"]
    assert bt["coverage"]["predicted"] == len(league)
    assert d["market_baseline"]["status"] == "insufficient_data", "the live consensus still needs captured odds"


def test_historical_prices_reach_the_match_and_the_market_pages_labelled_as_a_second_source(
    db: psycopg.Connection, league: list[MatchRecord], migrated_database: str, seed: Seed
) -> None:
    from decimal import Decimal

    from fastapi.testclient import TestClient

    from fbi.core.config import reset_cache
    from fbi.market.baseline import baseline_from_prices, write_baseline

    target = league[0]
    prices = {("pinnacle", "pre_closing"): ("2.05", "3.50", "3.80"), ("pinnacle", "closing"): ("1.95", "3.60", "4.10"),
              ("MAX", "closing"): ("2.02", "3.75", "4.30")}
    with db.cursor() as cur:
        for (bm, kind), trio in prices.items():
            for sel, odd in zip(("Home", "Draw", "Away"), trio, strict=True):
                cur.execute(
                    "INSERT INTO market.historical_odds (fixture_id, source, bookmaker_code, market_key, selection, "
                    "line, price_kind, odds_decimal, source_payload_hash) VALUES (%s,'football-data.co.uk',%s,'1X2',"
                    "%s,0,%s,%s,%s)", (target.fixture_id, bm, sel, kind, odd, seed.payload_hash))
            if bm != "MAX":
                write_baseline(db, baseline_from_prices(target.fixture_id, "football-data.co.uk", bm, kind,
                                                        *(Decimal(x) for x in trio)))
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s,%s,%s) "
                    "ON CONFLICT DO NOTHING", (target.fixture_id, target.goals_home, target.goals_away))
    evaluation = evaluate_session(_data(league), league, [_run(league, "poisson", 0.6)])
    store_session(db, name="hist", cfg=WalkForwardConfig(competition_ids=(target.competition_id,)), data=_data(league),
                  evaluation=evaluation, selection={}, hypers={"poisson": {"xi": 0.0}}, code_version="c0ffee",
                  cfg_hash="y")
    db.commit()
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    try:
        from fbi.api.app import create_app

        with TestClient(signed_in(create_app()), headers=SAME_SITE) as client:
            odds = client.get(f"/api/v1/odds/fixtures/{target.fixture_id}").json()["data"]
            intel = client.get("/api/v1/admin/odds/intelligence").json()
            match = client.get(f"/api/v1/admin/matches/{target.fixture_id}").json()["data"]
    finally:
        mp.undo()
        reset_cache()
    hist = odds["historical"]
    assert hist["status"] == "ok" and "not captured by this platform" in hist["data"]["note"]
    books = {(b["bookmaker_code"], b["price_kind"]): b for b in hist["data"]["books"]}
    assert books[("MAX", "closing")]["is_composite"] and books[("MAX", "closing")]["overround"] is None
    assert Decimal(books[("pinnacle", "closing")]["overround"]) > 1
    assert {f["devig_method"] for f in hist["data"]["fair_1x2"]} == {"proportional", "shin", "power"}
    assert odds["near_close"]["status"] == "empty", "a historical close is not our near-close"
    assert intel["status"] == "ok"
    moves = intel["data"]["movement"]["data"]
    assert len(moves) == 1 and moves[0]["fixtures"] == 1
    kinds = {p["kind"] for p in match["predictions"]["data"]}
    assert kinds == {"backtest"}, "a replay is never shown as a forecast"
