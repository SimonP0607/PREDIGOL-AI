"""Walk-forward evaluation of a count family (plan F10): was the model any good on matches it had not seen, and better than knowing nothing?

For every competition, in blocks of ``step_days``: fit on the matches already KNOWN at the start of the block (see ``fit.OUTCOME_KNOWN_AFTER``),
predict the matches of the block, move on. Nothing is ever predicted by a model that has seen the match.

Each prediction is compared with the BASELINE of the same competition and the same moment: every team gets the competition's average home and
away count over the training window. A family that does not beat that has learnt nothing about the teams. The dispersion of each (model and
baseline) is measured on the out-of-sample predictions themselves, so neither is flattered by in-sample means.

What this does NOT do: compare with the market. That needs the price history that F1 is still accumulating (the gate of plan F10: at least 300
bets and a CLV that is not negative); the families stay in RESEARCH until it can.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import numpy as np

from fbi.families import referee
from fbi.families.counts import MAX_COUNT, difference_probs, nb_pmf, normalised, over_under
from fbi.families.fit import (
    DAY,
    Dispersion,
    Match,
    NotEnoughHistoryError,
    estimate_dispersion,
    fit_family,
    known_at,
)

DEFAULT_XI = 0.0019
"""Time decay per day (a half-life of about a year), the order of magnitude the goal models use; ``tune`` can choose another on a window
BEFORE the test window."""
DEFAULT_PENALTY = 2.0
BINS = 10


@dataclass(frozen=True, slots=True)
class Row:
    """One out-of-sample prediction and what happened."""
    fixture_id: int
    competition_id: int
    kickoff_at: datetime
    y_home: int
    y_away: int
    mu_home: float
    mu_away: float
    base_home: float
    base_away: float
    with_referee: bool = False


@dataclass
class Evaluation:
    measure: str
    rows: list[Row]
    skipped_blocks: int
    model: Dispersion
    baseline: Dispersion
    params: dict[str, float] = field(default_factory=dict)


def _baseline(train: Sequence[Match], at: datetime, xi: float) -> tuple[float, float]:
    """The competition's average home and away count over the training window, with the same time decay as the model."""
    w = np.array([math.exp(-xi * max(0.0, (at - m.kickoff_at).total_seconds() / DAY)) for m in train])
    h = np.array([m.home for m in train], dtype=float)
    a = np.array([m.away for m in train], dtype=float)
    return float((w * h).sum() / w.sum()), float((w * a).sum() / w.sum())


def walk_forward(by_competition: Mapping[int, Sequence[Match]], *, measure: str, start: datetime, end: datetime, step_days: int = 28,
                 xi: float = DEFAULT_XI, penalty: float = DEFAULT_PENALTY, referee_kappa: float | None = None) -> Evaluation:
    """Predict every match with a kick-off in ``[start, end)`` from the matches known at the start of its block.

    With ``referee_kappa`` the means of a match whose referee is known (and has enough known matches) are scaled by his multiplier
    (``fbi.families.referee``), learned from the matches known at the start of the block."""
    rows: list[Row] = []
    skipped = 0
    for competition, matches in by_competition.items():
        ordered = sorted(matches, key=lambda m: (m.kickoff_at, m.fixture_id))
        t = start
        while t < end:
            block_end = min(t + timedelta(days=step_days), end)
            block = [m for m in ordered if t <= m.kickoff_at < block_end]
            if block:
                train = [m for m in ordered if known_at(m) <= t]
                try:
                    fitted = fit_family(train, measure=measure, at=t, xi=xi, penalty=penalty, dispersion=Dispersion(0.0, 0.0, 0.0))
                except NotEnoughHistoryError:
                    skipped += 1
                else:
                    base_h, base_a = _baseline(train, t, xi)
                    multipliers = referee.factors(train, fitted, kappa=referee_kappa) if referee_kappa else {}
                    for m in block:
                        if not fitted.knows(m.home_id, m.away_id):
                            continue
                        mu_h, mu_a = fitted.means(m.home_id, m.away_id)
                        factor = multipliers.get(m.referee_id) if m.referee_id is not None else None
                        if factor is not None:
                            mu_h, mu_a = mu_h * factor, mu_a * factor
                        rows.append(Row(m.fixture_id, competition, m.kickoff_at, m.home, m.away, mu_h, mu_a, base_h, base_a, factor is not None))
            t = block_end
    if not rows:
        return Evaluation(measure, [], skipped, Dispersion(0.0, 0.0, 0.0), Dispersion(0.0, 0.0, 0.0),
                          {"xi": xi, "penalty": penalty, "step_days": float(step_days), "referee_kappa": referee_kappa or 0.0})
    yh, ya = [r.y_home for r in rows], [r.y_away for r in rows]
    model = estimate_dispersion(yh, [r.mu_home for r in rows], ya, [r.mu_away for r in rows])
    baseline = estimate_dispersion(yh, [r.base_home for r in rows], ya, [r.base_away for r in rows])
    return Evaluation(measure, rows, skipped, model, baseline, {"xi": xi, "penalty": penalty, "step_days": float(step_days), "referee_kappa": referee_kappa or 0.0})


def _log(p: float) -> float:
    return math.log(max(p, 1e-12))


def _pmfs(mu_h: float, mu_a: float, d: Dispersion) -> tuple[Any, Any, Any]:
    ph, pa = nb_pmf(mu_h, d.home), nb_pmf(mu_a, d.away)
    pt = nb_pmf(mu_h + mu_a, d.total, 2 * MAX_COUNT)
    return normalised(ph), normalised(pa), normalised(pt)


def _line_block(pm: Any, pb: Any, y: Any) -> dict[str, Any]:
    """The scores of one yes/no bet (an over): the model's probabilities ``pm`` and the baseline's ``pb`` against what happened ``y``."""
    n = len(y)
    pm_c, pb_c = np.clip(pm, 1e-6, 1 - 1e-6), np.clip(pb, 1e-6, 1 - 1e-6)
    ll_m = -(y * np.log(pm_c) + (1 - y) * np.log(1 - pm_c))
    ll_b = -(y * np.log(pb_c) + (1 - y) * np.log(1 - pb_c))
    edges = np.linspace(0.0, 1.0, BINS + 1)
    which = np.clip(np.digitize(pm, edges) - 1, 0, BINS - 1)
    reliability = [{"bin": b, "n": int((which == b).sum()), "mean_p": float(pm[which == b].mean()), "observed": float(y[which == b].mean())}
                   for b in range(BINS) if (which == b).any()]
    return {
        "over_rate": float(y.mean()),
        "log_loss_model": float(ll_m.mean()), "log_loss_baseline": float(ll_b.mean()),
        "log_loss_gain": float((ll_b - ll_m).mean()), "log_loss_gain_se": float((ll_b - ll_m).std(ddof=1) / math.sqrt(n)) if n > 1 else None,
        "brier_model": float(((pm - y) ** 2).mean()), "brier_baseline": float(((pb - y) ** 2).mean()),
        "reliability": reliability,
    }


def summarise(ev: Evaluation, lines: Sequence[float] = (), side_lines: Sequence[float] = ()) -> dict[str, Any]:
    """The numbers that say whether the family learnt something: the log score of what happened against the baseline's, and for each bet the
    log loss, the Brier score and the reliability: ``lines`` are the lines of the TOTAL, ``side_lines`` those of ONE side (home and away
    each), and ``result`` is who had more (the "1X2" of the count)."""
    n = len(ev.rows)
    if n == 0:
        return {"measure": ev.measure, "n": 0, "skipped_blocks": ev.skipped_blocks}
    diffs: dict[str, list[float]] = {"home": [], "away": [], "total": []}
    line_stats: dict[float, dict[str, list[float]]] = {ln: {"p_model": [], "p_base": [], "y": []} for ln in lines}
    side_stats: dict[tuple[str, float], dict[str, list[float]]] = {(side, ln): {"p_model": [], "p_base": [], "y": []}
                                                                   for side in ("home", "away") for ln in side_lines}
    result_gain: list[float] = []
    for r in ev.rows:
        mh, mah, mth = _pmfs(r.mu_home, r.mu_away, ev.model)
        bh, bah, bth = _pmfs(r.base_home, r.base_away, ev.baseline)
        total = r.y_home + r.y_away
        diffs["home"].append(_log(float(mh[r.y_home]) if r.y_home < mh.size else 0.0) - _log(float(bh[r.y_home]) if r.y_home < bh.size else 0.0))
        diffs["away"].append(_log(float(mah[r.y_away]) if r.y_away < mah.size else 0.0) - _log(float(bah[r.y_away]) if r.y_away < bah.size else 0.0))
        diffs["total"].append(_log(float(mth[total]) if total < mth.size else 0.0) - _log(float(bth[total]) if total < bth.size else 0.0))
        for ln in lines:
            line_stats[ln]["p_model"].append(over_under(mth, ln).over)
            line_stats[ln]["p_base"].append(over_under(bth, ln).over)
            line_stats[ln]["y"].append(1.0 if total > ln else 0.0)
        for (side, ln), st in side_stats.items():
            pmf_m, pmf_b, y = (mh, bh, r.y_home) if side == "home" else (mah, bah, r.y_away)
            st["p_model"].append(over_under(pmf_m, ln).over)
            st["p_base"].append(over_under(pmf_b, ln).over)
            st["y"].append(1.0 if y > ln else 0.0)
        happened = 0 if r.y_home > r.y_away else (1 if r.y_home == r.y_away else 2)
        result_gain.append(_log(difference_probs(mh, mah)[happened]) - _log(difference_probs(bh, bah)[happened]))
    out: dict[str, Any] = {
        "measure": ev.measure, "n": n, "skipped_blocks": ev.skipped_blocks, "params": ev.params,
        "dispersion_model": {"home": ev.model.home, "away": ev.model.away, "total": ev.model.total},
        "dispersion_baseline": {"home": ev.baseline.home, "away": ev.baseline.away, "total": ev.baseline.total},
        "mean_observed": {"home": float(np.mean([r.y_home for r in ev.rows])), "away": float(np.mean([r.y_away for r in ev.rows]))},
        "log_score_gain_per_match": {},
        "lines": {},
        "side_lines": {},
    }
    for side, d in diffs.items():
        arr = np.array(d)
        out["log_score_gain_per_match"][side] = {"mean": float(arr.mean()), "se": float(arr.std(ddof=1) / math.sqrt(n)) if n > 1 else None}
    for ln, st in line_stats.items():
        out["lines"][str(ln)] = _line_block(np.array(st["p_model"]), np.array(st["p_base"]), np.array(st["y"]))
    for (side, ln), st in side_stats.items():
        out["side_lines"][f"{side} {ln}"] = _line_block(np.array(st["p_model"]), np.array(st["p_base"]), np.array(st["y"]))
    arr = np.array(result_gain)
    out["result"] = {"log_score_gain": float(arr.mean()), "se": float(arr.std(ddof=1) / math.sqrt(n)) if n > 1 else None}
    return out


def by_competition(ev: Evaluation) -> list[dict[str, Any]]:
    """The log-score gain over the baseline on the TOTAL, competition by competition (the competitions with most predictions first)."""
    groups: dict[int, list[Row]] = {}
    for r in ev.rows:
        groups.setdefault(r.competition_id, []).append(r)
    out: list[dict[str, Any]] = []
    for competition, rows in groups.items():
        gains = []
        for r in rows:
            _, _, mt = _pmfs(r.mu_home, r.mu_away, ev.model)
            _, _, bt = _pmfs(r.base_home, r.base_away, ev.baseline)
            k = r.y_home + r.y_away
            gains.append(_log(float(mt[k]) if k < mt.size else 0.0) - _log(float(bt[k]) if k < bt.size else 0.0))
        arr = np.array(gains)
        out.append({"competition_id": competition, "n": len(rows), "gain": float(arr.mean()),
                    "se": float(arr.std(ddof=1) / math.sqrt(len(rows))) if len(rows) > 1 else None})
    return sorted(out, key=lambda d: -int(d["n"]))


def compare_referee(plain: Evaluation, with_referee: Evaluation) -> dict[str, Any]:
    """The log score the referee adds, per match, to each count (home side, away side, total): the paired difference of two evaluations of the
    same matches, one without and one with the multiplier of the referee, each with the dispersion it measured. Also the share of the matches
    that had a multiplier and the gain over those alone."""
    if [r.fixture_id for r in plain.rows] != [r.fixture_id for r in with_referee.rows]:
        raise ValueError("the two evaluations are not of the same matches")
    out: dict[str, Any] = {"n": len(plain.rows)}
    if not plain.rows:
        return out
    scores = {"plain": _log_scores(plain), "referee": _log_scores(with_referee)}
    diff = scores["referee"] - scores["plain"]
    covered = np.array([r.with_referee for r in with_referee.rows])
    out["coverage"] = float(covered.mean())
    for i, name in enumerate(("home", "away", "total")):
        d = diff[:, i]
        out[name] = {"mean": float(d.mean()), "se": float(d.std(ddof=1) / math.sqrt(len(d))) if len(d) > 1 else None,
                     "mean_with_referee_only": float(d[covered].mean()) if covered.any() else None}
    out["dispersion_plain"] = asdict(plain.model)
    out["dispersion_referee"] = asdict(with_referee.model)
    return out


def _log_scores(ev: Evaluation) -> Any:
    """The log score of the model on (home, away, total) for every row: an array of shape (n, 3)."""
    out = np.zeros((len(ev.rows), 3))
    for i, r in enumerate(ev.rows):
        ph, pa, pt = _pmfs(r.mu_home, r.mu_away, ev.model)
        k = r.y_home + r.y_away
        out[i] = (_log(float(ph[r.y_home]) if r.y_home < ph.size else 0.0), _log(float(pa[r.y_away]) if r.y_away < pa.size else 0.0),
                  _log(float(pt[k]) if k < pt.size else 0.0))
    return out


MIN_CALIBRATION_TEST: Final = 200
"""Fewer out-of-sample predictions than twice this are not split into a half that fits a recalibration and a half that grades it."""


def _logit(p: Any) -> Any:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(q / (1 - q))


def _sigmoid(z: Any) -> Any:
    return 1.0 / (1.0 + np.exp(-z))


def ece(p: Any, y: Any, bins: int = BINS) -> float:
    """Expected calibration error: the gap between what was said and what happened, bin by bin of the predicted probability, weighted by the
    share of the predictions in the bin."""
    which = np.clip(np.digitize(p, np.linspace(0.0, 1.0, bins + 1)) - 1, 0, bins - 1)
    total = 0.0
    for b in range(bins):
        mask = which == b
        if mask.any():
            total += float(mask.sum()) * abs(float(p[mask].mean()) - float(y[mask].mean()))
    return total / len(p)


def recalibrate(p: Any, y: Any, *, slope: bool = True) -> tuple[float, float]:
    """The logistic recalibration ``q = sigmoid(a * logit(p) + b)`` that best fits what happened (``y``, 0 or 1), by Newton's method: ``(a, b)``.
    With ``slope=False`` only the shift ``b`` is fitted and ``a`` stays 1. A bet that always or never happened is left as it is."""
    if len(y) == 0 or float(y.min()) == float(y.max()):
        return 1.0, 0.0
    z = _logit(p)
    a, b = 1.0, 0.0
    for _ in range(60):
        q = _sigmoid(a * z + b)
        w = q * (1 - q) + 1e-12
        g_b, g_a = float((q - y).sum()), float(((q - y) * z).sum())
        if slope:
            h = np.array([[float((w * z * z).sum()), float((w * z).sum())], [float((w * z).sum()), float(w.sum())]]) + 1e-9 * np.eye(2)
            step = np.linalg.solve(h, np.array([g_a, g_b]))
        else:
            step = np.array([0.0, g_b / float(w.sum())])
        a, b = a - float(step[0]), b - float(step[1])
        if float(np.abs(step).max()) < 1e-9:
            break
    return a, b


def _bet_loss(p: Any, y: Any) -> Any:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(q) + (1 - y) * np.log(1 - q))


def calibration_check(ev: Evaluation, lines: Sequence[float] = (), side_lines: Sequence[float] = ()) -> dict[str, Any]:
    """Would a recalibration repair the over/under probabilities, and by how much? The out-of-sample predictions are put in the order they were
    played: the first half fits two recalibrations (a shift of the logit of the probability, and a shift with a slope) and the second half grades
    them - the ECE and the log loss of the probabilities as the model said them, shifted and with a slope. A recalibration is never graded on
    the matches that fitted it. ``gain`` is the log loss it saves per prediction (its standard error beside it)."""
    rows = sorted(ev.rows, key=lambda r: (r.kickoff_at, r.fixture_id))
    n = len(rows)
    out: dict[str, Any] = {"n": n, "bets": {}}
    if n < 2 * MIN_CALIBRATION_TEST:
        return out
    probs: dict[str, tuple[list[float], list[float]]] = {}
    for r in rows:
        pmf_home, pmf_away, pmf_total = _pmfs(r.mu_home, r.mu_away, ev.model)
        total = r.y_home + r.y_away
        for ln in lines:
            p_list, y_list = probs.setdefault(f"total {ln}", ([], []))
            p_list.append(over_under(pmf_total, ln).over)
            y_list.append(1.0 if total > ln else 0.0)
        for side, pmf, count in (("home", pmf_home, r.y_home), ("away", pmf_away, r.y_away)):
            for ln in side_lines:
                p_list, y_list = probs.setdefault(f"{side} {ln}", ([], []))
                p_list.append(over_under(pmf, ln).over)
                y_list.append(1.0 if count > ln else 0.0)
    cut = n // 2
    out["fit_until"] = rows[cut - 1].kickoff_at.isoformat()
    for name, (p_all, y_all) in probs.items():
        p, y = np.array(p_all), np.array(y_all)
        p_test, y_test = p[cut:], y[cut:]
        shift = recalibrate(p[:cut], y[:cut], slope=False)
        sloped = recalibrate(p[:cut], y[:cut], slope=True)
        z = _logit(p_test)
        variants = {"raw": p_test, "shift": _sigmoid(z + shift[1]), "slope": _sigmoid(sloped[0] * z + sloped[1])}
        losses = {k: _bet_loss(v, y_test) for k, v in variants.items()}
        saved = {k: losses["raw"] - losses[k] for k in ("shift", "slope")}
        out["bets"][name] = {
            "n_fit": cut, "n_test": n - cut,
            "shift": shift[1], "slope": sloped[0], "intercept": sloped[1],
            "mean_p": float(p_test.mean()), "observed": float(y_test.mean()),
            "ece": {k: ece(v, y_test) for k, v in variants.items()},
            "log_loss": {k: float(v.mean()) for k, v in losses.items()},
            "gain": {k: {"mean": float(v.mean()), "se": float(v.std(ddof=1) / math.sqrt(len(v))) if len(v) > 1 else None} for k, v in saved.items()},
        }
    return out


DEFAULT_XIS: Final = (0.0, 0.0019, 0.004)
DEFAULT_PENALTIES: Final = (0.5, 2.0, 8.0, 32.0)
TUNED_ON: Final = ("home", "away", "total")
"""The counts whose log-score gains are averaged to choose the hyper-parameters: a family states markets on the count of each side and on the
total, and (corners, 23 Oct 2026) the sides can have all the skill while the total has none - tuned on the total alone, the choice is noise."""


def tune(by_competition_matches: Mapping[int, Sequence[Match]], *, measure: str, start: datetime, days: int = 180, step_days: int = 28,
         xis: Sequence[float] = DEFAULT_XIS, penalties: Sequence[float] = DEFAULT_PENALTIES, counts: Sequence[str] = TUNED_ON) -> tuple[float, float, dict[str, float]]:
    """Choose the time decay and the penalty on the ``days`` BEFORE ``start`` (never on the test window): the pair with the best mean log-score
    gain over the baseline, averaged over ``counts`` (the home side, the away side and the total). Returns (xi, penalty, the grid's scores)."""
    grid: dict[str, float] = {}
    best: tuple[float, float, float] | None = None
    for xi in xis:
        for penalty in penalties:
            ev = walk_forward(by_competition_matches, measure=measure, start=start - timedelta(days=days), end=start, step_days=step_days,
                              xi=xi, penalty=penalty)
            if not ev.rows:
                continue
            gains = summarise(ev)["log_score_gain_per_match"]
            gain = float(np.mean([gains[c]["mean"] for c in counts]))
            grid[f"xi={xi},penalty={penalty}"] = gain
            if best is None or gain > best[0]:
                best = (gain, xi, penalty)
    if best is None:
        return DEFAULT_XI, DEFAULT_PENALTY, grid
    return best[1], best[2], grid
