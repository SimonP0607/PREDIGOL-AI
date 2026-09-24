"""Score a walk-forward session: every model, every market baseline, and the difference.

The ranking metrics are proper scoring rules (log loss, Brier) plus calibration
error. Accuracy is computed because the runs table has a column for it, and is
never used to rank: it rewards backing the favourite and says nothing about
whether 60% meant 60%.

Every model-versus-market number is computed on the fixtures BOTH priced, and
the difference carries a paired-bootstrap interval. A model is 'better' than
the market only if that whole interval is below zero.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from numpy.typing import NDArray

from fbi.backtesting.data import BacktestData
from fbi.backtesting.walkforward import ModelRun, outcome_index
from fbi.core.errors import InvalidOddsError
from fbi.domain.market_probability import DevigMethod, devig
from fbi.domain.odds import DecimalOdds
from fbi.features.data import MatchRecord
from fbi.models.metrics import (
    Bucket,
    brier,
    calibration,
    log_loss,
    paired_bootstrap_ci,
    per_match_log_loss,
)

PRIMARY_BASELINE = "pinnacle/closing/shin"
BASELINES_1X2 = (
    "pinnacle/closing/shin",
    "pinnacle/closing/proportional",
    "pinnacle/closing/power",
    "AVG/closing/shin",
    "bet365/closing/shin",
    "pinnacle/pre_closing/shin",
    "AVG/pre_closing/shin",
)
BASELINES_OU = ("pinnacle/closing", "AVG/closing", "pinnacle/pre_closing")
OU_LINE = 2.5

BET_EV_THRESHOLD = 0.05
"""Pre-registered, not tuned: back the single best-EV 1X2 selection of a fixture
when p_model * price - 1 >= 5%. Changing it after seeing results would be
selecting a rule on the test season."""
BET_PRICE_KEY = "pinnacle/closing/1X2"


@dataclass(frozen=True, slots=True)
class Scores:
    n: int
    brier: float
    log_loss: float
    ece: float
    accuracy: float
    buckets: tuple[Bucket, ...]


def score(p: NDArray[np.float64], y: NDArray[np.int64]) -> Scores:
    ece, buckets = calibration(p, y)
    acc = float((p.argmax(axis=1) == y).mean())
    return Scores(len(y), brier(p, y), log_loss(p, y), ece, acc, tuple(buckets))


@dataclass(frozen=True, slots=True)
class Diff:
    mean: float
    lo: float
    hi: float


@dataclass(frozen=True, slots=True)
class Comparison:
    baseline_key: str
    market_key: str
    line: float
    n_common: int
    model: Scores
    baseline: Scores
    logloss_diff: Diff
    brier_diff: Diff

    @property
    def verdict(self) -> str:
        if self.logloss_diff.hi < 0:
            return "better"
        if self.logloss_diff.lo > 0:
            return "worse"
        return "indistinguishable"


def _brier_rows(p: NDArray[np.float64], y: NDArray[np.int64]) -> NDArray[np.float64]:
    return np.asarray(((p - np.eye(p.shape[1])[y]) ** 2).sum(axis=1), dtype=np.float64)


def compare(model_p: dict[int, NDArray[np.float64]], base_p: dict[int, NDArray[np.float64]],
            y: dict[int, int], *, baseline_key: str, market_key: str, line: float,
            only: set[int] | None = None) -> Comparison | None:
    ids = sorted(set(model_p) & set(base_p) & set(y) & (only if only is not None else set(y)))
    if not ids:
        return None
    pm = np.array([model_p[i] for i in ids])
    pb = np.array([base_p[i] for i in ids])
    yy = np.array([y[i] for i in ids])
    ll = paired_bootstrap_ci(per_match_log_loss(pm, yy), per_match_log_loss(pb, yy))
    br = paired_bootstrap_ci(_brier_rows(pm, yy), _brier_rows(pb, yy))
    return Comparison(baseline_key, market_key, line, len(ids), score(pm, yy), score(pb, yy),
                      Diff(ll[0], min(ll[1], ll[0]), max(ll[2], ll[0])),
                      Diff(br[0], min(br[1], br[0]), max(br[2], br[0])))


@dataclass(frozen=True, slots=True)
class Bet:
    fixture_id: int
    selection: str
    odds: float
    p_model: float
    p_market: float | None
    ev: float
    won: bool

    @property
    def profit(self) -> float:
        return self.odds - 1.0 if self.won else -1.0


@dataclass(frozen=True, slots=True)
class BettingSim:
    rule: str
    odds_source: str
    fixtures_priced: int
    bets: tuple[Bet, ...]
    staked: float
    profit: float
    roi_pct: float | None
    roi_ci: tuple[float, float] | None
    max_drawdown: float
    mean_probability_edge: float | None


def simulate_bets(run: ModelRun, data: BacktestData, targets: Sequence[MatchRecord]) -> BettingSim:
    """Flat one-unit bets at Pinnacle's closing price, by the pre-registered rule.

    The model's data cut-off is at least an hour before kick-off, so it never
    knows more than the closing price did; the price itself is the closing
    one, which a bettor can only approximate. Hypothetical, and labelled so.
    """
    fair = data.market.get(PRIMARY_BASELINE, {})
    bets: list[Bet] = []
    priced = 0
    for m in sorted(targets, key=lambda t: (t.kickoff_at, t.fixture_id)):
        pred = run.predictions.get(m.fixture_id)
        prices = data.prices.get(BET_PRICE_KEY, {}).get(m.fixture_id)
        if pred is None or prices is None or not m.has_result or len(prices) < 3:
            continue
        priced += 1
        y = outcome_index(m)
        best: Bet | None = None
        for k, sel in enumerate(("Home", "Draw", "Away")):
            odds = prices[sel]
            ev = pred.p[k] * odds - 1.0
            f = fair.get(m.fixture_id)
            pm = None if f is None else (f.p_home, f.p_draw, f.p_away)[k]
            if best is None or ev > best.ev:
                best = Bet(m.fixture_id, sel, odds, pred.p[k], pm, ev, y == k)
        if best is not None and best.ev >= BET_EV_THRESHOLD:
            bets.append(best)
    staked = float(len(bets))
    profits = np.array([b.profit for b in bets], dtype=np.float64)
    total = float(profits.sum()) if len(bets) else 0.0
    roi = 100.0 * total / staked if staked else None
    ci = None
    if len(bets) >= 30:
        rng = np.random.default_rng(17)
        idx = rng.integers(0, len(bets), size=(2000, len(bets)))
        sims = profits[idx].mean(axis=1) * 100.0
        ci = (float(np.quantile(sims, 0.025)), float(np.quantile(sims, 0.975)))
    curve = np.cumsum(profits) if len(bets) else np.zeros(1)
    drawdown = float((np.maximum.accumulate(np.concatenate([[0.0], curve])) - np.concatenate([[0.0], curve])).max())
    edges = [b.p_model - b.p_market for b in bets if b.p_market is not None]
    return BettingSim(
        rule=f"back the best-EV 1X2 selection when p_model * price - 1 >= {BET_EV_THRESHOLD:.0%}; flat 1 unit",
        odds_source=f"{data.price_source}:{BET_PRICE_KEY}",
        fixtures_priced=priced, bets=tuple(bets), staked=staked, profit=total, roi_pct=roi, roi_ci=ci,
        max_drawdown=drawdown, mean_probability_edge=float(np.mean(edges)) if edges else None,
    )


@dataclass
class ModelEvaluation:
    run: ModelRun
    n_targets: int
    own: Scores | None
    comparisons: list[Comparison] = field(default_factory=list)
    ou: Scores | None = None
    ou_comparisons: list[Comparison] = field(default_factory=list)
    btts: Scores | None = None
    by_competition: dict[str, dict[str, float]] = field(default_factory=dict)
    """competition id (as text, for JSON) -> scores on the fixtures shared with the primary baseline"""
    by_month: dict[str, dict[str, float]] = field(default_factory=dict)
    betting: BettingSim | None = None

    @property
    def coverage(self) -> dict[str, object]:
        reasons: dict[str, int] = defaultdict(int)
        for _, why in self.run.uncovered:
            reasons[why] += 1
        return {"targets": self.n_targets, "predicted": len(self.run.predictions), "uncovered": dict(reasons),
                "fits": self.run.fits, "failed_fits": self.run.failed_fits, "no_interval": self.run.no_interval}

    def primary(self) -> Comparison | None:
        return next((c for c in self.comparisons if c.baseline_key == PRIMARY_BASELINE), None)


@dataclass(frozen=True, slots=True)
class BaselineEvaluation:
    key: str
    market_key: str
    line: float
    scores: Scores
    mean_overround: float | None

    @property
    def parts(self) -> tuple[str, str, str]:
        bm, kind, method = self.key.split("/")
        return bm, kind, method


@dataclass
class SessionEvaluation:
    targets: list[MatchRecord]
    baselines: list[BaselineEvaluation]
    models: list[ModelEvaluation]
    common_ids: list[int]
    common_scores: dict[str, Scores]
    dataset_hash: str


def _ou_fair(data: BacktestData, key: str) -> dict[int, NDArray[np.float64]]:
    out: dict[int, NDArray[np.float64]] = {}
    for fid, sel in data.prices.get(f"{key}/OU{OU_LINE:g}", {}).items():
        if "Over" not in sel or "Under" not in sel:
            continue
        try:
            fair = devig({"Over": DecimalOdds.parse(sel["Over"]), "Under": DecimalOdds.parse(sel["Under"])},
                         DevigMethod.SHIN)
        except (InvalidOddsError, ValueError):
            continue
        out[fid] = np.array([fair["Over"].probability.value, fair["Under"].probability.value])
    return out


def dataset_hash(targets: Sequence[MatchRecord], data: BacktestData) -> str:
    d = hashlib.sha256()
    base = data.market.get(PRIMARY_BASELINE, {})
    for m in sorted(targets, key=lambda t: t.fixture_id):
        b = base.get(m.fixture_id)
        d.update(f"{m.fixture_id}|{m.kickoff_at.isoformat()}|{m.goals_home}-{m.goals_away}|".encode())
        if b is not None:
            d.update(f"{b.p_home:.6f},{b.p_draw:.6f},{b.p_away:.6f}".encode())
        d.update(b";")
    return d.hexdigest()


def evaluate_session(data: BacktestData, targets: Sequence[MatchRecord], runs: Sequence[ModelRun]) -> SessionEvaluation:
    scored = [m for m in targets if m.has_result]
    y = {m.fixture_id: outcome_index(m) for m in scored}
    by_id = {m.fixture_id: m for m in scored}
    y_ou = {m.fixture_id: 0 if (m.goals_home or 0) + (m.goals_away or 0) > OU_LINE else 1 for m in scored}
    y_btts = {m.fixture_id: 0 if (m.goals_home or 0) > 0 and (m.goals_away or 0) > 0 else 1 for m in scored}

    base_1x2: dict[str, dict[int, NDArray[np.float64]]] = {}
    baselines: list[BaselineEvaluation] = []
    for key in BASELINES_1X2:
        trip = data.market.get(key, {})
        probs = {fid: np.array([t.p_home, t.p_draw, t.p_away]) for fid, t in trip.items() if fid in y}
        base_1x2[key] = probs
        if probs:
            ids = sorted(probs)
            baselines.append(BaselineEvaluation(
                key, "1X2", 0.0, score(np.array([probs[i] for i in ids]), np.array([y[i] for i in ids])),
                float(np.mean([trip[i].overround for i in ids]))))
    base_ou: dict[str, dict[int, NDArray[np.float64]]] = {}
    for key in BASELINES_OU:
        probs = {fid: p for fid, p in _ou_fair(data, key).items() if fid in y_ou}
        base_ou[key] = probs
        if probs:
            ids = sorted(probs)
            baselines.append(BaselineEvaluation(
                f"{key}/shin", "OU", OU_LINE,
                score(np.array([probs[i] for i in ids]), np.array([y_ou[i] for i in ids])), None))

    evaluations: list[ModelEvaluation] = []
    for run in runs:
        p1 = {fid: np.array(pr.p) for fid, pr in run.predictions.items() if fid in y}
        ids = sorted(p1)
        ev = ModelEvaluation(run, len(scored),
                             score(np.array([p1[i] for i in ids]), np.array([y[i] for i in ids])) if ids else None)
        for key in BASELINES_1X2:
            c = compare(p1, base_1x2[key], y, baseline_key=key, market_key="1X2", line=0.0)
            if c is not None:
                ev.comparisons.append(c)
        rows = {fid: {(r.market_key, r.selection): r.p for r in pr.rows} for fid, pr in run.predictions.items()}
        pou = {fid: np.array([r[("OU", "Over")], r[("OU", "Under")]]) for fid, r in rows.items()
               if ("OU", "Over") in r and fid in y_ou}
        if pou:
            ids_ou = sorted(pou)
            ev.ou = score(np.array([pou[i] for i in ids_ou]), np.array([y_ou[i] for i in ids_ou]))
            for key in BASELINES_OU:
                c = compare(pou, base_ou[key], y_ou, baseline_key=f"{key}/shin", market_key="OU", line=OU_LINE)
                if c is not None:
                    ev.ou_comparisons.append(c)
        pbt = {fid: np.array([r[("BTTS", "Yes")], r[("BTTS", "No")]]) for fid, r in rows.items()
               if ("BTTS", "Yes") in r and fid in y_btts}
        if pbt:
            ids_b = sorted(pbt)
            ev.btts = score(np.array([pbt[i] for i in ids_b]), np.array([y_btts[i] for i in ids_b]))
        primary = base_1x2.get(PRIMARY_BASELINE, {})
        groups_c: dict[str, list[int]] = defaultdict(list)
        groups_m: dict[str, list[int]] = defaultdict(list)
        for fid in sorted(set(p1) & set(primary)):
            groups_c[str(by_id[fid].competition_id)].append(fid)
            groups_m[by_id[fid].kickoff_at.strftime("%Y-%m")].append(fid)
        for bucket, groups in ((ev.by_competition, groups_c), (ev.by_month, groups_m)):
            for g, fids in sorted(groups.items()):
                yy = np.array([y[i] for i in fids])
                pm = np.array([p1[i] for i in fids])
                pb = np.array([primary[i] for i in fids])
                bucket[g] = {"n": float(len(fids)), "model_logloss": log_loss(pm, yy),
                             "baseline_logloss": log_loss(pb, yy),
                             "logloss_diff": log_loss(pm, yy) - log_loss(pb, yy),
                             "model_brier": brier(pm, yy), "baseline_brier": brier(pb, yy)}
        ev.betting = simulate_bets(run, data, scored)
        evaluations.append(ev)

    common = set(y) & set(base_1x2.get(PRIMARY_BASELINE, {}))
    for ev in evaluations:
        common &= set(ev.run.predictions)
    common_ids = sorted(common)
    common_scores: dict[str, Scores] = {}
    if common_ids:
        yy = np.array([y[i] for i in common_ids])
        common_scores[PRIMARY_BASELINE] = score(np.array([base_1x2[PRIMARY_BASELINE][i] for i in common_ids]), yy)
        for ev in evaluations:
            common_scores[ev.run.model] = score(np.array([ev.run.predictions[i].p for i in common_ids]), yy)
    return SessionEvaluation(list(scored), baselines, evaluations, common_ids, common_scores,
                             dataset_hash(scored, data))
