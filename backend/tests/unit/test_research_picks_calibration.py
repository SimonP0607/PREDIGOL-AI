"""F2 of the PICKS plan on a world whose answer is known: an overconfident model, a calibrated market."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from scripts.research_picks_calibration import (
    Forecast,
    calibrate_out_of_sample,
    cluster_ci,
    lean,
    q2_direction,
    q5_price,
    research,
)

START = datetime(2026, 9, 1, 17, 0, tzinfo=UTC)


def world(days: int = 40, per_day: int = 300, seed: int = 3) -> list[dict[str, Any]]:
    """The market is right; the model says 12 points more on every selection it flags, and flags «under» 80 % of the
    time in goals. The price is the market's fair price with an 8 % margin, so no rule can win on average."""
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    pid = 0
    for d in range(days):
        for i in range(per_day):
            pid += 1
            p_true = rng.uniform(0.30, 0.65)
            ko = START + timedelta(days=d, minutes=i)
            market = "OU" if i % 2 else "1X2"
            selection = ("Under" if rng.random() < 0.8 else "Over") if market == "OU" else "Home"
            rows.append({
                "pick_id": pid, "fixture_id": 10_000 + pid // 2, "kickoff_at": ko, "settled_at": ko + timedelta(hours=2),
                "market_key": market, "model_name": "dixon-coles", "p_model": min(p_true + 0.12, 0.97),
                "p_market": p_true, "odds": round(0.92 / p_true, 3),
                "result_status": "win" if rng.random() < p_true else "loss", "clv": rng.uniform(-0.15, 0.05),
                "selection": selection, "line": 2.5 if market == "OU" else 0.0, "competition": "Liga A",
                "newcomer": i % 10 == 1,
            })
    return rows


def test_no_selection_is_scored_by_a_fit_that_saw_it() -> None:
    rows = world(days=12, per_day=120)
    sels = calibrate_out_of_sample(rows, min_train=200)
    scored = [s for s in sels if s.p_cal is not None]
    assert scored, "a fit is possible once enough was settled before the day began"
    first_scored = min(s.obs.kickoff_at for s in scored)
    # each market has 60 a day: 200 settled take four days before the first fit
    assert first_scored >= START + timedelta(days=3)
    assert all(s.p_cal is None for s in sels if s.obs.kickoff_at < START + timedelta(days=3))


def test_the_overconfident_model_is_caught_and_its_rule_does_not_publish() -> None:
    f = research(world())
    q = f["q1"]["1X2"]
    assert q["enough"] and q["p_raw"] > q["hit"] + 0.08, "the raw probability is far above the hit rate"
    assert q["ece_cal"] < q["ece_raw"] and q["proposal"]["show_calibrated"]
    assert q["board_rule"]["roi"] < 0 and q["proposal"]["board_rule_does_not_publish"]
    assert not any(b["raise_cap_here"] for b in f["q3"]), "no band is paid in a world without value"


def forecasts(n: int, *, lean_pp: float, truth: str, competition: str = "Liga A", newcomer: bool = False,
              seed: int = 5, start: int = 0) -> list[Forecast]:
    """``n`` matches whose «under 2.5» the model sees ``lean_pp`` points above the market. ``truth``: who is right -
    ``market`` (the matches go under at the market's rate) or ``model`` (at the model's)."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        p_market = rng.uniform(0.40, 0.60)
        p_model = p_market + lean_pp / 100
        p_true = p_market if truth == "market" else p_model
        out.append(Forecast(start + i, "OU", "dixon_coles", competition, newcomer, p_model, p_market,
                            rng.random() < p_true))
    return out


def test_the_lean_is_a_bias_only_when_the_matches_side_with_the_market() -> None:
    wrong = lean(forecasts(2000, lean_pp=6, truth="market"))
    assert wrong["bias"] and wrong["direction"] == "low" and wrong["lean_ci_pp"][0] > 0
    assert abs(wrong["model_gap_pp"]) > abs(wrong["market_gap_pp"])
    right = lean(forecasts(2000, lean_pp=6, truth="model"))
    assert not right["bias"], "a model that leans and is right is not a bias to correct"
    small = lean(forecasts(2000, lean_pp=1, truth="market"))
    assert not small["bias"], "under 3 points it is not reported"
    few = lean(forecasts(120, lean_pp=8, truth="market"))
    assert not few["bias"] and few["lean_ci_pp"] is None and not few["enough"]


def test_the_symptom_is_on_the_flagged_picks_and_the_diagnosis_on_every_forecast() -> None:
    sels = calibrate_out_of_sample(world(), min_train=200)
    all_forecasts = (forecasts(1500, lean_pp=6, truth="market")
                     + forecasts(400, lean_pp=6, truth="market", newcomer=True, seed=9, start=10_000))
    q = q2_direction(sels, all_forecasts)
    assert 0.75 < q["flagged"]["OU"]["share_low"] < 0.85, "the share of «under» among the flagged picks"
    d = q["forecasts"]["OU/dixon_coles"]
    assert d["overall"]["n"] == 1900 and d["overall"]["bias"]
    rows = {(r["competition"], r["newcomer"]): r for r in d["by_competition"]}
    assert rows[("Liga A", False)]["n"] == 1500 and rows[("Liga A", True)]["n"] == 400


def test_the_price_is_said_in_points_whatever_the_sign_of_the_return() -> None:
    f = research(world())
    q5 = q5_price([])
    assert q5["price_gain_pp"] is None
    gain = f["q5"]["price_gain_pp"]
    at_price, at_fair = f["q5"]["at_price_taken"]["roi"], f["q5"]["at_fair_price"]["roi"]
    assert gain == round(100 * (at_price - at_fair), 2)
    assert at_price < 0 and gain < 0, "a margin below the fair price costs points even when the return is negative"


def test_the_interval_resamples_matches_not_selections() -> None:
    values = np.array([1.0, 1.0, -1.0, -1.0] * 100)
    same_match = np.repeat(np.arange(200), 2)  # two identical outcomes per match
    lo, hi = cluster_ci(values, same_match)
    lo1, hi1 = cluster_ci(values, np.arange(400))
    assert lo < 0 < hi and (hi - lo) > (hi1 - lo1), "correlated selections widen the interval"
