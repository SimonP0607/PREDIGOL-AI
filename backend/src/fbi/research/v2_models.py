"""The research-V2 challengers that need no model of their own in production yet.

``hgb``         gradient-boosted trees (scikit-learn's HistGradientBoostingClassifier) on the
                feature version's every feature - the family that won the 2017 Soccer
                Prediction Challenge (Hubacek et al. 2019), with little gain expected from
                the algorithm alone (Hubacek et al. 2022).
``hgb_market``  the same trees with the market as an input: the de-vigged AVERAGE price
                taken BEFORE the closing line (football-data's pre-closing odds, collected
                a day or more ahead), i.e. what a bettor could see at the forecast's
                cut-off - never the close, which is the benchmark and comes later.

Hyper-parameters are fixed a priori (not tuned on any season): 200 iterations, learning
rate 0.05, 15 leaves, 50 matches per leaf at least, L2 1.0 - a small, heavily regularised
ensemble for ~10,000 rows. Walk-forward like every other family: refitted every
``refit_days`` on results public before the block's cut-off; a feature set is used only
if its cut-off is before kick-off (the store refuses anything else).
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

import numpy as np

from fbi.backtesting.data import BacktestData
from fbi.backtesting.walkforward import (
    ModelRun,
    Prediction,
    PredRow,
    WalkForwardConfig,
    _check_block,
    blocks,
    known_before,
    outcome_index,
    train_hash,
)
from fbi.features.data import MatchRecord
from fbi.features.engine import FEATURE_NAMES, LeakageError

HGB_PARAMS = {"max_iter": 200, "learning_rate": 0.05, "max_leaf_nodes": 15, "min_samples_leaf": 50,
              "l2_regularization": 1.0, "early_stopping": False, "random_state": 29}
MIN_HGB_TRAIN = 1000
MARKET_INPUT = "AVG/pre_closing/shin"
HGB_FEATURES = tuple(n for n in FEATURE_NAMES)


def _row(features: dict[str, float | None], market: tuple[float, float, float] | None) -> list[float]:
    x = [math.nan if features.get(n) is None else float(features[n] or 0.0) for n in HGB_FEATURES]
    if market is not None:
        ph, pd, pa = market
        x += [math.log(ph / pa), math.log(pd / (1.0 - pd))]
    return x


def run_hgb(data: BacktestData, targets: Sequence[MatchRecord], *, cfg: WalkForwardConfig, refit_days: int,
            with_market: bool = False) -> ModelRun:
    from sklearn.ensemble import HistGradientBoostingClassifier

    name = "hgb_market" if with_market else "hgb"
    market = data.market.get(MARKET_INPUT, {}) if with_market else {}

    def mkt(fid: int) -> tuple[float, float, float] | None:
        t = market.get(fid)
        return None if t is None else (t.p_home, t.p_draw, t.p_away)

    domestic = set(cfg.competition_ids)
    labelled = [m for m in data.matches if m.has_result and m.competition_id in domestic
                and m.fixture_id in data.features and (not with_market or mkt(m.fixture_id) is not None)]
    params = ",".join(f"{k}={v}" for k, v in sorted(HGB_PARAMS.items()))
    run = ModelRun(name, f"features={len(HGB_FEATURES)}{'+market:' + MARKET_INPUT if with_market else ''},{params}")
    for cutoff, group in blocks(targets, refit_days, cfg.cutoff_offset):
        train = [m for m in labelled if known_before(m, cutoff)]
        run.blocks.append(_check_block(cutoff, train, group))
        if len(train) < MIN_HGB_TRAIN:
            run.uncovered.extend((m.fixture_id, f"fewer than {MIN_HGB_TRAIN} training matches with features"
                                  + (" and a pre-closing price" if with_market else "")) for m in group)
            continue
        x = np.array([_row(data.features[m.fixture_id], mkt(m.fixture_id)) for m in train])
        y = np.array([outcome_index(m) for m in train])
        # A feature with no value at all in the window (shot statistics before a source
        # covered the league) carries nothing to split on: it is left out of this fit.
        keep = ~np.all(np.isnan(x), axis=0)
        run.fits += 1
        model = HistGradientBoostingClassifier(**HGB_PARAMS)
        model.fit(x[:, keep], y)
        if list(model.classes_) != [0, 1, 2]:
            run.failed_fits += 1
            run.uncovered.extend((m.fixture_id, "a training window without all three outcomes") for m in group)
            continue
        run.note_training(train)
        th = train_hash(train)
        for m in group:
            fv = data.features.get(m.fixture_id)
            feature_cutoff = data.feature_cutoff.get(m.fixture_id)
            if fv is None or feature_cutoff is None:
                run.uncovered.append((m.fixture_id, "no feature set for this fixture"))
                continue
            if feature_cutoff >= m.kickoff_at:
                raise LeakageError(f"feature cut-off after kick-off for fixture {m.fixture_id}")
            price = mkt(m.fixture_id)
            if with_market and price is None:
                run.uncovered.append((m.fixture_id, "no pre-closing price for this fixture"))
                continue
            p = model.predict_proba(np.array([_row(fv, price)])[:, keep])[0]
            probs = (float(p[0]), float(p[1]), float(p[2]))
            rows = tuple(PredRow("1X2", sel, 0.0, probs[k], None, None)
                         for k, sel in enumerate(("Home", "Draw", "Away")))
            run.no_interval += 1
            run.predictions[m.fixture_id] = Prediction(m.fixture_id, name, max(cutoff, feature_cutoff), probs, rows,
                                                       th, len(train))
    return run


ENSEMBLE_MEMBERS: tuple[str, ...] = ("poisson", "dixon_coles", "elo_ologit", "mnlogit", "hgb")
"""The ensemble rung: the models of the ladder that read no market, pooled with equal weights."""


def ensemble_run(runs: Sequence[ModelRun], *, members: tuple[str, ...] = ENSEMBLE_MEMBERS,
                 name: str = "ensemble") -> ModelRun:
    """An equal-weight logarithmic pool of the members' walk-forward forecasts - no fitting of
    its own, so nothing to leak: each member's forecast was made before kick-off, and the pool
    takes the latest member cut-off as its own. Only fixtures every member predicted."""
    by = {r.model: r for r in runs if r.model in members}
    run = ModelRun(name, "equal-weight log pool of " + "+".join(sorted(by)))
    if len(by) < 2:
        return run
    ids = [set(r.predictions) for r in by.values()]
    common = set.intersection(*ids)
    for fid in sorted(set.union(*ids) - common):
        run.uncovered.append((fid, "a member model did not predict this fixture"))
    for fid in sorted(common):
        ps = [by[m].predictions[fid] for m in sorted(by)]
        logp = np.mean([np.log(np.clip(np.array(x.p, dtype=float), 1e-12, 1.0)) for x in ps], axis=0)
        q = np.exp(logp)
        q /= q.sum()
        probs = (float(q[0]), float(q[1]), float(q[2]))
        rows = tuple(PredRow("1X2", sel, 0.0, probs[k], None, None)
                     for k, sel in enumerate(("Home", "Draw", "Away")))
        digest = hashlib.sha256("|".join(sorted(x.input_hash for x in ps)).encode()).hexdigest()
        run.no_interval += 1
        run.predictions[fid] = Prediction(fid, name, max(x.data_cutoff for x in ps), probs, rows, digest,
                                          min(x.n_train for x in ps))
    froms = [r.train_from for r in by.values() if r.train_from is not None]
    tos = [r.train_to for r in by.values() if r.train_to is not None]
    run.train_from = min(froms) if froms else None
    run.train_to = max(tos) if tos else None
    for r in by.values():
        run.train_ids |= r.train_ids
    return run


def validation_targets(data: BacktestData, cfg: WalkForwardConfig) -> list[MatchRecord]:
    return [m for m in data.matches if m.competition_id in cfg.competition_ids
            and m.season == cfg.validation_season and m.has_result]


__all__ = ["ENSEMBLE_MEMBERS", "HGB_FEATURES", "HGB_PARAMS", "MARKET_INPUT", "ensemble_run", "run_hgb",
           "validation_targets"]
