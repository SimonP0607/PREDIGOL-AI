"""F2 of the PICKS plan on a world whose answer is known: an overconfident model, a calibrated market."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from scripts.research_picks_calibration import (
    calibrate_out_of_sample,
    cluster_ci,
    q2_direction,
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


def test_the_lean_toward_under_is_reported_by_competition_and_newcomers_apart() -> None:
    sels = calibrate_out_of_sample(world(), min_train=200)
    ou = q2_direction(sels)["OU"]
    assert 0.75 < ou["share_low"] < 0.85
    rows = {(r["competition"], r["newcomer"]): r for r in ou["by_competition"]}
    assert rows[("Liga A", False)]["bias"] and rows[("Liga A", False)]["lean_low_pp"] > 3
    assert ("Liga A", True) in rows


def test_the_interval_resamples_matches_not_selections() -> None:
    values = np.array([1.0, 1.0, -1.0, -1.0] * 100)
    same_match = np.repeat(np.arange(200), 2)  # two identical outcomes per match
    lo, hi = cluster_ci(values, same_match)
    lo1, hi1 = cluster_ci(values, np.arange(400))
    assert lo < 0 < hi and (hi - lo) > (hi1 - lo1), "correlated selections widen the interval"
