"""PM-12-03 (IA-157): the LAB's model portfolio, one preregistered protocol per line - OFF the server.

    python -m scripts.lab_portfolio <lab-export-v2 folder> --out <result.json> [--preds <predictions.parquet>]

One walk-forward pass, every Monday 00:00 UTC and every test competition, computes the 1X2 of each match of that ISO week with:

* B0, the reference: the arithmetic of the model in force (``fbi.competitions.scenario_store._fit``: Dixon-Coles with the promoted
  spec, 730 days of the same competition, results known 3 h after kick-off; Poisson when the Dixon-Coles correction is invalid for a
  match, as ``fit_scores`` does);
* C26 (``PM-12-03-OP26``): B0 with its home term re-estimated on the last 365 days (half-life 120 days, the rest of B0 fixed, a normal
  prior of sd 0.10 around B0's home);
* C27 and its placebo C27p (``PM-12-03-OP27``, segment M only): team strengths fitted by cross-entropy to the closing no-margin
  probabilities of the PREVIOUS 365 days' matches (an ordered logit on h + s_home - s_away, penalty 1.0); the placebo permutes those
  probabilities between matches of the same league and ISO week;
* C30a/b/c (``PM-12-03-OP30``): Poisson without the correction; Elo (elo-v2.0 over every exported match in order, frozen at the
  Monday) + ``fbi.models.elo_ologit``; their equal log pool with B0;
* the conformal sets of ``PM-12-03-OP29`` on B0 (split conformal, score 1 - p, alpha 0.10, the previous 13 weeks calibrate).

Every comparison is the paired per-match log loss difference with a bootstrap of whole ISO weeks. OP-28 (E4/E6) is not touched.
A pass changes nothing: at most a candidate for the model gate, never production without the owner's signature.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize

KEYS = ("PM-12-03-OP26", "PM-12-03-OP27", "PM-12-03-OP29", "PM-12-03-OP30")
TEST_FROM = datetime(2022, 7, 1, tzinfo=UTC)
TEST_TO = datetime(2026, 11, 21, tzinfo=UTC)  # matches up to 20-nov included
MIN_SEASON_MATCHES = 150
MIN_SEASONS = 2
HA_DAYS, HA_HALF_LIFE, HA_SD = 365, 120.0, 0.10
MK_DAYS, MK_XI, MK_PENALTY = 365, 0.002, 1.0
MK_FROM, MK_TO = datetime(2023, 8, 1, tzinfo=UTC), datetime(2025, 6, 1, tzinfo=UTC)
CONF_ALPHA, CONF_WEEKS = 0.10, 13
REPS = 2000
EPS = 1e-12


def onex2(m: NDArray[np.float64]) -> NDArray[np.float64]:
    """(home, draw, away) of a score matrix (rows home goals), renormalised over the matrix."""
    tot = float(m.sum())
    return np.array([np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()]) / tot


def pool(p: NDArray[np.float64], q: NDArray[np.float64]) -> NDArray[np.float64]:
    g = np.sqrt(np.clip(p, EPS, 1) * np.clip(q, EPS, 1))
    return g / g.sum()


# ── C26: the home term, re-estimated ───────────────────────────────────────────────────────────────────────────────────────


def home_term(model: Any, recent: Sequence[tuple[int, int, int, float]], *, prior_sd: float = HA_SD) -> float:
    """MAP of the home term with the rest of ``model`` fixed: Poisson likelihood of the home goals of ``recent`` ((home, away,
    home goals, weight)) and a normal prior around the model's own home. Newton on a concave one-dimensional problem."""
    h0 = float(model.home)
    rows = [(model.index[h], model.index[a], g, w) for h, a, g, w in recent if model.knows(h) and model.knows(a)]
    if not rows:
        return h0
    hi = np.array([r[0] for r in rows])
    ai = np.array([r[1] for r in rows])
    g = np.array([r[2] for r in rows], dtype=np.float64)
    w = np.array([r[3] for r in rows], dtype=np.float64)
    base = np.exp(model.mu + model.attack[hi] - model.defence[ai])
    h = h0
    for _ in range(50):
        lam = base * math.exp(h)
        grad = float((w * (g - lam)).sum()) - (h - h0) / prior_sd**2
        hess = -float((w * lam).sum()) - 1.0 / prior_sd**2
        step = grad / hess
        h -= step
        if abs(step) < 1e-10:
            break
    return h


# ── C27: strengths from market probabilities ───────────────────────────────────────────────────────────────────────────────


def _sig(x: NDArray[np.float64]) -> NDArray[np.float64]:
    return 1.0 / (1.0 + np.exp(-x))


def market_objective(theta: NDArray[np.float64], hi: NDArray[np.int64], ai: NDArray[np.int64], q: NDArray[np.float64],
                     w: NDArray[np.float64], penalty: float) -> tuple[float, NDArray[np.float64]]:
    """Weighted cross-entropy of the ordered logit against the market probabilities ``q`` (home, draw, away), and its gradient.
    ``theta``: n strengths, h, t1, log(t2 - t1). P(away) = sig(t1 - z), P(away or draw) = sig(t2 - z), z = h + s_home - s_away."""
    n = theta.size - 3
    s, h, t1 = theta[:n], float(theta[n]), float(theta[n + 1])
    t2 = t1 + math.exp(theta[n + 2])
    z = h + s[hi] - s[ai]
    a1, a2 = _sig(t1 - z), _sig(t2 - z)
    pa, pd, ph = np.clip(a1, EPS, 1), np.clip(a2 - a1, EPS, 1), np.clip(1 - a2, EPS, 1)
    loss = -float((w * (q[:, 0] * np.log(ph) + q[:, 1] * np.log(pd) + q[:, 2] * np.log(pa))).sum()) + penalty * float((s * s).sum())
    d1, d2 = a1 * (1 - a1), a2 * (1 - a2)
    g_t1 = -w * (q[:, 2] * d1 / pa - q[:, 1] * d1 / pd)
    g_t2 = -w * (q[:, 1] * d2 / pd - q[:, 0] * d2 / ph)
    g_z = -w * (-q[:, 2] * d1 / pa + q[:, 1] * (d1 - d2) / pd + q[:, 0] * d2 / ph)
    grad = np.zeros_like(theta)
    np.add.at(grad, hi, g_z)
    np.add.at(grad, ai, -g_z)
    grad[:n] += 2 * penalty * s
    grad[n] = g_z.sum()
    grad[n + 1] = g_t1.sum() + g_t2.sum()
    grad[n + 2] = g_t2.sum() * math.exp(theta[n + 2])
    return loss, grad


def market_fit(rows: Sequence[tuple[int, int, NDArray[np.float64], float]], *, penalty: float = MK_PENALTY
               ) -> tuple[dict[int, int], NDArray[np.float64]] | None:
    """Strengths, home term and thresholds fitted to market probabilities ((home, away, (p_home, p_draw, p_away), weight))."""
    teams = sorted({r[0] for r in rows} | {r[1] for r in rows})
    if len(teams) < 3 or len(rows) < 30:
        return None
    idx = {t: i for i, t in enumerate(teams)}
    hi = np.array([idx[r[0]] for r in rows], dtype=np.int64)
    ai = np.array([idx[r[1]] for r in rows], dtype=np.int64)
    q = np.array([r[2] for r in rows], dtype=np.float64)
    w = np.array([r[3] for r in rows], dtype=np.float64)
    start = np.concatenate([np.zeros(len(teams)), [0.3, -0.5, math.log(0.9)]])
    res = minimize(market_objective, start, args=(hi, ai, q, w, penalty), jac=True, method="L-BFGS-B", options={"maxiter": 500})
    return idx, np.asarray(res.x, dtype=np.float64)


def market_predict(fit: tuple[dict[int, int], NDArray[np.float64]], home: int, away: int) -> NDArray[np.float64] | None:
    idx, theta = fit
    if home not in idx or away not in idx:
        return None
    n = len(idx)
    z = theta[n] + theta[idx[home]] - theta[idx[away]]
    t1, t2 = theta[n + 1], theta[n + 1] + math.exp(theta[n + 2])
    a1, a2 = 1 / (1 + math.exp(-(t1 - z))), 1 / (1 + math.exp(-(t2 - z)))
    p = np.array([1 - a2, a2 - a1, a1])
    return np.clip(p, EPS, 1) / np.clip(p, EPS, 1).sum()


# ── conformal (OP-29) ──────────────────────────────────────────────────────────────────────────────────────────────────────


def conformal_q(scores: NDArray[np.float64], alpha: float = CONF_ALPHA) -> float | None:
    n = scores.size
    if n == 0:
        return None
    level = min(1.0, math.ceil((n + 1) * (1 - alpha)) / n)
    return float(np.quantile(scores, level, method="higher"))


# ── comparisons ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def paired(a: NDArray[np.float64], b: NDArray[np.float64], weeks: NDArray[np.int64], *, seed: int, level: float = 0.95,
           reps: int = REPS) -> dict[str, Any]:
    """Mean of a - b (per-match log losses) with its interval when whole ISO weeks are resampled; s and the detectable effect."""
    from scripts.lab_pm_common import block_bootstrap_mean

    d = a - b
    if d.size == 0:
        return {"n": 0}
    mean, lo, hi = block_bootstrap_mean(d, weeks, reps=reps, seed=seed, level=level)
    s = float(d.std(ddof=1)) if d.size > 1 else math.nan
    return {"n": int(d.size), "weeks": int(np.unique(weeks).size), "mean": mean, "ci": [lo, hi], "level": level, "s": s,
            "mde": 2.80 * s / math.sqrt(d.size) if d.size > 1 else None}


# ── the walk-forward pass ──────────────────────────────────────────────────────────────────────────────────────────────────


def market_probs(con: Any) -> dict[int, NDArray[np.float64]]:
    """Closing no-margin 1X2 from football-data: per bookmaker with the three prices, proportional, averaged over bookmakers.
    football-data's AVG and MAX columns are aggregates, not bookmakers: they are left out (a MAX "book" has a negative margin)."""
    rows = con.execute("""
        SELECT fixture_id, bookmaker_code, lower(selection) AS sel, odds_decimal
          FROM market_historical_odds WHERE price_kind = 'closing' AND market_key = '1X2' AND odds_decimal > 1
           AND upper(bookmaker_code) NOT IN ('AVG', 'MAX')
    """).fetchall()
    by: dict[tuple[int, str], dict[str, float]] = defaultdict(dict)
    for fid, book, sel, odds in rows:
        by[(int(fid), str(book))][_sel(sel)] = 1.0 / float(odds)
    acc: dict[int, list[NDArray[np.float64]]] = defaultdict(list)
    for (fid, _book), v in by.items():
        if set(v) == {"home", "draw", "away"}:
            p = np.array([v["home"], v["draw"], v["away"]])
            acc[fid].append(p / p.sum())
    return {fid: np.mean(ps, axis=0) for fid, ps in acc.items()}


def _sel(s: str) -> str:
    s = s.strip().lower()
    return {"1": "home", "h": "home", "home": "home", "x": "draw", "d": "draw", "draw": "draw", "2": "away", "a": "away",
            "away": "away"}.get(s, s)


def test_competitions(df: Any) -> list[int]:
    win = df[(df.ctype == "league") & (df.kickoff_at >= TEST_FROM) & (df.kickoff_at < TEST_TO)]
    per = win.groupby(["comp", "cs_id"]).size()
    good = per[per >= MIN_SEASON_MATCHES].reset_index().groupby("comp").size()
    return sorted(int(c) for c in good[good >= MIN_SEASONS].index)


def walk_forward(con: Any, *, xi: float, penalty: float, history_days: int, seed: int, log: Any = print) -> list[dict[str, Any]]:
    from fbi.competitions import scenario_store as ss
    from fbi.features.elo import EloBook
    from fbi.models.elo_ologit import OLogitObs, fit_ologit
    from fbi.models.goals import InvalidCorrectionError
    from scripts import lab_pm_common as lc

    df = con.sql(f"SELECT * FROM ({lc.MATCHES_SQL}) m ORDER BY kickoff_at, fixture_id").df()
    df["kickoff_at"] = [t.to_pydatetime().astimezone(UTC) for t in df["kickoff_at"]]
    comps = test_competitions(df)
    log(f"test competitions: {len(comps)}")
    market = market_probs(con)
    spec = ss.GoalSpec(xi, penalty, history_days)
    rng = np.random.default_rng(seed)

    # Elo over every exported match, in order; snapshots frozen at each Monday
    book = EloBook()
    elo_at: dict[datetime, dict[int, float]] = {}
    mondays = sorted({lc.monday_of(t) for t in df["kickoff_at"] if TEST_FROM - timedelta(days=history_days + 7) <= t < TEST_TO})
    rows_all = list(df.itertuples(index=False))
    pre_elo: dict[int, float] = {}
    mi = 0
    for r in rows_all:
        while mi < len(mondays) and mondays[mi] <= r.kickoff_at:
            elo_at[mondays[mi]] = dict(book.ratings)
            mi += 1
        u = book.update(int(r.home), int(r.away), int(r.gh), int(r.ga), neutral=bool(r.neutral))
        pre_elo[int(r.fixture_id)] = u.home_before - u.away_before
    while mi < len(mondays):
        elo_at[mondays[mi]] = dict(book.ratings)
        mi += 1

    by_comp: dict[int, list[Any]] = defaultdict(list)
    for r in rows_all:
        if int(r.comp) in comps:
            by_comp[int(r.comp)].append(r)
    out: list[dict[str, Any]] = []
    for comp in comps:
        games = by_comp[comp]
        weeks: dict[datetime, list[Any]] = defaultdict(list)
        for r in games:
            if TEST_FROM <= r.kickoff_at < TEST_TO:
                weeks[lc.monday_of(r.kickoff_at)].append(r)
        played = [ss.Played(r.kickoff_at, int(r.home), int(r.away), int(r.gh), int(r.ga), bool(r.neutral)) for r in games]
        for monday in sorted(weeks):
            train = [m for m in played if m.kickoff_at + ss.RESULT_AVAILABLE_AFTER < monday
                     and m.kickoff_at >= monday - timedelta(days=history_days)]
            if len(train) < ss.MIN_TRAIN:
                continue
            main = ss._fit(train, ss.MODEL, spec, monday)
            if main is None:
                continue
            second = None
            pois = ss._fit(train, ss.FALLBACK, spec, monday)
            recent = [(m.home, m.away, m.home_goals, 0.5 ** ((monday - m.kickoff_at).total_seconds() / 86400 / HA_HALF_LIFE))
                      for m in train if not m.neutral and m.kickoff_at >= monday - timedelta(days=HA_DAYS)]
            h26 = home_term(main, recent)
            c26_model = dataclasses.replace(main, home=h26)
            # Elo + ordered logit on the same training window, ratings as of each training match
            tr_rows = [r for r in games if r.kickoff_at + ss.RESULT_AVAILABLE_AFTER < monday
                       and r.kickoff_at >= monday - timedelta(days=history_days)]
            ol = None
            try:
                ol = fit_ologit([OLogitObs(pre_elo[int(r.fixture_id)], bool(r.neutral),
                                           2 if r.gh > r.ga else 1 if r.gh == r.ga else 0) for r in tr_rows])
            except ValueError:
                ol = None
            frozen = elo_at.get(monday, {})
            mk = mkp = None
            if comp in lc.MARKET_LEAGUES and MK_FROM <= monday < MK_TO:
                hist = [r for r in games if r.kickoff_at < monday and r.kickoff_at >= monday - timedelta(days=MK_DAYS)
                        and int(r.fixture_id) in market]
                rows = [(int(r.home), int(r.away), market[int(r.fixture_id)],
                         math.exp(-MK_XI * (monday - r.kickoff_at).total_seconds() / 86400)) for r in hist]
                mk = market_fit(rows)
                # placebo: probabilities permuted between matches of the same ISO week
                wk: dict[datetime, list[int]] = defaultdict(list)
                for i, r in enumerate(hist):
                    wk[lc.monday_of(r.kickoff_at)].append(i)
                perm = list(range(len(rows)))
                for ids in wk.values():
                    shuffled = list(rng.permutation(ids))
                    for a, b in zip(ids, shuffled, strict=True):
                        perm[a] = b
                mkp = market_fit([(rows[i][0], rows[i][1], rows[perm[i]][2], rows[i][3]) for i in range(len(rows))])
            for r in weeks[monday]:
                h, a, nt = int(r.home), int(r.away), bool(r.neutral)
                if not (main.knows(h) and main.knows(a)):
                    continue
                rec: dict[str, Any] = {"fixture_id": int(r.fixture_id), "comp": comp, "cs_id": int(r.cs_id), "season": int(r.season),
                                       "monday": monday, "kickoff_at": r.kickoff_at, "neutral": nt,
                                       "y": 0 if r.gh > r.ga else 1 if r.gh == r.ga else 2}
                try:
                    rec["B0"] = onex2(main.score_matrix(h, a, neutral=nt)[0])
                    b0_kind = "dixon_coles"
                except InvalidCorrectionError:
                    if second is None:
                        second = pois
                    if second is None or not (second.knows(h) and second.knows(a)):
                        continue
                    rec["B0"] = onex2(second.score_matrix(h, a, neutral=nt)[0])
                    b0_kind = "poisson"
                rec["b0_kind"] = b0_kind
                if not nt:
                    with contextlib.suppress(InvalidCorrectionError):  # C26 missing: the pair is left out of its comparison
                        rec["C26"] = onex2(c26_model.score_matrix(h, a, neutral=nt)[0])
                    rec["h26"], rec["h0"] = h26, float(main.home)
                if pois is not None and pois.knows(h) and pois.knows(a):
                    rec["C30a"] = onex2(pois.score_matrix(h, a, neutral=nt)[0])
                if ol is not None and ol.converged and not (nt and not ol.home_identified):
                    ph, pd, pa = ol.predict(frozen.get(h, 1500.0) - frozen.get(a, 1500.0), neutral=nt)
                    rec["C30b"] = np.array([ph, pd, pa])
                    rec["C30c"] = pool(rec["B0"], rec["C30b"])
                if mk is not None:
                    p = market_predict(mk, h, a)
                    if p is not None:
                        rec["C27"] = p
                if mkp is not None:
                    p = market_predict(mkp, h, a)
                    if p is not None:
                        rec["C27p"] = p
                if int(r.fixture_id) in market:
                    rec["MKT"] = market[int(r.fixture_id)]
                out.append(rec)
        log(f"comp {comp}: {sum(1 for x in out if x['comp'] == comp)} predictions")
    return out


# ── the lines ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _ll(recs: Sequence[Mapping[str, Any]], model: str) -> NDArray[np.float64]:
    return np.array([-math.log(max(float(r[model][r["y"]]), EPS)) for r in recs])


def _weeks(recs: Sequence[Mapping[str, Any]]) -> NDArray[np.int64]:
    return np.array([r["monday"].toordinal() for r in recs], dtype=np.int64)


def compare(recs: Sequence[Mapping[str, Any]], a: str, b: str, *, seed: int, level: float = 0.95) -> dict[str, Any]:
    sel = [r for r in recs if a in r and b in r]
    return paired(_ll(sel, a), _ll(sel, b), _weeks(sel), seed=seed, level=level)


def segments(recs: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    from scripts.lab_pm_common import PRIORITY

    seg: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in recs:
        seg["prioritarias" if r["comp"] in PRIORITY else "resto"].append(r)
        seg[f"temporada {r['season']}"].append(r)
    return seg


def line_op26(recs: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    glob = compare(recs, "C26", "B0", seed=seed)
    segs = {k: compare(v, "C26", "B0", seed=seed) for k, v in segments(recs).items()}
    segs = {k: v for k, v in segs.items() if v.get("n", 0) >= 1000}
    if glob.get("n", 0) < 5000:
        verdict = "INSUFICIENTE"
    else:
        verdict = "PASA" if glob["ci"][1] < 0 and all(v["ci"][0] <= 0 for v in segs.values()) else "NO PASA"
    ha = defaultdict(list)
    for r in recs:
        if "h26" in r:
            ha[(r["comp"], r["kickoff_at"].year)].append(r["h26"])
    market = compare([r for r in recs if "MKT" in r], "C26", "MKT", seed=seed)
    return {"verdict": verdict, "global": glob, "segments": segs, "vs_market": market,
            "home_term_by_comp_year": {f"{c}:{y}": float(np.mean(v)) for (c, y), v in sorted(ha.items())}}


def line_op27(recs: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    sel = [r for r in recs if "C27" in r and "C27p" in r and "B0" in r and MK_FROM <= r["monday"] < MK_TO]
    a = compare(sel, "C27", "B0", seed=seed)
    b = compare(sel, "C27", "C27p", seed=seed)
    c = compare(sel, "C27p", "B0", seed=seed)
    if a.get("n", 0) < 1500:
        verdict, why = "INSUFICIENTE", "menos de 1.500 partidos"
    elif c["ci"][1] < 0:
        verdict, why = "NO PASA", "circularidad o artefacto: el placebo mejora a B0"
    elif a["ci"][1] < 0 and b["ci"][1] < 0:
        verdict, why = "PASA", "mejora a B0 y al placebo"
    else:
        verdict, why = "NO PASA", "no mejora a B0 o al placebo con intervalo"
    mkt = compare([r for r in sel if "MKT" in r], "C27", "MKT", seed=seed)
    by_league = {str(k): compare([r for r in sel if r["comp"] == k], "C27", "B0", seed=seed) for k in sorted({r["comp"] for r in sel})}
    return {"verdict": verdict, "why": why, "C27_vs_B0": a, "C27_vs_placebo": b, "placebo_vs_B0": c, "C27_vs_market": mkt,
            "by_league": by_league}


def line_op29(recs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    from scripts.lab_pm_common import wilson

    recs = sorted(recs, key=lambda r: (r["monday"], r["kickoff_at"]))
    first = recs[0]["monday"] if recs else None
    scores = [(r["kickoff_at"], 1.0 - float(r["B0"][r["y"]])) for r in recs]
    tested: list[dict[str, Any]] = []
    for monday in sorted({r["monday"] for r in recs}):
        if first is None or monday < first + timedelta(weeks=CONF_WEEKS):
            continue
        cal = np.array([s for t, s in scores if monday - timedelta(weeks=CONF_WEEKS) <= t and t + timedelta(hours=3) < monday])
        q = conformal_q(cal)
        if q is None:
            continue
        for r in recs:
            if r["monday"] != monday:
                continue
            members = [k for k in range(3) if 1.0 - float(r["B0"][k]) <= q]
            tested.append({"comp": r["comp"], "season": r["season"], "y": r["y"], "size": len(members),
                           "covered": r["y"] in members})

    def summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        n = len(rows)
        if not n:
            return {"n": 0}
        cov = sum(1 for x in rows if x["covered"])
        sizes = np.array([x["size"] for x in rows])
        single = [x for x in rows if x["size"] == 1]
        return {"n": n, "coverage": cov / n, "wilson": list(wilson(cov, n)), "mean_size": float(sizes.mean()),
                "share_size": {str(k): float((sizes == k).mean()) for k in (0, 1, 2, 3)},
                "singleton_accuracy": (sum(1 for x in single if x["covered"]) / len(single)) if single else None}

    from scripts.lab_pm_common import PRIORITY

    glob = summary(tested)
    seg_rows: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for x in tested:
        seg_rows["prioritarias" if x["comp"] in PRIORITY else "resto"].append(x)
        seg_rows[f"temporada {x['season']}"].append(x)
    segs = {k: summary(v) for k, v in seg_rows.items()}
    by_outcome = {name: summary([x for x in tested if x["y"] == k]) for k, name in enumerate(("local", "empate", "visitante"))}
    if glob.get("n", 0) < 2000:
        verdict = "INSUFICIENTE"
    else:
        in_band = all(0.885 <= s["coverage"] <= 0.915 for s in [glob, *[v for v in segs.values() if v["n"] >= 500]])
        verdict = "PASA" if in_band and glob["mean_size"] <= 2.5 else "NO PASA"
    return {"verdict": verdict, "global": glob, "segments": segs, "by_outcome": by_outcome}


def line_op30(recs: Sequence[Mapping[str, Any]], seed: int) -> dict[str, Any]:
    level = 1 - 0.05 / 3
    sel = [r for r in recs if all(k in r for k in ("B0", "C30a", "C30b", "C30c"))]
    res = {k: compare(sel, k, "B0", seed=seed, level=level) for k in ("C30a", "C30b", "C30c")}
    if len(sel) < 5000:
        verdict, winners = "INSUFICIENTE", []
    else:
        winners = [k for k, v in res.items() if v["ci"][1] < 0]
        verdict = "PASA" if winners else "NO PASA"
    mkt_sel = [r for r in recs if "MKT" in r]
    external = {k: compare(mkt_sel, k, "MKT", seed=seed) for k in ("B0", "C30a", "C30b", "C30c")}
    segs = {s: {k: compare(v, k, "B0", seed=seed, level=level) for k in ("C30a", "C30b", "C30c")}
            for s, v in segments(sel).items() if len(v) >= 1000}
    return {"verdict": verdict, "winners": winners, "vs_B0": res, "vs_market": external,
            "market_ok": external["B0"].get("n", 0) >= 1500, "segments": segs, "excluded_missing": len(recs) - len(sel)}


def brier_table(recs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out = {}
    for k in ("B0", "C26", "C27", "C27p", "C30a", "C30b", "C30c", "MKT"):
        sel = [r for r in recs if k in r]
        if not sel:
            continue
        p = np.array([r[k] for r in sel])
        y = np.zeros_like(p)
        y[np.arange(len(sel)), [r["y"] for r in sel]] = 1
        out[k] = {"n": len(sel), "log_loss": float(_ll(sel, k).mean()), "brier": float(((p - y) ** 2).sum(axis=1).mean())}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    import json

    from fbi.research import protocol
    from scripts import lab_pm_common as lc

    for k in KEYS:
        protocol.require(k)
    seed = protocol.require(KEYS[0]).seed
    ap = argparse.ArgumentParser(prog="lab_portfolio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    con = lc.open_export(args.folder, need=("core.fixtures", "core.fixture_results", "market.historical_odds",
                                            "analytics.promoted_forecast_spec"))
    spec_row = lc.one(con, "SELECT spec FROM analytics_promoted_forecast_spec ORDER BY promoted_at DESC LIMIT 1")
    spec = json.loads(spec_row[0])
    hyper = spec["goal"]["dixon_coles"]
    recs = walk_forward(con, xi=float(hyper["xi"]), penalty=float(hyper["penalty"]), history_days=int(spec.get("history_days", 730)),
                        seed=seed)
    result = {
        "stamps": {k: lc.stamp(k, args.folder).as_json() for k in KEYS}, "spec": spec, "predictions": len(recs),
        "competitions": sorted({r["comp"] for r in recs}), "scores": brier_table(recs),
        "OP26": line_op26(recs, seed), "OP27": line_op27(recs, seed), "OP29": line_op29(recs), "OP30": line_op30(recs, seed),
        "OP28": "no se toca: E4 (INT-A09) y E6 (INT-A08) del Plan Intelligence",
    }
    lc.write_json(args.out, result)
    for k in ("OP26", "OP27", "OP29", "OP30"):
        print(k, result[k]["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
