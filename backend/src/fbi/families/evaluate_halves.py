"""Grading the bets derived from the two halves (plan F10): did adding the halves up say anything the competition's average does not?

``evaluate.walk_forward`` predicts the goals of ONE half. This module takes the evaluations of the first and of the second half, joins them by
match, derives the whole menu of ``halves.menu`` from each side's predictions (the model's and the baseline's: every team gets the average
of its competition) and scores both against how the match really went: the log loss of every group of outcomes (the result of a half, the
highest scoring half, the nine HT/FT cells) and of every yes/no bet (both teams score in a half, over/under, odd/even).

It also measures the assumption the derivation rests on: that the second half does not depend on the first once the strengths of the teams
are known. The correlation between what the first half did beyond its prediction and what the second half did beyond its prediction is
reported with its standard error, and so is the calibration of the nine HT/FT cells, where a dependence would show first.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Final

import numpy as np

from fbi.families import halves
from fbi.families.evaluate import Evaluation, Row
from fbi.families.fit import prediction

GROUPS: Final[dict[str, tuple[str, ...]]] = {
    "result_1h": ("ht_1", "ht_x", "ht_2"),
    "result_2h": ("h2_1", "h2_x", "h2_2"),
    "highest_half": ("best_first", "best_tie", "best_second"),
    "htft": tuple("htft_" + label.lower().replace("/", "_") for label in halves.HTFT_LABELS),
}
"""The outcomes that are one of several: exactly one of them happens, and the log loss is that of the one that did."""
_GROUPED = frozenset(k for keys in GROUPS.values() for k in keys)


def _sign(d: int) -> str:
    return "1" if d > 0 else ("x" if d == 0 else "2")


def outcomes(first: tuple[int, int], second: tuple[int, int]) -> dict[str, float]:
    """What every key of ``halves.menu`` turned out to be, for a match whose halves ended ``first`` and ``second`` (home, away goals):
    1.0 for the outcome that happened, 0.0 for the rest; for an over/under key 1.0 means over."""
    (h1, a1), (h2, a2) = first, second
    t1, t2 = h1 + a1, h2 + a2
    out: dict[str, float] = {}
    for keys in GROUPS.values():
        out.update(dict.fromkeys(keys, 0.0))
    out[f"ht_{_sign(h1 - a1)}"] = 1.0
    out[f"h2_{_sign(h2 - a2)}"] = 1.0
    out[f"htft_{_sign(h1 - a1)}_{_sign(h1 + h2 - a1 - a2)}"] = 1.0
    out["best_first" if t1 > t2 else ("best_tie" if t1 == t2 else "best_second")] = 1.0
    out["btts_1h"] = 1.0 if h1 > 0 and a1 > 0 else 0.0
    out["btts_2h"] = 1.0 if h2 > 0 and a2 > 0 else 0.0
    for tag, total in (("1h", t1), ("2h", t2)):
        for line in halves.TOTAL_LINES:
            out[f"ou_{tag}_{line}"] = 1.0 if total > line else 0.0
        out[f"odd_{tag}"] = float(total % 2)
    return out


def _log(p: float) -> float:
    return math.log(max(p, 1e-12))


def _group_loss(keys: Sequence[str], p: dict[str, float], actual: dict[str, float]) -> float:
    """-log of the probability given to the outcome of the group that happened."""
    return -_log(p[next(k for k in keys if actual[k] == 1.0)])


def _binary_loss(p: float, y: float) -> float:
    q = min(max(p, 1e-6), 1.0 - 1e-6)
    return -(y * math.log(q) + (1.0 - y) * math.log(1.0 - q))


def _pair(first: Evaluation, second: Evaluation, a: Row, b: Row, *, model: bool) -> dict[str, float]:
    if model:
        return halves.menu(prediction(a.mu_home, a.mu_away, first.model), prediction(b.mu_home, b.mu_away, second.model))
    return halves.menu(prediction(a.base_home, a.base_away, first.baseline), prediction(b.base_home, b.base_away, second.baseline))


def evaluate(first: Evaluation, second: Evaluation) -> dict[str, Any]:
    """The matches that both evaluations predicted, graded on the whole menu of the halves, model against baseline."""
    by_id = {r.fixture_id: r for r in first.rows}
    pairs = [(by_id[r.fixture_id], r) for r in second.rows if r.fixture_id in by_id]
    n = len(pairs)
    if n == 0:
        return {"n": 0}
    model_loss: dict[str, list[float]] = {}
    base_loss: dict[str, list[float]] = {}
    cells = GROUPS["htft"]
    predicted_cell: dict[str, list[float]] = {c: [] for c in cells}
    observed_cell: dict[str, list[float]] = {c: [] for c in cells}
    for a, b in pairs:
        actual = outcomes((a.y_home, a.y_away), (b.y_home, b.y_away))
        m, base = _pair(first, second, a, b, model=True), _pair(first, second, a, b, model=False)
        for name, keys in GROUPS.items():
            model_loss.setdefault(name, []).append(_group_loss(keys, m, actual))
            base_loss.setdefault(name, []).append(_group_loss(keys, base, actual))
        for key in m:
            if key not in _GROUPED:
                model_loss.setdefault(key, []).append(_binary_loss(m[key], actual[key]))
                base_loss.setdefault(key, []).append(_binary_loss(base[key], actual[key]))
        for c in cells:
            predicted_cell[c].append(m[c])
            observed_cell[c].append(actual[c])
    markets: dict[str, Any] = {}
    for name, losses in model_loss.items():
        lm, lb = np.array(losses), np.array(base_loss[name])
        gain = lb - lm
        markets[name] = {
            "n": n, "log_loss_model": float(lm.mean()), "log_loss_baseline": float(lb.mean()),
            "gain": float(gain.mean()), "gain_se": float(gain.std(ddof=1) / math.sqrt(n)) if n > 1 else None,
        }
    res_first = np.array([(a.y_home + a.y_away) - (a.mu_home + a.mu_away) for a, _ in pairs])
    res_second = np.array([(b.y_home + b.y_away) - (b.mu_home + b.mu_away) for _, b in pairs])
    corr = float(np.corrcoef(res_first, res_second)[0, 1]) if n > 2 and res_first.std() > 0 and res_second.std() > 0 else None
    return {
        "n": n,
        "mean_goals": {"first_half": float(np.mean([a.y_home + a.y_away for a, _ in pairs])),
                       "second_half": float(np.mean([b.y_home + b.y_away for _, b in pairs]))},
        "markets": markets,
        "halves_residual_correlation": {"r": corr, "se": 1.0 / math.sqrt(n) if n > 0 else None},
        "htft_calibration": [{"cell": c.removeprefix("htft_"), "mean_predicted": float(np.mean(predicted_cell[c])),
                              "observed": float(np.mean(observed_cell[c]))} for c in cells],
    }
