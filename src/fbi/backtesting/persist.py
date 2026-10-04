"""Write a scored walk-forward session to the database.

Everything lands in one transaction: a session is either stored whole or not
at all. Model versions are immutable - the version string carries the
hyper-parameters and the commit, and an existing version whose recorded
hyper-parameters differ is a conflict, not something to overwrite.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.backtesting.data import BacktestData
from fbi.backtesting.evaluate import (
    BET_PRICE_KEY,
    OU_LINE,
    PRIMARY_BASELINE,
    Comparison,
    ModelEvaluation,
    Scores,
    SessionEvaluation,
)
from fbi.backtesting.walkforward import ModelRun, WalkForwardConfig, outcome_index
from fbi.features.engine import FEATURE_NAMES
from fbi.models.families import MNLOGIT_SOURCE_FEATURES

MODEL_SEMVER = "2.0.0"

CATALOGUE: dict[str, tuple[str, str, str]] = {
    # name -> (registry name, family, description)
    "poisson": ("poisson", "goals",
                "Poisson (Maher 1982): home and away goals as independent Poisson counts with one attack and "
                "one defence strength per team; time decay and shrinkage chosen on the validation season."),
    "dixon_coles": ("dixon_coles", "goals",
                    "Dixon-Coles (1997): the Poisson model with a low-score dependence correction rho, "
                    "estimated jointly."),
    "elo_ologit": ("elo_ologit", "rating",
                   "Elo V2 ratings (World Football Elo: K=20, home advantage 65, margin multiplier) mapped to "
                   "1X2 by an ordered logit refitted at every cut-off."),
    "base_rates": ("base_rates", "baseline",
                   "League home/draw/away frequencies over the training window, Laplace-smoothed: the no-skill "
                   "reference."),
    "mnlogit": ("mnlogit", "ml",
                "Multinomial logistic regression (L2 = 1, fixed a priori) on Elo and pi-rating differences, shot and "
                "shot-on-target share differences, Elo-residual form, rest and league home advantage."),
    "hgb": ("hgb", "ml",
            "Gradient-boosted trees (scikit-learn HistGradientBoosting, hyper-parameters fixed a priori) on every "
            "feature of the feature version; refitted monthly, walk-forward."),
    "hgb_market": ("hgb_market", "ml",
                   "The same gradient-boosted trees with the de-vigged average pre-closing price as an input: what "
                   "a bettor could see at the cut-off, never the closing line."),
}


FEATURE_LINEAGE: dict[str, list[str]] = {
    # the feature-set columns a model version reads (models.model_versions.feature_names)
    "elo_ologit": ["elo_diff"],
    "mnlogit": list(MNLOGIT_SOURCE_FEATURES),
    "hgb": list(FEATURE_NAMES),
    "hgb_market": [*FEATURE_NAMES, "market:AVG/pre_closing/shin"],
}


class VersionConflictError(RuntimeError):
    """A model version already exists with different hyper-parameters."""


def scores_json(s: Scores | None) -> dict[str, Any] | None:
    if s is None:
        return None
    return {"n": s.n, "brier": s.brier, "log_loss": s.log_loss, "ece": s.ece, "accuracy": s.accuracy,
            "buckets": [asdict(b) for b in s.buckets]}


def comparison_json(c: Comparison) -> dict[str, Any]:
    return {"baseline": c.baseline_key, "market": c.market_key, "line": c.line, "n_common": c.n_common,
            "model": scores_json(c.model), "baseline_scores": scores_json(c.baseline),
            "logloss_diff": asdict(c.logloss_diff), "brier_diff": asdict(c.brier_diff), "verdict": c.verdict,
            "evidence": c.evidence, "details": c.details()}


def config_json(cfg: WalkForwardConfig) -> dict[str, Any]:
    out = asdict(cfg)
    out["cutoff_offset_minutes"] = int(cfg.cutoff_offset.total_seconds() // 60)
    del out["cutoff_offset"]
    out["competition_ids"] = list(cfg.competition_ids)
    return out


def config_from_json(d: dict[str, Any]) -> WalkForwardConfig:
    """The inverse of config_json: the configuration a stored session or experiment ran with."""
    return WalkForwardConfig(
        competition_ids=tuple(int(x) for x in d["competition_ids"]), test_season=int(d["test_season"]),
        validation_season=int(d["validation_season"]), refit_days=int(d["refit_days"]),
        validation_refit_days=int(d["validation_refit_days"]), history_days=int(d["history_days"]),
        cutoff_offset=timedelta(minutes=int(d["cutoff_offset_minutes"])),
        xi_grid=tuple(float(x) for x in d["xi_grid"]), penalty_grid=tuple(float(x) for x in d["penalty_grid"]),
        interval_draws=int(d["interval_draws"]))


def config_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def find_completed_session(conn: psycopg.Connection, *, name: str, dataset_hash: str, code_version: str,
                           cfg_hash: str) -> int | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT id FROM analytics.backtest_sessions WHERE name = %s AND dataset_hash = %s AND code_version = %s "
            "AND status = 'completed' AND config->>'config_hash' = %s ORDER BY id DESC LIMIT 1",
            (name, dataset_hash, code_version, cfg_hash),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None


def version_string(model: str, spec: str, code_version: str) -> str:
    return f"{MODEL_SEMVER}/{spec}@{code_version[:7]}"


def ensure_version(conn: psycopg.Connection, *, model: str, spec: str, hyper: dict[str, Any], code_version: str,
                   feature_names: Sequence[str], train_from: date, train_to: date, n_train: int) -> int:
    """The id of (model, version), created on first use. A version is immutable:
    the same version string with other hyper-parameters is a conflict."""
    reg_name, family, description = CATALOGUE[model]
    version = version_string(model, spec, code_version)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "INSERT INTO models.model_registry (name, family, description) VALUES (%s, %s, %s) "
            "ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description RETURNING id",
            (reg_name, family, description),
        )
        row = cur.fetchone()
        assert row is not None
        model_id = int(row[0])
        cur.execute("SELECT id, hyperparameters FROM models.model_versions WHERE model_id = %s AND version = %s",
                    (model_id, version))
        existing = cur.fetchone()
        if existing is not None:
            if dict(existing[1]) != hyper:
                raise VersionConflictError(f"{reg_name} {version} exists with other hyper-parameters; bump MODEL_SEMVER")
            return int(existing[0])
        cur.execute(
            "INSERT INTO models.model_versions (model_id, version, hyperparameters, feature_names, train_from, "
            "train_to, n_train, code_version, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'experimental') RETURNING id",
            (model_id, version, json.dumps(hyper), list(feature_names), train_from,
             max(train_to, train_from + timedelta(days=1)), max(n_train, 1), code_version),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def ensure_model_version(conn: psycopg.Connection, run: ModelRun, *, hyper: dict[str, Any], code_version: str,
                         feature_names: Sequence[str]) -> int:
    assert run.train_from is not None and run.train_to is not None
    return ensure_version(conn, model=run.model, spec=run.spec, hyper=hyper, code_version=code_version,
                          feature_names=feature_names, train_from=run.train_from.date(),
                          train_to=run.train_to.date(), n_train=len(run.train_ids))


def goal_hyper(spec_xi: float, spec_penalty: float, cfg: WalkForwardConfig, code_version: str) -> dict[str, Any]:
    from fbi.backtesting.walkforward import MIN_GOAL_TRAIN

    return {"xi": spec_xi, "penalty": spec_penalty, "history_days": cfg.history_days, "min_train": MIN_GOAL_TRAIN,
            "interval": "laplace 90%", "code_version": code_version}


def ologit_hyper(code_version: str) -> dict[str, Any]:
    from fbi.backtesting.walkforward import MIN_OLOGIT_TRAIN
    from fbi.features.engine import FEATURE_VERSION

    return {"elo": "elo-v2.0 K=20 home=65 initial=1500", "feature_version": FEATURE_VERSION,
            "min_train": MIN_OLOGIT_TRAIN, "interval": "laplace 90%", "code_version": code_version}


def base_rates_hyper(cfg: WalkForwardConfig, code_version: str) -> dict[str, Any]:
    from fbi.backtesting.walkforward import MIN_BASE_RATE_TRAIN

    return {"history_days": cfg.history_days, "laplace": 1, "min_train": MIN_BASE_RATE_TRAIN,
            "code_version": code_version}


def mnlogit_hyper(code_version: str) -> dict[str, Any]:
    from fbi.backtesting.walkforward import MIN_MNLOGIT_TRAIN, MNLOGIT_L2
    from fbi.features.engine import FEATURE_VERSION
    from fbi.models.families import MNLOGIT_FEATURES

    return {"features": list(MNLOGIT_FEATURES), "l2": MNLOGIT_L2, "feature_version": FEATURE_VERSION,
            "min_train": MIN_MNLOGIT_TRAIN, "imputation": "training mean", "code_version": code_version}


def hgb_hyper(code_version: str, *, with_market: bool) -> dict[str, Any]:
    from fbi.features.engine import FEATURE_VERSION
    from fbi.research.v2_models import HGB_PARAMS, MARKET_INPUT, MIN_HGB_TRAIN

    return {"params": dict(HGB_PARAMS), "feature_version": FEATURE_VERSION, "min_train": MIN_HGB_TRAIN,
            "market_input": MARKET_INPUT if with_market else None, "refit_days": 30, "code_version": code_version}


def store_session(
    conn: psycopg.Connection,
    *,
    name: str,
    cfg: WalkForwardConfig,
    data: BacktestData,
    evaluation: SessionEvaluation,
    selection: dict[str, Any],
    hypers: dict[str, dict[str, Any]],
    code_version: str,
    cfg_hash: str,
) -> int:
    """Insert the session and everything under it. The caller commits."""
    targets = evaluation.targets
    test_from: date = min(m.kickoff_at for m in targets).date()
    test_to: date = max(m.kickoff_at for m in targets).date()
    cfg_payload = config_json(cfg) | {"config_hash": cfg_hash}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "INSERT INTO analytics.backtest_sessions (name, protocol, competition_ids, validation_season, test_season, "
            "test_from, test_to, config, selection, primary_baseline, n_targets, dataset_hash, code_version) "
            "VALUES (%s,'walk_forward',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (name, list(cfg.competition_ids), cfg.validation_season, cfg.test_season, test_from, test_to,
             json.dumps(cfg_payload), json.dumps(selection), PRIMARY_BASELINE, len(targets),
             evaluation.dataset_hash, code_version),
        )
        row = cur.fetchone()
        assert row is not None
        session_id = int(row[0])

        for b in evaluation.baselines:
            parts = b.key.split("/")
            cur.execute(
                "INSERT INTO analytics.baseline_evaluations (session_id, baseline_key, source, bookmaker_code, "
                "price_kind, devig_method, market_key, line, n_samples, brier_score, logloss, ece, mean_overround, "
                "calibration) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (session_id, b.key, data.price_source, parts[0], parts[1], parts[2], b.market_key, b.line,
                 b.scores.n, round(b.scores.brier, 6), round(b.scores.log_loss, 6), round(b.scores.ece, 6),
                 None if b.mean_overround is None else round(b.mean_overround, 6),
                 json.dumps([asdict(x) for x in b.scores.buckets])),
            )

        for ev in evaluation.models:
            _store_run(cur, session_id=session_id, name=name, cfg=cfg, data=data, ev=ev, evaluation=evaluation,
                       hyper=hypers[ev.run.model], code_version=code_version, conn=conn)

        cur.execute("UPDATE analytics.backtest_sessions SET status = 'completed', finished_at = now() WHERE id = %s",
                    (session_id,))
    return session_id


def _store_run(cur: psycopg.Cursor[Any], *, session_id: int, name: str, cfg: WalkForwardConfig, data: BacktestData,
               ev: ModelEvaluation, evaluation: SessionEvaluation, hyper: dict[str, Any], code_version: str,
               conn: psycopg.Connection) -> None:
    run = ev.run
    if ev.own is None or not run.predictions:
        return
    feature_names = FEATURE_LINEAGE.get(run.model, [])
    version_id = ensure_model_version(conn, run, hyper=hyper, code_version=code_version,
                                      feature_names=feature_names)
    targets = evaluation.targets
    bet = ev.betting
    details = {
        "coverage": ev.coverage,
        "calibration": [asdict(b) for b in ev.own.buckets],
        "comparisons": [comparison_json(c) for c in ev.comparisons],
        "ou": scores_json(ev.ou),
        "ou_comparisons": [comparison_json(c) for c in ev.ou_comparisons],
        "btts": scores_json(ev.btts),
        "by_competition": ev.by_competition,
        "by_month": ev.by_month,
        "common_sample": scores_json(evaluation.common_scores.get(run.model)),
        "betting": None if bet is None else {
            "rule": bet.rule, "fixtures_priced": bet.fixtures_priced,
            "mean_probability_edge": bet.mean_probability_edge, "hypothetical": True,
        },
    }
    roi = None if bet is None or bet.roi_pct is None else round(bet.roi_pct, 4)
    cur.execute(
        "INSERT INTO analytics.backtest_runs (name, model_version_id, competition_ids, test_from, test_to, protocol, "
        "train_window, config, code_version, dataset_hash, n_samples, accuracy_pct, brier_score, logloss, ece, "
        "odds_source, n_bets, total_stake_units, total_profit_units, roi_pct, yield_pct, max_drawdown_units, "
        "roi_ci_low, roi_ci_high, status, finished_at, session_id, details) VALUES "
        "(%s,%s,%s,%s,%s,'walk_forward',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'completed',now(),%s,%s) "
        "RETURNING id",
        (f"{name}:{run.model}", version_id, list(cfg.competition_ids),
         min(m.kickoff_at for m in targets).date(), max(m.kickoff_at for m in targets).date(),
         (f"rolling {cfg.history_days} days, refitted every {cfg.refit_days} day(s), "
          f"cut-off {int(cfg.cutoff_offset.total_seconds() // 60)} min before the block's first kick-off"),
         json.dumps(hyper), code_version, evaluation.dataset_hash, ev.own.n, round(100 * ev.own.accuracy, 3),
         round(ev.own.brier, 6), round(ev.own.log_loss, 6), round(ev.own.ece, 6),
         None if bet is None else bet.odds_source, None if bet is None else len(bet.bets),
         None if bet is None else bet.staked, None if bet is None else round(bet.profit, 4),
         roi if bet is not None and bet.staked > 0 else None, roi if bet is not None and bet.staked > 0 else None,
         None if bet is None else round(bet.max_drawdown, 4),
         None if bet is None or bet.roi_ci is None else round(bet.roi_ci[0], 4),
         None if bet is None or bet.roi_ci is None else round(bet.roi_ci[1], 4),
         session_id, json.dumps(details)),
    )
    row = cur.fetchone()
    assert row is not None
    run_id = int(row[0])

    for c in (*ev.comparisons, *ev.ou_comparisons):
        ll = _ordered(c.logloss_diff.mean, c.logloss_diff.lo, c.logloss_diff.hi)
        cur.execute(
            "INSERT INTO analytics.backtest_comparisons (backtest_run_id, baseline_key, market_key, line, n_common, "
            "model_logloss, baseline_logloss, logloss_diff, logloss_diff_ci_low, logloss_diff_ci_high, model_brier, "
            "baseline_brier, brier_diff, brier_diff_ci_low, brier_diff_ci_high, verdict, details) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (run_id, c.baseline_key, c.market_key, c.line, c.n_common, round(c.model.log_loss, 6),
             round(c.baseline.log_loss, 6), *ll, round(c.model.brier, 6), round(c.baseline.brier, 6),
             *_ordered(c.brier_diff.mean, c.brier_diff.lo, c.brier_diff.hi), verdict(ll[1], ll[2]),
             Json(c.details())),
        )

    fair = data.market.get(PRIMARY_BASELINE, {})
    bets = {b.fixture_id: b for b in (bet.bets if bet else ())}
    by_id = {m.fixture_id: m for m in targets}
    ou_fair_key = "pinnacle/closing"
    samples: list[tuple[Any, ...]] = []
    preds: list[tuple[Any, ...]] = []
    for fid, pr in sorted(run.predictions.items()):
        m = by_id.get(fid)
        if m is None:
            continue
        y = outcome_index(m)
        total = (m.settle_home or 0) + (m.settle_away or 0)
        both = (m.settle_home or 0) > 0 and (m.settle_away or 0) > 0
        f = fair.get(fid)
        for r in pr.rows:
            preds.append((fid, version_id, r.market_key, r.selection, r.line, round(r.p, 6), round(r.p, 6),
                          None if r.lo is None else round(r.lo, 6), None if r.hi is None else round(r.hi, 6),
                          pr.input_hash, pr.data_cutoff, session_id))
            if r.market_key == "1X2":
                k = ("Home", "Draw", "Away").index(r.selection)
                happened = y == k
                p_fair = None if f is None else round((f.p_home, f.p_draw, f.p_away)[k], 6)
                price = data.price(BET_PRICE_KEY, fid, r.selection)
            elif r.market_key == "OU":
                happened = (total > OU_LINE) == (r.selection == "Over")
                p_fair = None
                price = data.price(f"{ou_fair_key}/OU{OU_LINE:g}", fid, r.selection)
            else:
                happened = both == (r.selection == "Yes")
                p_fair = None
                price = None
            b = bets.get(fid)
            was_bet = b is not None and r.market_key == "1X2" and b.selection == r.selection
            samples.append((run_id, fid, r.market_key, r.selection, r.line, round(r.p, 6), p_fair,
                            None if price is None else round(price, 3), was_bet, 1.0 if was_bet else None,
                            happened, 1.0 if happened else 0.0,
                            (round(b.profit, 4) if was_bet and b is not None else None)))
    # A prediction is identified by (fixture, version, market, selection, line,
    # cut-off). The same version at the same cut-off is the same deterministic
    # computation, so an existing row is kept rather than duplicated.
    cur.execute("CREATE TEMP TABLE _bt_predictions (LIKE models.predictions INCLUDING DEFAULTS) ON COMMIT DROP")
    with cur.copy(
        "COPY _bt_predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, p_calibrated, "
        "p_lo, p_hi, feature_set_hash, data_cutoff_ts, backtest_session_id) FROM STDIN"
    ) as copy:
        for p in preds:
            copy.write_row(p)
    cur.execute(
        "INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, "
        "p_calibrated, p_lo, p_hi, feature_set_hash, data_cutoff_ts, backtest_session_id) "
        "SELECT fixture_id, model_version_id, market_key, selection, line, p_raw, p_calibrated, p_lo, p_hi, "
        "feature_set_hash, data_cutoff_ts, backtest_session_id FROM _bt_predictions ON CONFLICT DO NOTHING"
    )
    cur.execute("DROP TABLE _bt_predictions")
    with cur.copy(
        "COPY analytics.backtest_samples (backtest_run_id, fixture_id, market_key, selection, line, p_calibrated, "
        "p_market_fair, market_odds, was_bet, stake_units, outcome_correct, p_actual, profit_units) FROM STDIN"
    ) as copy:
        for s in samples:
            copy.write_row(s)


def verdict(lo: float, hi: float) -> str:
    """From the interval as STORED, so the row always satisfies its own CHECK."""
    if hi < 0:
        return "better"
    if lo > 0:
        return "worse"
    return "indistinguishable"


def _ordered(mean: float, lo: float, hi: float) -> tuple[float, float, float]:
    """Rounded to the column's precision without breaking lo <= mean <= hi."""
    m, low, high = round(mean, 6), round(lo, 6), round(hi, 6)
    return m, min(low, m), max(high, m)
