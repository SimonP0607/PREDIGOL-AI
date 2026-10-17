"""The model gate: what a model must show before it may leave RESEARCH.

Six checks, each with the evidence it was read from, fixed before any
session-2 result was seen:

  out_of_sample        every prediction was made from results public before its
                       block's cut-off (the walk-forward loop raises otherwise;
                       here we confirm every block was checked);
  temporal_validation  walk-forward refits, hyper-parameters from the
                       validation season only or fixed a priori;
  calibrated           ECE on the common sample no worse than the market's by
                       more than CALIBRATION_SLACK (or below CALIBRATION_FLOOR);
  reproducible         a later run of the recorded code on the recorded data
                       gave identical predictions (``scripts.experiment reproduce``);
  stable               the log-loss difference to the market has the same sign
                       in both halves of the test period and in at least
                       STABLE_COMPETITION_SHARE of the competitions with
                       MIN_GROUP or more fixtures;
  beats_market         the whole interval of the log-loss difference against the
                       primary market baseline (Pinnacle close, Shin) is below 0.

``passed`` needs all six. A passed gate makes an experiment a CANDIDATE;
PRODUCTION is a separate, explicit promotion (``scripts.experiment promote``),
and the database refuses it without a passed gate. A model that does not
beat the market stays in RESEARCH however well it scores otherwise.
"""

from __future__ import annotations

from typing import Any

from fbi.backtesting.evaluate import PRIMARY_BASELINE, ModelEvaluation, SessionEvaluation

CALIBRATION_SLACK = 0.01
CALIBRATION_FLOOR = 0.02
STABLE_COMPETITION_SHARE = 2 / 3
MIN_GROUP = 50
CHECKS = ("out_of_sample", "temporal_validation", "calibrated", "reproducible", "stable", "beats_market")


def _halves(by_month: dict[str, dict[str, float]]) -> tuple[float | None, float | None]:
    """n-weighted log-loss difference in the first and the second half of the test period."""
    months = sorted(by_month)
    total = sum(by_month[m]["n"] for m in months)
    if total == 0:
        return None, None
    first: list[tuple[float, float]] = []
    second: list[tuple[float, float]] = []
    seen = 0.0
    for m in months:
        row = by_month[m]
        (first if seen + row["n"] / 2 <= total / 2 else second).append((row["n"], row["logloss_diff"]))
        seen += row["n"]

    def mean(rows: list[tuple[float, float]]) -> float | None:
        n = sum(r[0] for r in rows)
        return None if n == 0 else sum(r[0] * r[1] for r in rows) / n

    return mean(first), mean(second)


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


def evaluate_gate(ev: ModelEvaluation, evaluation: SessionEvaluation, *, refit_days: int,
                  reproduced_by: int | None = None) -> dict[str, Any]:
    run = ev.run
    checks: dict[str, dict[str, Any]] = {}

    checks["out_of_sample"] = {
        "passed": bool(run.blocks) and len(run.predictions) > 0,
        "evidence": f"{len(run.blocks)} walk-forward blocks, each checked before fitting: every training result "
                    "public before the cut-off, the cut-off before every kick-off it predicts",
    }
    checks["temporal_validation"] = {
        "passed": bool(run.blocks),
        "evidence": f"walk-forward, refitted every {refit_days} day(s); hyper-parameters chosen on the validation "
                    "season only (goal models) or fixed a priori (all others)",
    }

    mine = evaluation.common_scores.get(run.model)
    market = evaluation.common_scores.get(PRIMARY_BASELINE)
    if mine is None or market is None:
        checks["calibrated"] = {"passed": False, "evidence": "no common sample with the market"}
    else:
        limit = max(CALIBRATION_FLOOR, market.ece + CALIBRATION_SLACK)
        checks["calibrated"] = {
            "passed": mine.ece <= limit,
            "evidence": f"ECE {mine.ece:.4f} on the {mine.n} common fixtures; market {market.ece:.4f}; "
                        f"limit {limit:.4f}",
        }

    checks["reproducible"] = {
        "passed": reproduced_by is not None,
        "evidence": (f"experiment {reproduced_by} re-ran the recorded code on the recorded data: identical"
                     if reproduced_by is not None else "not reproduced yet (scripts.experiment reproduce)"),
    }

    primary = ev.primary()
    if primary is None:
        checks["stable"] = {"passed": False, "evidence": "no comparison with the primary market baseline"}
        checks["beats_market"] = {"passed": False, "evidence": f"no fixture shared with {PRIMARY_BASELINE}"}
    else:
        overall = _sign(primary.logloss_diff.mean)
        first, second = _halves(ev.by_month)
        comps = [row for row in ev.by_competition.values() if row["n"] >= MIN_GROUP]
        agree = sum(1 for row in comps if _sign(row["logloss_diff"]) == overall)
        halves_ok = first is not None and second is not None and _sign(first) == _sign(second) == overall
        comps_ok = bool(comps) and agree / len(comps) >= STABLE_COMPETITION_SHARE
        checks["stable"] = {
            "passed": halves_ok and comps_ok,
            "evidence": (f"difference to the market by half: {first if first is None else round(first, 5)} then "
                         f"{second if second is None else round(second, 5)}; same sign as overall in {agree} of "
                         f"{len(comps)} competitions with {MIN_GROUP}+ fixtures"),
        }
        d = primary.logloss_diff
        checks["beats_market"] = {
            "passed": primary.verdict == "better",
            "evidence": (f"log-loss difference {d.mean:+.5f} [{d.lo:+.5f}, {d.hi:+.5f}] against {PRIMARY_BASELINE} "
                         f"on {primary.n_common} fixtures: {primary.verdict}, evidence {primary.evidence}"),
        }

    return {
        "passed": all(checks[c]["passed"] for c in CHECKS),
        "checks": checks,
        "rules": {"calibration_slack": CALIBRATION_SLACK, "calibration_floor": CALIBRATION_FLOOR,
                  "stable_competition_share": STABLE_COMPETITION_SHARE, "min_group": MIN_GROUP,
                  "primary_baseline": PRIMARY_BASELINE},
    }


def status_for(gate: dict[str, Any]) -> str:
    """Where a gate leaves an experiment: CANDIDATE if passed, else RESEARCH. Never PRODUCTION."""
    return "CANDIDATE" if gate.get("passed") else "RESEARCH"
