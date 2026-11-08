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
    Q2 (C4)      goals and both-teams-score: the share of «under» / «no» flagged, and the model's lean against the market
                 (mean p_model - p_market) by competition, newcomers apart. Proposal: a lean of 3 pp or more in a
                 competition with >= 300 selections is reported as a bias to correct in the model, through its gate.
    Q3 (C3, S3)  the odds cap with the calibrated probability: each band of odds alone, out of sample. Proposal: the cap
                 of 3.00 rises to a band's top only if that band has >= 300 selections, an interval wholly above 0 and a
                 mean closing-line value >= 0.
    Q4 (C3)      the big disagreements (p_model - p_market >= 15 pp) by how the market moved after the price was taken
                 (closing-line value, strong when |CLV| >= 10 %). Proposal: a disagreement the market moved against
                 strongly becomes a visible risk if its interval lies wholly below that of the others.
    Q5 (C5)      the price: the return at the price taken against the return at the market's fair price (1 / p_market)
                 on the calibrated rule. Proposal: the card says how much of the value is the price alone.

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
), seasons AS (
    -- the teams of each competition and season, to tell a newcomer (absent from the season before)
    SELECT DISTINCT cs.competition_id, cs.season, t.team_id
      FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
     CROSS JOIN LATERAL (VALUES (f.home_team_id), (f.away_team_id)) t(team_id)
     WHERE cs.competition_id IN (SELECT DISTINCT cid FROM last)
), newcomers AS (
    SELECT s.competition_id, s.season, s.team_id
      FROM seasons s
      JOIN (SELECT DISTINCT competition_id, season FROM seasons) prev
        ON prev.competition_id = s.competition_id AND prev.season = s.season - 1
      LEFT JOIN seasons was
        ON was.competition_id = s.competition_id AND was.season = s.season - 1 AND was.team_id = s.team_id
     WHERE was.team_id IS NULL
)
SELECT l.*, (nh.team_id IS NOT NULL OR na.team_id IS NOT NULL) AS newcomer
  FROM last l
  LEFT JOIN newcomers nh ON nh.competition_id = l.cid AND nh.season = l.season AND nh.team_id = l.home_team_id
  LEFT JOIN newcomers na ON na.competition_id = l.cid AND na.season = l.season AND na.team_id = l.away_team_id
 WHERE l.result_status IN ('win', 'loss') AND l.p_market > 0 AND l.p_market < 1 AND l.p_model > 0 AND l.p_model < 1
 ORDER BY l.kickoff_at, l.pick_id
"""


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


def q2_direction(sels: Sequence[Sel]) -> dict[str, Any]:
    low = {"OU": "Under", "BTTS": "No"}
    out: dict[str, Any] = {}
    for market, side in low.items():
        group = [s for s in sels if s.obs.market_key == market]
        if not group:
            continue
        by_comp: dict[tuple[str, bool], list[Sel]] = defaultdict(list)
        for s in group:
            by_comp[(s.competition, s.newcomer)].append(s)
        rows = []
        for (comp, newcomer), g in sorted(by_comp.items(), key=lambda kv: -len(kv[1])):
            lean = float(np.mean([(s.obs.p_model - s.obs.p_market) * (1 if s.selection == side else -1) for s in g]))
            rows.append({"competition": comp, "newcomer": newcomer, "n": len(g), "enough": len(g) >= MIN_N,
                         "share_low": round(sum(1 for s in g if s.selection == side) / len(g), 4),
                         "lean_low_pp": round(100 * lean, 2), "bias": len(g) >= MIN_N and lean >= LEAN})
        out[market] = {"n": len(group), "share_low": round(sum(1 for s in group if s.selection == side) / len(group), 4),
                       "by_competition": rows}
    return out


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
    share = None
    if at_price.get("roi") is not None and at_fair.get("roi") is not None and at_price["roi"] != 0:
        share = round((at_price["roi"] - at_fair["roi"]) / abs(at_price["roi"]), 4)
    return {"at_price_taken": at_price, "at_fair_price": at_fair, "price_part_of_return": share}


def research(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sels = calibrate_out_of_sample(rows)
    scored = [s for s in sels if s.p_cal is not None]
    return {"selections": len(sels), "scored_out_of_sample": len(scored), "min_n": MIN_N, "reps": REPS, "seed": SEED,
            "q1": q1_probabilities(sels), "q2": q2_direction(sels), "q3": q3_bands(scored), "q4": q4_moves(sels),
            "q5": q5_price(scored)}


def _r(r: Mapping[str, Any]) -> str:
    if not r.get("n"):
        return "n=0"
    ci = r.get("ci")
    band = f" [{ci[0]:+.1%}, {ci[1]:+.1%}]" if ci else " (muestra corta)"
    clv = f" CLV {r['clv']:+.1%}" if r.get("clv") is not None else ""
    return f"n={r['n']:,} ROI {r['roi']:+.1%}{band}{clv}"


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
    for m, q in f["q2"].items():
        print(f"  {m}: {q['share_low']:.0%} del lado bajo")
        for c in q["by_competition"][:15]:
            flag = " SESGO" if c["bias"] else ""
            print(f"    {c['competition'][:32]:32} {'recién llegados' if c['newcomer'] else '':16} n={c['n']:5,} "
                  f"lado bajo {c['share_low']:.0%} inclinación {c['lean_low_pp']:+.1f} pp{flag}")
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
          f"{_r(q5['at_fair_price'])} · parte del rendimiento que es solo precio: {q5['price_part_of_return']}")


def load(conn: psycopg.Connection[Any], *, since: datetime, cutoff: datetime) -> list[dict[str, Any]]:
    return list(conn.execute(SQL, {"since": since, "cutoff": cutoff}).fetchall())


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
    figures = research(rows)
    if args.json:
        print(json.dumps(figures, ensure_ascii=False, indent=2,
                         default=lambda x: None if isinstance(x, float) and math.isnan(x) else str(x)))
    else:
        report(figures)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
