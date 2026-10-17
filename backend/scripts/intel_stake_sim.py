"""PrediGol Intelligence, stake-v1: are a quarter of Kelly and its caps prudent? Read-only simulation.

    python -m scripts.intel_stake_sim [--days 60] [--paths 2000] [--market OU]

The bets are the walk-forward out-of-sample selections of each (market, model) whose CALIBRATED EV was >= 2 % at the
price taken (``fbi.intel.calibration.walk_forward``: each day scored by a calibrator fitted on the days before), in the
order they happened. Two worlds:

    REALISED   the outcomes that really happened (one path): what each policy would have done
    CALIBRATED outcomes drawn from the calibrated probability (``--paths`` paths): what each policy does IF the
               calibration is right - the best case the stake rule can assume

Policies: flat 1 u; Kelly x 1/4 capped at 1 u (stake-v1, APROBADO); x 1/4 capped at 1.5 u (PREMIUM); x 1/2 uncapped;
full Kelly. 1 u = 1 % of the bankroll, staked on the CURRENT bankroll (compounding), bankroll starts at 100 u.
Reported: final bankroll (median, 5 %), the worst drawdown (median, 95 %), the chance of a 30 % and of a 50 %
drawdown, and the realised path's figures. Nothing is written.
"""

from __future__ import annotations

import argparse
import math
from datetime import timedelta
from typing import Any

import numpy as np

from fbi.core.clock import now
from fbi.intel import calibration
from fbi.intel.stake import kelly

POLICIES: dict[str, tuple[float, float | None]] = {"flat_1u": (0.0, 1.0), "kelly_q_cap1": (0.25, 1.0),
                                                  "kelly_q_cap1.5": (0.25, 1.5), "kelly_half": (0.5, None),
                                                  "kelly_full": (1.0, None)}


def stake_units(policy: str, p: float, odds: float) -> float:
    frac, cap = POLICIES[policy]
    if frac == 0.0:
        return 1.0
    f = kelly(p, odds)
    if f <= 0:
        return 0.0
    units = frac * f * 100
    if cap is not None:
        units = math.floor(units / 0.25) * 0.25
        units = min(units, cap)
    return units


def run_path(bets: list[tuple[float, float]], wins: np.ndarray, policy: str) -> tuple[float, float]:
    bank = 100.0
    peak = bank
    worst = 0.0
    for (p, odds), w in zip(bets, wins, strict=True):
        stake = bank * stake_units(policy, p, odds) / 100.0
        bank += stake * (odds - 1) if w else -stake
        bank = max(bank, 1e-9)
        peak = max(peak, bank)
        worst = max(worst, 1 - bank / peak)
    return bank, worst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--paths", type=int, default=2000)
    ap.add_argument("--market", default=None)
    args = ap.parse_args()
    import psycopg

    from fbi.core.config import settings

    url = settings.database.psycopg_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, options="-c default_transaction_read_only=on") as conn:
        obs = calibration.load_observations(conn, cutoff=now(), market=args.market,
                                            history=timedelta(days=args.days))
    groups: dict[tuple[str, str], list[calibration.Obs]] = {}
    for o in obs:
        groups.setdefault((o.market_key, o.model_name), []).append(o)
    rng = np.random.default_rng(13)
    out: dict[str, Any] = {}
    for key, xs in sorted(groups.items()):
        bets: list[tuple[float, float]] = []
        realised: list[bool] = []
        by_day: dict[Any, list[calibration.Obs]] = {}
        for o in xs:
            by_day.setdefault(o.day, []).append(o)
        days = sorted(by_day)
        for i, d in enumerate(days):
            if i < calibration.WF_MIN_PRIOR_DAYS:
                continue
            train = calibration.train_set(xs, cutoff=calibration.day_start(d))
            if len(train) < calibration.MIN_TRAIN:
                continue
            params = calibration.fit_params("logit2", train)
            for o in sorted(by_day[d], key=lambda o: o.kickoff_at):
                p = calibration.apply_params("logit2", params, o.p_model, o.p_market)
                if p is None or p * o.odds - 1 < calibration.EV_RULE:
                    continue
                bets.append((p, o.odds))
                realised.append(o.y == 1)
        if len(bets) < 50:
            print(f"{key}: {len(bets)} bets - too few to simulate")
            continue
        probs = np.array([b[0] for b in bets])
        res: dict[str, Any] = {"bets": len(bets), "mean_odds": round(float(np.mean([b[1] for b in bets])), 3),
                               "mean_p_cal": round(float(probs.mean()), 4)}
        for policy in POLICIES:
            finals, dds = [], []
            for _ in range(args.paths):
                wins = rng.random(len(bets)) < probs
                f, dd = run_path(bets, wins, policy)
                finals.append(f)
                dds.append(dd)
            rf, rdd = run_path(bets, np.array(realised), policy)
            res[policy] = {"calibrated_final_median": round(float(np.median(finals)), 2),
                           "calibrated_final_p5": round(float(np.percentile(finals, 5)), 2),
                           "calibrated_dd_median": round(float(np.median(dds)), 4),
                           "calibrated_dd_p95": round(float(np.percentile(dds, 95)), 4),
                           "p_dd_30": round(float(np.mean(np.array(dds) >= 0.30)), 4),
                           "p_dd_50": round(float(np.mean(np.array(dds) >= 0.50)), 4),
                           "realised_final": round(rf, 2), "realised_dd": round(rdd, 4)}
        out[f"{key[0]}/{key[1]}"] = res
        print(f"\n## {key[0]}/{key[1]}: {res['bets']} bets, mean odds {res['mean_odds']}, mean p_cal {res['mean_p_cal']}")
        for policy in POLICIES:
            r = res[policy]
            print(f"  {policy:15s} calibrated: final median {r['calibrated_final_median']:8.2f}  p5 "
                  f"{r['calibrated_final_p5']:8.2f}  maxDD median {r['calibrated_dd_median']:.3f}  p95 "
                  f"{r['calibrated_dd_p95']:.3f}  P(DD>=30%) {r['p_dd_30']:.3f}  P(DD>=50%) {r['p_dd_50']:.3f} | "
                  f"realised: final {r['realised_final']:8.2f}  maxDD {r['realised_dd']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
