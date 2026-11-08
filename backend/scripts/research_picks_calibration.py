"""The evidence the PICKS plan asks for before anything changes (plan PICKS, F2: C1 to C5). Read-only research.

    python -m scripts.research_picks_calibration                 # every settled selection since the engine began
    python -m scripts.research_picks_calibration --days 60
    python -m scripts.research_picks_calibration --json > f2.json

THE SAMPLE. The settled shadow picks, one per selection and model: the LAST pick before kick-off of each (match, market,
selection, line, model), won or lost (pushes, voids and half results are left out) - the population and the reading of
``fbi.intel.calibration`` (``SETTLED_SQL``), with the competition, the season, the line and whether a team of the
match is new in its competition this season.

THE CALIBRATED PROBABILITY, OUT OF SAMPLE. ``cal-logit2-v1`` refitted the way production validates it: each Bogotá day D
is scored by a fit on the selections settled before D began (28-day window, at least 500, the same ``fit_params`` and
``apply_params``). No selection is ever scored by a fit that saw it.

THE CRITERIA, FIXED BEFORE LOOKING (as in P5). A figure counts with at least 300 settled selections in its group
(``MIN_N``); every return has a 95 % interval by bootstrap over MATCHES (the selections of one match win or lose
together; 1,000 resamples, seed 20261108). A proposal follows only from the interval, never from the point:

    Q1 (C1, C2)  per market: the raw and the calibrated probability against the hit rate (mean and ECE), and the return of
                 the two rules - the board's (raw EV >= 5 %, edge >= 2 pp, odds 1.50-5.00) and Intelligence's
                 (calibrated EV >= 2 %). Proposal: show the calibrated probability where its ECE is lower than the raw
                 one's; a rule whose interval lies wholly below 0 does not publish.
    Q2 (C4)      goals and both-teams-score. The symptom: the share of «under» / «no» among the flagged selections. The
                 diagnosis, on EVERY production forecast of a finished match, not only the flagged ones (a flagged pick
                 has p_model > p_market by construction): the last forecast of each model before kick-off for «under
                 2.5» and «no» against the last de-vigged consensus before kick-off and what the match did, by
                 competition, newcomers apart. Proposal: a lean (mean p_model - p_market) of 3 pp or more either way,
                 with >= 300 matches, an interval that excludes 0 and the model further from what happened than the
                 market, is reported as a bias to correct in the model, through its gate.
    Q3 (C3, S3)  the odds cap with the calibrated probability: each band of odds alone, out of sample. Proposal: the cap
                 of 3.00 rises to a band's top only if that band has >= 300 selections, an interval wholly above 0 and a
                 mean closing-line value >= 0.
    Q4 (C3)      the big disagreements (p_model - p_market >= 15 pp) by how the market moved after the price was taken
                 (closing-line value, strong when |CLV| >= 10 %). Proposal: a disagreement the market moved against
                 strongly becomes a visible risk if its interval lies wholly below that of the others.
    Q5 (C5)      the price: the return at the price taken against the return at the market's fair price (1 / p_market)
                 on the calibrated rule, and the difference in points. Proposal: the card says how many points of the
                 return come from the price alone (a share of the return would flip its meaning when it is negative).

It changes nothing and needs no provider call. Its figures go to docs/owner/PICKS_F2_EVIDENCIA.md.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import day_start, local_day
from fbi.core.config import settings
from fbi.intel import calibration, stats

READ_ONLY = "-c default_transaction_read_only=on -c statement_timeout=600000 -c TimeZone=UTC"
MIN_N = 300
REPS = 1000
SEED = 20261108
BOARD_EV, BOARD_EDGE, BOARD_ODDS = 0.05, 0.02, (1.50, 5.00)
CAL_EV = calibration.EV_RULE
BANDS: tuple[tuple[float, float], ...] = ((1.0, 1.7), (1.7, 2.5), (2.5, 3.0), (3.0, 3.5), (3.5, 4.0), (4.0, 5.0),
                                          (5.0, 1000.0))
BIG_GAP = 0.15
STRONG_MOVE = 0.10
LEAN = 0.03

NEWCOMERS = """seasons AS (
    -- the teams of each competition and season, to tell a newcomer (absent from the season before)
    SELECT DISTINCT cs.competition_id, cs.season, t.team_id
      FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
     CROSS JOIN LATERAL (VALUES (f.home_team_id), (f.away_team_id)) t(team_id)
     WHERE cs.competition_id IN (SELECT DISTINCT cid FROM {source})
), newcomers AS (
    SELECT s.competition_id, s.season, s.team_id
      FROM seasons s
      JOIN (SELECT DISTINCT competition_id, season FROM seasons) prev
        ON prev.competition_id = s.competition_id AND prev.season = s.season - 1
      LEFT JOIN seasons was
        ON was.competition_id = s.competition_id AND was.season = s.season - 1 AND was.team_id = s.team_id
     WHERE was.team_id IS NULL
)"""
"""A team that plays this season in a competition whose previous season is recorded, and did not play that one."""

SQL = """
WITH last AS (
    SELECT DISTINCT ON (p.fixture_id, p.market_key, p.selection, p.line, r.name)
           p.id AS pick_id, p.fixture_id, f.kickoff_at, p.market_key, p.selection, p.line::float8 AS line,
           r.name AS model_name, p.p_calibrated::float8 AS p_model, p.p_market_fair::float8 AS p_market,
           p.market_odds::float8 AS odds, pr.result_status, pr.settled_at, lv.lv_devigged::float8 AS clv,
           c.name AS competition, cs.competition_id AS cid, cs.season,
           f.home_team_id, f.away_team_id
      FROM picks.picks p
      JOIN core.fixtures f ON f.id = p.fixture_id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
      JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry r ON r.id = v.model_id
      JOIN picks.pick_results pr ON pr.pick_id = p.id
      LEFT JOIN picks.pick_line_value lv ON lv.pick_id = p.id
     WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(cutoff)s
       AND p.created_at < f.kickoff_at AND pr.settled_at IS NOT NULL AND pr.settled_at < %(cutoff)s
     ORDER BY p.fixture_id, p.market_key, p.selection, p.line, r.name, p.created_at DESC, p.id DESC
), {newcomers}
SELECT l.*, (nh.team_id IS NOT NULL OR na.team_id IS NOT NULL) AS newcomer
  FROM last l
  LEFT JOIN newcomers nh ON nh.competition_id = l.cid AND nh.season = l.season AND nh.team_id = l.home_team_id
  LEFT JOIN newcomers na ON na.competition_id = l.cid AND na.season = l.season AND na.team_id = l.away_team_id
 WHERE l.result_status IN ('win', 'loss') AND l.p_market > 0 AND l.p_market < 1 AND l.p_model > 0 AND l.p_model < 1
 ORDER BY l.kickoff_at, l.pick_id
""".replace("{newcomers}", NEWCOMERS.format(source="last"))

GOALS_SQL = """
WITH f AS (
    SELECT f.id AS fixture_id, f.kickoff_at, c.name AS competition, cs.competition_id AS cid, cs.season,
           f.home_team_id, f.away_team_id, r.reg_goals_home, r.reg_goals_away
      FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
      JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(cutoff)s AND upper(f.status_short) IN ('FT', 'AET', 'PEN')
       AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
), sides(market_key, selection, line) AS (
    VALUES ('OU', 'Under', 2.5::numeric), ('BTTS', 'No', 0::numeric)
), model AS (
    -- each model's last real-time forecast before kick-off (the engine's own reading: p_calibrated, no backtest)
    SELECT DISTINCT ON (p.fixture_id, v.model_id, p.market_key)
           p.fixture_id, mr.name AS model_name, p.market_key, p.p_calibrated::float8 AS p_model
      FROM f
      JOIN models.predictions p ON p.fixture_id = f.fixture_id
      JOIN sides s ON s.market_key = p.market_key AND s.selection = p.selection AND s.line = p.line
      JOIN models.model_versions v ON v.id = p.model_version_id
      JOIN models.model_registry mr ON mr.id = v.model_id
     WHERE p.backtest_session_id IS NULL AND p.data_cutoff_ts < f.kickoff_at AND p.created_at < f.kickoff_at
     ORDER BY p.fixture_id, v.model_id, p.market_key, p.data_cutoff_ts DESC, p.id DESC
), market AS (
    -- the last de-vigged consensus before kick-off, with the engine's method
    SELECT f.fixture_id, s.market_key, k.p_market
      FROM f CROSS JOIN sides s
     CROSS JOIN LATERAL (
        SELECT mc.p_fair::float8 AS p_market FROM market.market_consensus mc
         WHERE mc.fixture_id = f.fixture_id AND mc.market_key = s.market_key AND mc.selection = s.selection
           AND mc.line = s.line AND mc.devig_method = %(devig)s AND mc.as_of < f.kickoff_at
         ORDER BY mc.as_of DESC LIMIT 1) k
), {newcomers}
SELECT m.fixture_id, m.model_name, m.market_key, f.competition, m.p_model, k.p_market,
       CASE WHEN m.market_key = 'OU' THEN f.reg_goals_home + f.reg_goals_away < 2.5
            ELSE NOT (f.reg_goals_home > 0 AND f.reg_goals_away > 0) END AS low,
       (nh.team_id IS NOT NULL OR na.team_id IS NOT NULL) AS newcomer
  FROM model m
  JOIN market k ON k.fixture_id = m.fixture_id AND k.market_key = m.market_key
  JOIN f ON f.fixture_id = m.fixture_id
  LEFT JOIN newcomers nh ON nh.competition_id = f.cid AND nh.season = f.season AND nh.team_id = f.home_team_id
  LEFT JOIN newcomers na ON na.competition_id = f.cid AND na.season = f.season AND na.team_id = f.away_team_id
 WHERE m.p_model > 0 AND m.p_model < 1 AND k.p_market > 0 AND k.p_market < 1
 ORDER BY m.fixture_id, m.market_key, m.model_name
""".replace("{newcomers}", NEWCOMERS.format(source="f"))
"""Q2's diagnosis: every finished match with a forecast and a market for «under 2.5» and «no» (both teams to score)."""


@dataclass(frozen=True, slots=True)
class Sel:
    """One settled selection, with its out-of-sample calibrated probability (None before a fit was possible)."""

    obs: calibration.Obs
    selection: str
    line: float
    competition: str
    newcomer: bool
    p_cal: float | None

    @property
    def pnl(self) -> float:
        return self.obs.odds - 1 if self.obs.y == 1 else -1.0

    @property
    def pnl_fair(self) -> float:
        return 1 / self.obs.p_market - 1 if self.obs.y == 1 else -1.0


def to_obs(r: Mapping[str, Any]) -> calibration.Obs:
    return calibration.Obs(int(r["pick_id"]), int(r["fixture_id"]), r["kickoff_at"], r["settled_at"],
                           str(r["market_key"]), str(r["model_name"]), float(r["p_model"]), float(r["p_market"]),
                           float(r["odds"]), 1.0 if r["result_status"] == "win" else 0.0,
                           None if r["clv"] is None else float(r["clv"]))


def calibrate_out_of_sample(rows: Sequence[Mapping[str, Any]], *, method: str = "logit2",
                            min_train: int = calibration.MIN_TRAIN) -> list[Sel]:
    """Each Bogotá day scored by a fit, per (market, model), on what was settled before the day began."""
    obs = [to_obs(r) for r in rows]
    groups: dict[tuple[str, str], list[calibration.Obs]] = defaultdict(list)
    for o in obs:
        groups[(o.market_key, o.model_name)].append(o)
    p_cal: dict[int, float] = {}
    for group in groups.values():
        by_day: dict[date, list[calibration.Obs]] = defaultdict(list)
        for o in group:
            by_day[local_day(o.kickoff_at)].append(o)
        for d in sorted(by_day):
            train = calibration.train_set(group, cutoff=day_start(d))
            if len(train) < min_train:
                continue
            params = calibration.fit_params(method, train)
            for o in by_day[d]:
                p = calibration.apply_params(method, params, o.p_model, o.p_market)
                if p is not None:
                    p_cal[o.pick_id] = p
    return [Sel(o, str(r["selection"]), float(r["line"]), str(r["competition"]), bool(r["newcomer"]),
                p_cal.get(o.pick_id)) for o, r in zip(obs, rows, strict=True)]


def cluster_ci(values: np.ndarray, groups: np.ndarray, *, reps: int = REPS, seed: int = SEED) -> list[float]:
    """95 % interval of a mean by resampling whole matches: per-match sums and counts, drawn with replacement.
    (``stats.bootstrap_mean_ci`` does the same per group with a mask, too slow for 10^5 selections.)"""
    _, idx = np.unique(groups, return_inverse=True)
    sums = np.bincount(idx, weights=values)
    counts = np.bincount(idx).astype(np.float64)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, sums.size, size=(reps, sums.size))
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


def roi(sample: Sequence[Sel], pnl: Callable[[Sel], float] = lambda s: s.pnl) -> dict[str, Any]:
    """Mean return per unit with its 95 % interval by bootstrap over matches; null below ``MIN_N``."""
    n = len(sample)
    out: dict[str, Any] = {"n": n, "matches": len({s.obs.fixture_id for s in sample}), "enough": n >= MIN_N}
    if not n:
        return out | {"roi": None, "ci": None, "clv": None}
    values = np.array([pnl(s) for s in sample])
    clvs = [s.obs.clv for s in sample if s.obs.clv is not None]
    out["roi"] = round(float(values.mean()), 4)
    out["ci"] = cluster_ci(values, np.array([s.obs.fixture_id for s in sample])) if n >= MIN_N else None
    out["clv"] = round(float(np.mean(clvs)), 4) if clvs else None
    out["hit"] = round(float(np.mean([s.obs.y for s in sample])), 4)
    return out


def below_zero(r: Mapping[str, Any]) -> bool:
    return bool(r.get("ci")) and r["ci"][1] < 0


def above_zero(r: Mapping[str, Any]) -> bool:
    return bool(r.get("ci")) and r["ci"][0] > 0


def board_rule(s: Sel) -> bool:
    ev = s.obs.p_model * s.obs.odds - 1
    return (ev >= BOARD_EV and s.obs.p_model - s.obs.p_market >= BOARD_EDGE
            and BOARD_ODDS[0] <= s.obs.odds <= BOARD_ODDS[1])


def cal_rule(s: Sel) -> bool:
    return s.p_cal is not None and s.p_cal * s.obs.odds - 1 >= CAL_EV


def q1_probabilities(sels: Sequence[Sel]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for market in sorted({s.obs.market_key for s in sels}):
        group = [s for s in sels if s.obs.market_key == market and s.p_cal is not None]
        if not group:
            continue
        y = np.array([s.obs.y for s in group])
        raw = np.array([s.obs.p_model for s in group])
        cal = np.array([s.p_cal for s in group], dtype=float)
        mkt = np.array([s.obs.p_market for s in group])
        board, intel = roi([s for s in group if board_rule(s)]), roi([s for s in group if cal_rule(s)])
        ece_raw, ece_cal = stats.ece(y, raw), stats.ece(y, cal)
        out[market] = {
            "n": len(group), "enough": len(group) >= MIN_N, "hit": round(float(y.mean()), 4),
            "p_raw": round(float(raw.mean()), 4), "p_cal": round(float(cal.mean()), 4),
            "p_market": round(float(mkt.mean()), 4), "ece_raw": round(ece_raw, 4), "ece_cal": round(ece_cal, 4),
            "ece_market": round(stats.ece(y, mkt), 4), "board_rule": board, "calibrated_rule": intel,
            "proposal": {
                "show_calibrated": len(group) >= MIN_N and ece_cal < ece_raw,
                "board_rule_does_not_publish": below_zero(board),
                "calibrated_rule_does_not_publish": below_zero(intel),
            },
        }
    return out


@dataclass(frozen=True, slots=True)
class Forecast:
    """One model's last forecast before kick-off of «under 2.5» or «no» (both teams to score), its market and the match."""

    fixture_id: int
    market_key: str
    model_name: str
    competition: str
    newcomer: bool
    p_model: float
    p_market: float
    low: bool


def to_forecasts(rows: Sequence[Mapping[str, Any]]) -> list[Forecast]:
    return [Forecast(int(r["fixture_id"]), str(r["market_key"]), str(r["model_name"]), str(r["competition"]),
                     bool(r["newcomer"]), float(r["p_model"]), float(r["p_market"]), bool(r["low"])) for r in rows]


def lean(group: Sequence[Forecast]) -> dict[str, Any]:
    """How far the model leans from the market toward the low side (+) or the high side (-), and who is closer to what
    the matches did. A bias needs ``MIN_N`` matches, a lean of ``LEAN`` or more whose interval excludes 0, and the
    model further from the observed frequency than the market."""
    n = len(group)
    diffs = np.array([f.p_model - f.p_market for f in group], dtype=np.float64)
    observed = float(np.mean([1.0 if f.low else 0.0 for f in group]))
    p_model = float(np.mean([f.p_model for f in group]))
    p_market = float(np.mean([f.p_market for f in group]))
    ci = cluster_ci(diffs, np.array([f.fixture_id for f in group])) if n >= MIN_N else None
    lean_pp = 100 * float(diffs.mean())
    model_gap, market_gap = p_model - observed, p_market - observed
    bias = (n >= MIN_N and abs(lean_pp) >= 100 * LEAN and ci is not None and (ci[0] > 0 or ci[1] < 0)
            and abs(model_gap) > abs(market_gap))
    return {"n": n, "enough": n >= MIN_N, "p_model": round(p_model, 4), "p_market": round(p_market, 4),
            "observed": round(observed, 4), "lean_pp": round(lean_pp, 2),
            "lean_ci_pp": None if ci is None else [round(100 * ci[0], 2), round(100 * ci[1], 2)],
            "model_gap_pp": round(100 * model_gap, 2), "market_gap_pp": round(100 * market_gap, 2),
            "direction": "low" if lean_pp > 0 else "high", "bias": bias}


def q2_direction(sels: Sequence[Sel], forecasts: Sequence[Forecast]) -> dict[str, Any]:
    """The symptom on the flagged selections, and the diagnosis on every forecast (see the module's note)."""
    low = {"OU": "Under", "BTTS": "No"}
    flagged: dict[str, Any] = {}
    for market, side in low.items():
        picked = [s for s in sels if s.obs.market_key == market]
        if picked:
            flagged[market] = {"n": len(picked),
                               "share_low": round(sum(1 for s in picked if s.selection == side) / len(picked), 4)}
    diagnosis: dict[str, Any] = {}
    for market in low:
        for model in sorted({fc.model_name for fc in forecasts if fc.market_key == market}):
            mine = [fc for fc in forecasts if fc.market_key == market and fc.model_name == model]
            by_comp: dict[tuple[str, bool], list[Forecast]] = defaultdict(list)
            for fc in mine:
                by_comp[(fc.competition, fc.newcomer)].append(fc)
            rows = [{"competition": comp, "newcomer": newcomer, **lean(g)}
                    for (comp, newcomer), g in sorted(by_comp.items(), key=lambda kv: -len(kv[1]))]
            diagnosis[f"{market}/{model}"] = {"overall": lean(mine), "by_competition": rows}
    return {"flagged": flagged, "forecasts": diagnosis}


def q3_bands(sels: Sequence[Sel]) -> list[dict[str, Any]]:
    taken = [s for s in sels if cal_rule(s)]
    out = []
    for lo, hi in BANDS:
        band = roi([s for s in taken if lo <= s.obs.odds < hi])
        clv_ok = band.get("clv") is not None and band["clv"] >= 0
        out.append({"band": [lo, hi], **band, "raise_cap_here": lo >= 3.0 and above_zero(band) and clv_ok})
    return out


def q4_moves(sels: Sequence[Sel]) -> dict[str, Any]:
    big = [s for s in sels if s.obs.p_model - s.obs.p_market >= BIG_GAP and s.obs.clv is not None]
    against = [s for s in big if s.obs.clv is not None and s.obs.clv <= -STRONG_MOVE]
    others = [s for s in big if s.obs.clv is not None and s.obs.clv > -STRONG_MOVE]
    a, o = roi(against), roi(others)
    risk = bool(a.get("ci") and o.get("ci") and a["ci"][1] < o["ci"][0])
    return {"gap_pp": 100 * BIG_GAP, "strong_move": STRONG_MOVE, "moved_against": a, "others": o,
            "becomes_visible_risk": risk}


def q5_price(sels: Sequence[Sel]) -> dict[str, Any]:
    taken = [s for s in sels if cal_rule(s)]
    at_price, at_fair = roi(taken), roi(taken, lambda s: s.pnl_fair)
    gain = None
    if at_price.get("roi") is not None and at_fair.get("roi") is not None:
        gain = round(100 * (at_price["roi"] - at_fair["roi"]), 2)
    return {"at_price_taken": at_price, "at_fair_price": at_fair, "price_gain_pp": gain}


def research(rows: Sequence[Mapping[str, Any]], goals_rows: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    sels = calibrate_out_of_sample(rows)
    scored = [s for s in sels if s.p_cal is not None]
    forecasts = to_forecasts(goals_rows)
    return {"selections": len(sels), "scored_out_of_sample": len(scored), "forecasts": len(forecasts), "min_n": MIN_N,
            "reps": REPS, "seed": SEED, "q1": q1_probabilities(sels), "q2": q2_direction(sels, forecasts),
            "q3": q3_bands(scored), "q4": q4_moves(sels), "q5": q5_price(scored)}


def _r(r: Mapping[str, Any]) -> str:
    if not r.get("n"):
        return "n=0"
    ci = r.get("ci")
    band = f" [{ci[0]:+.1%}, {ci[1]:+.1%}]" if ci else " (muestra corta)"
    clv = f" CLV {r['clv']:+.1%}" if r.get("clv") is not None else ""
    return f"n={r['n']:,} ROI {r['roi']:+.1%}{band}{clv}"


def _lean(q: Mapping[str, Any]) -> str:
    ci = q.get("lean_ci_pp")
    band = f" [{ci[0]:+.1f}, {ci[1]:+.1f}]" if ci else " (muestra corta)"
    flag = " SESGO" if q["bias"] else ""
    return (f"n={q['n']:,} modelo {q['p_model']:.1%} · mercado {q['p_market']:.1%} · real {q['observed']:.1%} · "
            f"inclinación {q['lean_pp']:+.1f} pp{band}{flag}")


def report(f: Mapping[str, Any]) -> None:
    print(f"F2 · {f['selections']:,} selecciones liquidadas, {f['scored_out_of_sample']:,} con calibrada fuera de muestra"
          f" (criterio: n >= {f['min_n']}, IC 95 % por bootstrap de partidos, {f['reps']} remuestras)\n")
    print("Q1 · probabilidad cruda y calibrada por mercado")
    for m, q in f["q1"].items():
        print(f"  {m:5} n={q['n']:,} acierto {q['hit']:.1%} · cruda {q['p_raw']:.1%} (ECE {q['ece_raw']:.3f}) · "
              f"calibrada {q['p_cal']:.1%} (ECE {q['ece_cal']:.3f}) · mercado {q['p_market']:.1%}")
        print(f"        regla del tablero {_r(q['board_rule'])} · regla calibrada {_r(q['calibrated_rule'])}")
        print(f"        propuesta {q['proposal']}")
    print("\nQ2 · dirección en goles y ambos marcan")
    for m, q in f["q2"]["flagged"].items():
        print(f"  señaladas {m}: {q['share_low']:.0%} del lado bajo (n={q['n']:,})")
    for key, q in f["q2"]["forecasts"].items():
        print(f"  {key}: {_lean(q['overall'])}")
        for c in q["by_competition"][:15]:
            who = "recién llegados" if c["newcomer"] else ""
            print(f"    {c['competition'][:32]:32} {who:16} {_lean(c)}")
    print("\nQ3 · tramos de cuota con la regla calibrada (fuera de muestra)")
    for b in f["q3"]:
        flag = " -> sube el tope" if b["raise_cap_here"] else ""
        print(f"  {b['band'][0]:.2f}-{b['band'][1]:.2f}: {_r(b)}{flag}")
    q4 = f["q4"]
    print(f"\nQ4 · desacuerdos de {q4['gap_pp']:.0f} pp o más: el mercado se movió en contra (CLV <= "
          f"-{q4['strong_move']:.0%}) {_r(q4['moved_against'])} · los demás {_r(q4['others'])} · "
          f"riesgo visible: {q4['becomes_visible_risk']}")
    q5 = f["q5"]
    print(f"\nQ5 · regla calibrada al precio tomado {_r(q5['at_price_taken'])} · al precio justo "
          f"{_r(q5['at_fair_price'])} · puntos que vienen solo del precio: {q5['price_gain_pp']}")


def load(conn: psycopg.Connection[Any], *, since: datetime, cutoff: datetime) -> list[dict[str, Any]]:
    return list(conn.execute(SQL, {"since": since, "cutoff": cutoff}).fetchall())


def load_goals(conn: psycopg.Connection[Any], *, since: datetime, cutoff: datetime) -> list[dict[str, Any]]:
    from fbi.picks.engine import CONSENSUS_METHOD

    return list(conn.execute(GOALS_SQL, {"since": since, "cutoff": cutoff,
                                         "devig": CONSENSUS_METHOD.value}).fetchall())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=None, help="only matches of the last N days (default: all)")
    parser.add_argument("--json", action="store_true", help="print the figures as JSON")
    args = parser.parse_args(argv)
    from fbi.core.clock import now as clock_now

    cutoff = clock_now()
    since = cutoff - timedelta(days=args.days) if args.days else datetime(2000, 1, 1, tzinfo=cutoff.tzinfo)
    with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY, row_factory=dict_row) as conn:
        rows = load(conn, since=since, cutoff=cutoff)
        goals = load_goals(conn, since=since, cutoff=cutoff)
    figures = research(rows, goals)
    if args.json:
        print(json.dumps(figures, ensure_ascii=False, indent=2,
                         default=lambda x: None if isinstance(x, float) and math.isnan(x) else str(x)))
    else:
        report(figures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
