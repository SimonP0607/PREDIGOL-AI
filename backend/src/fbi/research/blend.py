"""Does a model add anything to the market? A logarithmic opinion pool, fitted out of sample.

    p  proportional to  q^(1 - w) * m^w        q: the de-vigged market, m: the model

``w`` is the weight the data give the model next to the market (Pitcan 2026 ran this
test against the Serie A close; ``docs/research/MODEL_RESEARCH_V2_2026.md`` section 4):
w = 0 is the market alone, w = 1 the model alone, 0 < w < 1 a blend. A model can be a
worse forecaster than the market and still carry information the market lacks - then w
is above zero. If w is zero, or its interval includes zero, the model adds nothing the
market did not already know, however it scores on its own.

Protocol (fixed before the test season is read):
  * w is FITTED on the validation season (the model's own walk-forward predictions there
    against the market's) and APPLIED unchanged to the test season;
  * the blended forecast is then compared with the market on the test season, paired on
    the same fixtures, with the match-day block bootstrap every comparison uses;
  * w is also re-estimated on the test season itself, with a block-bootstrap interval:
    the reading "w > 0" needs that whole interval above zero.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize_scalar

from fbi.models.metrics import per_match_log_loss

W_BOUNDS = (-1.0, 2.0)
"""Wide on purpose: a negative w (the model anti-informative) or above 1 (the market
should be discounted) are possible answers and must not be clipped away."""
BOOTSTRAP_DRAWS = 500
SEED = 23
EPS = 1e-12


def pool(q: NDArray[np.float64], m: NDArray[np.float64], w: float) -> NDArray[np.float64]:
    """Row-wise q^(1-w) * m^w, renormalised."""
    logp = (1.0 - w) * np.log(np.clip(q, EPS, 1.0)) + w * np.log(np.clip(m, EPS, 1.0))
    logp -= logp.max(axis=1, keepdims=True)
    p = np.exp(logp)
    return np.asarray(p / p.sum(axis=1, keepdims=True), dtype=np.float64)


def fit_weight(q: NDArray[np.float64], m: NDArray[np.float64], y: NDArray[np.int64]) -> float:
    """The w that minimises the pooled forecast's mean log loss."""
    if len(y) == 0:
        raise ValueError("no fixtures to fit a weight on")
    res = minimize_scalar(lambda w: float(per_match_log_loss(pool(q, m, w), y).mean()),
                          bounds=W_BOUNDS, method="bounded", options={"xatol": 1e-4})
    return float(res.x)


def weight_interval(q: NDArray[np.float64], m: NDArray[np.float64], y: NDArray[np.int64],
                    blocks: Sequence[Hashable], *, draws: int = BOOTSTRAP_DRAWS, seed: int = SEED
                    ) -> tuple[float, float, float]:
    """(w, lo, hi): the weight on these fixtures, and its 95% interval from resampling whole
    match days (the blocks) with replacement and refitting."""
    w = fit_weight(q, m, y)
    labels = list(blocks)
    groups: dict[Hashable, list[int]] = {}
    for i, b in enumerate(labels):
        groups.setdefault(b, []).append(i)
    keys = list(groups)
    rng = np.random.default_rng(seed)
    ws = []
    for _ in range(draws):
        pick = rng.integers(0, len(keys), size=len(keys))
        idx = np.concatenate([np.asarray(groups[keys[k]]) for k in pick])
        ws.append(fit_weight(q[idx], m[idx], y[idx]))
    return w, float(np.quantile(ws, 0.025)), float(np.quantile(ws, 0.975))


@dataclass(frozen=True, slots=True)
class BlendResult:
    base_key: str
    w_validation: float | None
    """Fitted on the validation season; None when the model had no validation predictions."""
    n_validation: int
    w_test: float
    w_test_lo: float
    w_test_hi: float
    n_test: int
    logloss_market: float
    logloss_blend: float | None
    """On the test season, the validation w applied; None without a validation w."""
    diff_mean: float | None
    diff_lo: float | None
    diff_hi: float | None
    """Blended minus market log loss on the test season (paired, match-day block bootstrap)."""

    @property
    def adds_information(self) -> bool:
        """The test-season weight's whole interval is above zero."""
        return self.w_test_lo > 0

    @property
    def blend_beats_market(self) -> bool:
        return self.diff_hi is not None and self.diff_hi < 0

    def as_json(self) -> dict[str, object]:
        return {"base": self.base_key, "w_validation": self.w_validation, "n_validation": self.n_validation,
                "w_test": self.w_test, "w_test_ci": [self.w_test_lo, self.w_test_hi], "n_test": self.n_test,
                "logloss_market": self.logloss_market, "logloss_blend": self.logloss_blend,
                "blend_minus_market": None if self.diff_mean is None else
                [self.diff_mean, self.diff_lo, self.diff_hi],
                "adds_information": self.adds_information, "blend_beats_market": self.blend_beats_market}


def blend_analysis(*, base_key: str,
                   val_q: Mapping[int, NDArray[np.float64]], val_m: Mapping[int, NDArray[np.float64]],
                   val_y: Mapping[int, int],
                   test_q: Mapping[int, NDArray[np.float64]], test_m: Mapping[int, NDArray[np.float64]],
                   test_y: Mapping[int, int], test_blocks: Mapping[int, Hashable]) -> BlendResult | None:
    """None when the test season has fewer than 30 fixtures both priced."""
    from fbi.models.metrics import block_bootstrap_ci

    ids = sorted(set(test_q) & set(test_m) & set(test_y))
    if len(ids) < 30:
        return None
    q = np.array([test_q[i] for i in ids])
    m = np.array([test_m[i] for i in ids])
    y = np.array([test_y[i] for i in ids], dtype=np.int64)
    w, lo, hi = weight_interval(q, m, y, [test_blocks.get(i, i) for i in ids])
    ll_market = per_match_log_loss(q, y)
    vids = sorted(set(val_q) & set(val_m) & set(val_y))
    w_val = None
    ll_blend = diff = None
    if len(vids) >= 30:
        w_val = fit_weight(np.array([val_q[i] for i in vids]), np.array([val_m[i] for i in vids]),
                           np.array([val_y[i] for i in vids], dtype=np.int64))
        blended = per_match_log_loss(pool(q, m, w_val), y)
        ll_blend = float(blended.mean())
        ci = block_bootstrap_ci(blended - ll_market, [test_blocks.get(i, i) for i in ids])
        diff = (ci[0], min(ci[1], ci[0]), max(ci[2], ci[0]))
    return BlendResult(base_key, w_val, len(vids), w, lo, hi, len(ids), float(ll_market.mean()), ll_blend,
                       None if diff is None else diff[0], None if diff is None else diff[1],
                       None if diff is None else diff[2])
