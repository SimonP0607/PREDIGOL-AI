"""INT-A02 (LAB, IA-036): the coherent multiclass calibration against the rescaled cal-logit2-v1, walk-forward - the ONE evaluation of
protocol ``proto-int-a02-v1`` (``fbi.research.protocol.A02``). Reads two CSV files and no database; writes one JSON.

    python -m scripts.ia_lab_a02_coherente --units units.csv --picks picks.csv --out a02.json

THE INPUTS (``extract.sql`` of the plan writes them from production, read-only):

  units.csv  one row per (match, model, market, outcome) of 1X2, over/under 2.5 and both teams to score: the match (kick-off, status,
             regulation score, when its result was settled, competition), the model's LAST prediction stored 3 h or more before the
             kick-off (``q``, its moment ``t``) and the newest Shin consensus no older than 6 h at ``t`` (``m``, empty when none);
  picks.csv  the last pick before kick-off of each (match, market, selection, line, model) and its settled result: what cal-logit2-v1
             is fitted on in production (``fbi.intel.calibration.SETTLED_SQL``; OU with every line, as the calibrator pools them).

THE UNIT is a match, a model and a complete market. Excluded, and counted: a match not finished (FT, AET, PEN), without a settled
regulation score, before 1 Sep 2026 (Bogotá); a market with an outcome missing, a probability outside (0, 1) or no consensus of 6 h or
less at the prediction's moment.

THE WALK-FORWARD, per (market, model), over the Bogotá days of the units (the first ``WF_MIN_PRIOR_DAYS`` skipped): day D is scored by
fits on the matches that kicked off in the 28 days before D began and were settled before it began, with at least 500 of them
(``fbi.intel.calibration``'s rules). The two calibrators score the same days, each fitted on its own population:

  coherent   ``fbi.intel.calibration_coherent``: the pool of q and m with one intercept per outcome, fitted on the units;
  rescaled   cal-logit2-v1 as production fits it - ``calibration.train_set`` and ``fit_params("logit2")`` on the picks -,
             applied to each outcome of the unit with ``apply_params`` and the market then divided by its sum, as the common view
             does (``fbi.forecasting.market_view._calibrate``): the probability the Match Center shows today.

THE FIGURES, as the protocol fixed them before the data were read: per market (the models pooled) the paired difference of the
multiclass log loss, coherent minus rescaled, averaged per day and then over the days, with its 95 % interval by bootstrap of days
(seed of the protocol); the sum of every coherent market (|sum - 1| <= 1e-9); the ECE of each outcome over 10 groups of equal size;
the same against the raw model and the de-vigged market; the ECE of the selections the model flagged (a pick), coherent against
cal-logit2-v1 as decision-v1 uses it (not rescaled) and rescaled; the market's share c / (b + c) of the pool per (market, model) with
its interval; reliability tables; the same per model and for the priority competitions (``fbi.intel.day_priority`` groups 1-3)
against the rest. The verdict per market: PASA, RECHAZA or PENDIENTE POR MUESTRA (fewer than 1,500 units or 5 days).

It touches no model, calibrator in use, forecast, pick or decision: a measurement in the LAB.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from fbi.ai.calendar import day_start, local_day
from fbi.intel import calibration as cal
from fbi.intel import calibration_coherent as cc
from fbi.intel.day_priority import group_of
from fbi.picks.settlement import Status, market_outcome
from fbi.research import protocol

KEY = "INT-A02"
VERSION = "ia-lab-a02-v1"
SINCE = date(2026, 9, 1)
OUTCOMES: dict[str, tuple[str, ...]] = {"1X2": ("Home", "Draw", "Away"), "OU": ("Over", "Under"), "BTTS": ("Yes", "No")}
LINE: dict[str, Decimal] = {"1X2": Decimal("0"), "OU": Decimal("2.5"), "BTTS": Decimal("0")}
FINISHED = frozenset({"FT", "AET", "PEN"})
BEFORE_KICKOFF = timedelta(hours=3)
MARKET_AGE = timedelta(hours=6)
PRIORITY_GROUPS = frozenset({1, 2, 3})
ECE_SLACK = 0.005
MEAN_REPS = 10000
WEIGHT_REPS = 500
METHODS = ("coherent", "rescaled", "raw", "market")
COMPARED = (("coherent", "rescaled"), ("coherent", "raw"), ("coherent", "market"), ("rescaled", "market"))


def ts(text: str) -> datetime:
    """A timestamp as PostgreSQL's COPY writes it (``2026-09-01 18:00:00+00``), aware."""
    t = text.strip().replace(" ", "T", 1)
    if len(t) >= 3 and t[-3] in "+-" and t[-2:].isdigit():
        t += ":00"
    out = datetime.fromisoformat(t)
    if out.tzinfo is None:
        raise ValueError(f"timestamp without a time zone: {text!r}")
    return out


def num(text: str | None) -> float | None:
    return None if text is None or text == "" else float(text)


@dataclass(frozen=True, slots=True)
class Unit:
    fixture_id: int
    model: str
    market: str
    kickoff: datetime
    settled: datetime
    day: date
    q: tuple[float, ...]
    m: tuple[float, ...]
    y: int
    priority: bool


def outcome_index(market: str, home: int, away: int) -> int:
    won = [i for i, s in enumerate(OUTCOMES[market]) if market_outcome(market, s, LINE[market], home, away) == Status.WIN]
    if len(won) != 1:
        raise ValueError(f"{market} {home}-{away}: {len(won)} outcomes win")
    return won[0]


def load_units(path: Path) -> tuple[list[Unit], Counter[str], dict[str, int]]:
    """The units, the count of what was excluded and why, and the size of the raw file."""
    groups: dict[tuple[int, str, str], list[dict[str, str]]] = defaultdict(list)
    rows = 0
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rows += 1
            groups[(int(r["fixture_id"]), r["model"], r["market_key"])].append(r)
    units: list[Unit] = []
    excluded: Counter[str] = Counter()
    for (fixture_id, model, market), rs in sorted(groups.items()):
        first = rs[0]
        kickoff = ts(first["kickoff_at"])
        if local_day(kickoff) < SINCE:
            excluded["antes del 1-sep (Bogotá)"] += 1
            continue
        if first["status_short"] not in FINISHED:
            excluded[f"estado {first['status_short']}"] += 1
            continue
        if not first["settled_at"] or first["gh"] == "" or first["ga"] == "":
            excluded["sin resultado liquidado"] += 1
            continue
        by_sel = {r["selection"]: r for r in rs}
        if market not in OUTCOMES or sorted(by_sel) != sorted(OUTCOMES[market]) or len(rs) != len(OUTCOMES[market]):
            excluded["mercado incompleto"] += 1
            continue
        t = ts(first["t"])
        if t > kickoff - BEFORE_KICKOFF:
            excluded["predicción a menos de 3 h del saque"] += 1
            continue
        q = [num(by_sel[s]["q"]) for s in OUTCOMES[market]]
        m = [num(by_sel[s]["m"]) for s in OUTCOMES[market]]
        if any(x is None or not 0.0 < x < 1.0 for x in q):
            excluded["probabilidad del modelo fuera de (0, 1)"] += 1
            continue
        if any(x is None for x in m):
            excluded["sin consenso de 6 h o menos"] += 1
            continue
        if any(not 0.0 < float(x or 0.0) < 1.0 for x in m):
            excluded["probabilidad del mercado fuera de (0, 1)"] += 1
            continue
        ages = [t - ts(by_sel[s]["m_as_of"]) for s in OUTCOMES[market]]
        if any(a < timedelta(0) or a > MARKET_AGE for a in ages):
            excluded["consenso fuera de [t - 6 h, t]"] += 1
            continue
        league = num(first["provider_league_id"])
        units.append(Unit(fixture_id, model, market, kickoff, ts(first["settled_at"]), local_day(kickoff),
                          tuple(float(x or 0.0) for x in q), tuple(float(x or 0.0) for x in m),
                          outcome_index(market, int(first["gh"]), int(first["ga"])),
                          group_of(None if league is None else int(league)) in PRIORITY_GROUPS))
    return units, excluded, {"rows": rows, "groups": len(groups)}


FlagKey = tuple[int, str, str, str]
"""(match, market, selection, model) of a selection the model flagged (a pick before the kick-off)."""


def load_picks(path: Path) -> tuple[dict[tuple[str, str], list[cal.Obs]], set[FlagKey], Counter[str]]:
    """cal-logit2-v1's observations per (market, model) - ``SETTLED_SQL``'s last filter applied here -, the flagged selections of the
    units' markets, and the count of what was left out."""
    obs: dict[tuple[str, str], list[cal.Obs]] = defaultdict(list)
    flags: set[FlagKey] = set()
    left: Counter[str] = Counter()
    with path.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            kickoff = ts(r["kickoff_at"])
            if local_day(kickoff) < SINCE:
                left["antes del 1-sep (Bogotá)"] += 1
                continue
            market = r["market_key"]
            if market in LINE and Decimal(r["line"]) == LINE[market]:
                flags.add((int(r["fixture_id"]), market, r["selection"], r["model"]))
            p_model, p_market = num(r["p_model"]), num(r["p_market"])
            if r["result_status"] not in ("win", "loss"):
                left[f"resultado {r['result_status']}"] += 1
                continue
            if p_market is None or not 0.0 < p_market < 1.0 or p_model is None or not 0.0 < p_model < 1.0:
                left["probabilidad fuera de (0, 1) o sin mercado"] += 1
                continue
            obs[(market, r["model"])].append(cal.Obs(
                int(r["pick_id"]), int(r["fixture_id"]), kickoff, ts(r["settled_at"]), market, r["model"], p_model, p_market,
                float(r["odds"] or 0.0), 1.0 if r["result_status"] == "win" else 0.0, None))
    return obs, flags, left


@dataclass
class Scored:
    """The units of one (market, model) scored out of sample, with the fit of each day."""

    market: str
    model: str
    day: list[date]
    fixture: list[int]
    y: list[int]
    priority: list[bool]
    flagged: list[tuple[bool, ...]]
    p: dict[str, list[tuple[float, ...]]]
    """method -> probabilities per unit: the four of ``METHODS`` and ``selection`` (cal-logit2-v1 per outcome, not rescaled)."""
    q: list[tuple[float, ...]]
    m: list[tuple[float, ...]]
    """The inputs of each scored unit (the model's and the market's probabilities), for the pooled fit of the market's share."""
    fits: list[dict[str, Any]]
    skipped: list[dict[str, Any]]


def walk_forward(market: str, model: str, units: Sequence[Unit], obs: Sequence[cal.Obs], flags: set[FlagKey]) -> Scored:
    out = Scored(market, model, [], [], [], [], [], {k: [] for k in (*METHODS, "selection")}, [], [], [], [])
    if not units:
        return out
    kick = np.array([u.kickoff.timestamp() for u in units])
    settled = np.array([u.settled.timestamp() for u in units])
    q = np.array([u.q for u in units])
    m = np.array([u.m for u in units])
    y = np.array([u.y for u in units], dtype=np.int64)
    by_day: dict[date, list[int]] = defaultdict(list)
    for i, u in enumerate(units):
        by_day[u.day].append(i)
    days = sorted(by_day)
    sels = OUTCOMES[market]
    for i, d in enumerate(days):
        if i < cal.WF_MIN_PRIOR_DAYS:
            out.skipped.append({"day": d.isoformat(), "why": "primeros días (3 previos)"})
            continue
        cut = day_start(d)
        mask = cc.train_mask(kick, settled, cutoff=cut.timestamp(), window=cal.WINDOW.total_seconds())
        ref_train = cal.train_set(list(obs), cutoff=cut)
        n_coh, n_ref = int(mask.sum()), len(ref_train)
        if n_coh < cal.MIN_TRAIN or n_ref < cal.MIN_TRAIN:
            out.skipped.append({"day": d.isoformat(), "why": "menos de 500 para ajustar", "n_coherent": n_coh, "n_reference": n_ref})
            continue
        fit = cc.fit(q[mask], m[mask], y[mask])
        params = cal.fit_params("logit2", ref_train)
        idx = by_day[d]
        p_coh = fit.predict(q[idx], m[idx])
        p_sel = np.array([[cal.apply_params("logit2", params, float(q[j, k]), float(m[j, k])) for k in range(len(sels))] for j in idx],
                         dtype=np.float64)
        p_res = cc.rescale(p_sel)
        out.fits.append({"day": d.isoformat(), "n_coherent": n_coh, "n_reference": n_ref, "scored": len(idx), "coherent": fit.as_json(),
                         "reference": params})
        for row, j in enumerate(idx):
            u = units[j]
            out.day.append(d)
            out.fixture.append(u.fixture_id)
            out.y.append(u.y)
            out.priority.append(u.priority)
            out.flagged.append(tuple((u.fixture_id, market, s, model) in flags for s in sels))
            out.q.append(u.q)
            out.m.append(u.m)
            out.p["coherent"].append(tuple(float(x) for x in p_coh[row]))
            out.p["selection"].append(tuple(float(x) for x in p_sel[row]))
            out.p["rescaled"].append(tuple(float(x) for x in p_res[row]))
            out.p["raw"].append(tuple(float(x) / sum(u.q) for x in u.q))
            out.p["market"].append(tuple(float(x) / sum(u.m) for x in u.m))
    return out


# -- the figures ------------------------------------------------------------------------------------------------------------------------

@dataclass
class Pop:
    """A population of scored units (one market): arrays ready for the figures."""

    market: str
    day: np.ndarray
    y: np.ndarray
    flagged: np.ndarray
    p: dict[str, np.ndarray]

    @property
    def n(self) -> int:
        return int(self.y.size)


def population(market: str, parts: Iterable[Scored], keep: Sequence[bool] | None = None) -> Pop:
    scored = list(parts)
    day = np.array([d.toordinal() for s in scored for d in s.day], dtype=np.int64)
    y = np.array([v for s in scored for v in s.y], dtype=np.int64)
    flagged = np.array([f for s in scored for f in s.flagged], dtype=bool).reshape(-1, len(OUTCOMES[market]))
    p = {k: np.array([x for s in scored for x in s.p[k]], dtype=np.float64).reshape(-1, len(OUTCOMES[market]))
         for k in (*METHODS, "selection")}
    if keep is not None:
        mask = np.asarray(keep, dtype=bool)
        day, y, flagged, p = day[mask], y[mask], flagged[mask], {k: v[mask] for k, v in p.items()}
    return Pop(market, day, y, flagged, p)


def r6(x: float | None) -> float | None:
    return cc.finite(x)


def paired(pop: Pop, a: str, b: str, seed: int) -> dict[str, Any]:
    """The paired difference of the multiclass log loss, ``a`` minus ``b``: per day its mean, then the mean over days with its interval by
    bootstrap of days (the protocol's primary figure); the spread of the daily values and the smallest difference they can see; and, as a
    check, the mean over units with the days resampled whole."""
    diff = cc.log_loss(pop.p[a], pop.y) - cc.log_loss(pop.p[b], pop.y)
    days = np.unique(pop.day)
    sums = np.array([diff[pop.day == d].sum() for d in days])
    counts = np.array([float((pop.day == d).sum()) for d in days])
    daily = sums / counts
    mean, lo, hi = cc.day_bootstrap(daily, reps=MEAN_REPS, seed=seed)
    wmean, wlo, whi = cc.cluster_bootstrap(sums, counts, reps=MEAN_REPS, seed=seed)
    s = cc.sd(daily)
    mde = protocol.mde_for_mean(s, int(days.size)) if days.size > 1 and math.isfinite(s) and s > 0 else None
    out: dict[str, Any] = {"a": a, "b": b, "n": pop.n, "days": int(days.size), "mean_of_days": r6(mean), "ci95": [r6(lo), r6(hi)],
                           "sd_daily": r6(s), "mde": r6(mde), "mean_of_units": r6(wmean), "ci95_units": [r6(wlo), r6(whi)],
                           "days_a_better": int((daily < 0).sum())}
    if (a, b) == COMPARED[0]:
        out["daily"] = [{"day": date.fromordinal(int(d)).isoformat(), "n": int(c), "diff": r6(float(v))}
                        for d, c, v in zip(days, counts, daily, strict=True)]
    return out


def eces(pop: Pop) -> dict[str, dict[str, float | None]]:
    sels = OUTCOMES[pop.market]
    return {meth: {s: r6(cc.ece_equal_mass((pop.y == k).astype(float), pop.p[meth][:, k])) for k, s in enumerate(sels)} for meth in METHODS}


def flagged_eces(pop: Pop) -> dict[str, Any]:
    """The selections the model flagged (a pick), as decision-v1 judges them: one binary forecast per flagged outcome."""
    rows, cols = np.nonzero(pop.flagged)
    y01 = (pop.y[rows] == cols).astype(float)
    out: dict[str, Any] = {"n": int(rows.size), "hit_rate": r6(float(y01.mean())) if rows.size else None}
    for meth in ("coherent", "selection", "rescaled", "market"):
        p = pop.p[meth][rows, cols]
        out[meth] = {"ece": r6(cc.ece_equal_mass(y01, p)), "mean_p": r6(float(p.mean())) if rows.size else None}
    return out


def sums(pop: Pop) -> dict[str, Any]:
    coh = cc.sum_gap(pop.p["coherent"])
    res = cc.sum_gap(pop.p["rescaled"])
    raw = pop.p["selection"].sum(axis=1) - 1.0
    return {"coherent_max_gap": float(coh.max()) if coh.size else None,
            "coherent_within": int((coh <= cc.SUM_TOLERANCE).sum()), "n": pop.n,
            "rescaled_max_gap": float(res.max()) if res.size else None,
            "selection_sum_minus_one_pp": {"median": r6(float(np.median(raw)) * 100) if raw.size else None,
                                           "p10": r6(float(np.percentile(raw, 10)) * 100) if raw.size else None,
                                           "p90": r6(float(np.percentile(raw, 90)) * 100) if raw.size else None,
                                           "max_abs": r6(float(np.abs(raw).max()) * 100) if raw.size else None}}


def summary(pop: Pop, seed: int, *, with_ece: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {"n": pop.n, "days": int(np.unique(pop.day).size),
                           "logloss": {meth: r6(float(cc.log_loss(pop.p[meth], pop.y).mean())) if pop.n else None for meth in METHODS},
                           "paired": {f"{a}-{b}": paired(pop, a, b, seed) for a, b in COMPARED} if pop.n else {}}
    if with_ece and pop.n:
        out["ece"] = eces(pop)
        out["flagged"] = flagged_eces(pop)
        out["sums"] = sums(pop)
    return out


def verdict(s: Mapping[str, Any]) -> dict[str, Any]:
    """The protocol's rule on one market."""
    if s["n"] < cal.MIN_OOS_N or s["days"] < cal.MIN_OOS_DAYS:
        return {"verdict": "PENDIENTE POR MUESTRA", "why": [f"{s['n']} partidos-mercado en {s['days']} días (mínimo 1.500 en 5)"]}
    why: list[str] = []
    sm = s["sums"]
    if sm["coherent_within"] != sm["n"]:
        why.append(f"{sm['n'] - sm['coherent_within']} mercados no suman 1")
    hi = s["paired"]["coherent-rescaled"]["ci95"][1]
    if hi is None or hi > 0:
        why.append(f"límite superior del IC95 de la diferencia = {hi} > 0")
    for sel, coh in s["ece"]["coherent"].items():
        ref = s["ece"]["rescaled"][sel]
        if coh is None or ref is None or coh - ref > ECE_SLACK:
            why.append(f"ECE de {sel} empeora {None if coh is None or ref is None else round(coh - ref, 4)} > 0,005")
    return {"verdict": "RECHAZA" if why else "PASA", "why": why}


def market_share(sc: Scored, seed: int) -> dict[str, Any]:
    """c / (b + c): of the daily walk-forward fits, and of one fit over the scored units with its interval (the days resampled whole and
    the pool refitted, as ``fbi.research.blend.weight_interval``)."""
    daily = [f["coherent"]["market_share"] for f in sc.fits if f["coherent"]["market_share"] is not None]
    out: dict[str, Any] = {"daily_fits": len(sc.fits), "daily_median": r6(float(np.median(daily))) if daily else None,
                           "daily_p25": r6(float(np.percentile(daily, 25))) if daily else None,
                           "daily_p75": r6(float(np.percentile(daily, 75))) if daily else None,
                           "daily_not_converged": sum(1 for f in sc.fits if not f["coherent"]["converged"])}
    if len(sc.y) < cal.MIN_TRAIN:
        return out
    q = np.array(sc.q, dtype=np.float64)
    m = np.array(sc.m, dtype=np.float64)
    y = np.array(sc.y, dtype=np.int64)
    day = np.array([d.toordinal() for d in sc.day])
    whole = cc.fit(q, m, y)
    groups = [np.nonzero(day == d)[0] for d in np.unique(day)]
    rng = np.random.default_rng(seed)
    shares: list[float] = []
    for _ in range(WEIGHT_REPS):
        idx = np.concatenate([groups[g] for g in rng.integers(0, len(groups), len(groups))])
        s = cc.fit(q[idx], m[idx], y[idx]).market_share
        if s is not None:
            shares.append(s)
    out.update({"pooled": whole.as_json(), "pooled_share": r6(whole.market_share),
                "pooled_share_ci95": [r6(float(np.percentile(shares, 2.5))), r6(float(np.percentile(shares, 97.5)))] if shares else None,
                "reps": len(shares)})
    return out


def reliability(pop: Pop) -> dict[str, dict[str, list[dict[str, Any]]]]:
    return {meth: {s: cc.reliability_equal_mass((pop.y == k).astype(float), pop.p[meth][:, k]) for k, s in enumerate(OUTCOMES[pop.market])}
            for meth in ("coherent", "rescaled")}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(units_path: Path, picks_path: Path) -> dict[str, Any]:
    proto = protocol.require(KEY)
    stamp = protocol.stamp(KEY)
    seed = proto.seed
    units, excluded, raw = load_units(units_path)
    obs, flags, left = load_picks(picks_path)
    by_mm: dict[tuple[str, str], list[Unit]] = defaultdict(list)
    for u in units:
        by_mm[(u.market, u.model)].append(u)
    scored: dict[tuple[str, str], Scored] = {}
    for (market, model), us in sorted(by_mm.items()):
        scored[(market, model)] = walk_forward(market, model, sorted(us, key=lambda u: (u.kickoff, u.fixture_id)), obs.get((market, model), []), flags)
    results: dict[str, Any] = {}
    for market in OUTCOMES:
        parts = [s for (mk, _), s in sorted(scored.items()) if mk == market and s.y]
        if not parts:
            results[market] = {"n": 0, "days": 0, "verdict": {"verdict": "PENDIENTE POR MUESTRA", "why": ["sin unidades evaluadas"]}}
            continue
        pop = population(market, parts)
        s = summary(pop, seed)
        s["verdict"] = verdict(s)
        s["reliability"] = reliability(pop)
        s["models"] = {}
        for part in parts:
            ms = summary(population(market, [part]), seed)
            ms["market_share"] = market_share(part, seed)
            ms["skipped_days"] = Counter(str(x["why"]) for x in part.skipped)
            ms["first_day"] = part.day[0].isoformat()
            ms["last_day"] = part.day[-1].isoformat()
            s["models"][part.model] = ms
        prio = [p for part in parts for p in part.priority]
        s["segments"] = {"prioritarias": summary(population(market, parts, prio), seed),
                         "resto": summary(population(market, parts, [not p for p in prio]), seed)}
        results[market] = s
    return {
        "version": VERSION, "stamp": stamp,
        "protocol": {"title": proto.title, "registered_on": proto.registered_on, "seed": seed, "pass_rule": proto.pass_rule,
                     "reject_rule": proto.reject_rule, "min_sample": proto.min_sample},
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "inputs": {"units": {"path": str(units_path), "sha256": sha256(units_path), **raw},
                   "picks": {"path": str(picks_path), "sha256": sha256(picks_path)}},
        "rules": {"since": SINCE.isoformat(), "window_days": cal.WINDOW.days, "min_train": cal.MIN_TRAIN, "prior_days": cal.WF_MIN_PRIOR_DAYS,
                  "l2": cc.L2, "reference": f"{cal.VERSION} (logit2) on its picks, rescaled", "coherent": cc.VERSION, "bins": cc.BINS,
                  "mean_reps": MEAN_REPS, "weight_reps": WEIGHT_REPS, "ece_slack": ECE_SLACK},
        "data": {"units": len(units), "units_by_market_model": {f"{k[0]}/{k[1]}": len(v) for k, v in sorted(by_mm.items())},
                 "excluded": dict(excluded.most_common()), "picks_obs": {f"{k[0]}/{k[1]}": len(v) for k, v in sorted(obs.items())},
                 "picks_left_out": dict(left.most_common()), "flagged_selections": len(flags),
                 "scored": {f"{k[0]}/{k[1]}": len(v.y) for k, v in sorted(scored.items())}},
        "results": results,
        "verdict": {m: results[m]["verdict"] for m in OUTCOMES},
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_lab_a02_coherente", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--units", required=True, type=Path)
    ap.add_argument("--picks", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    doc = run(args.units, args.picks)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str, sort_keys=False) + "\n", encoding="utf-8")
    for market, v in doc["verdict"].items():
        r = doc["results"][market]
        pr = (r.get("paired") or {}).get("coherent-rescaled") or {}
        sys.stdout.write(f"{market}: {v['verdict']} n={r['n']} days={r['days']} diff={pr.get('mean_of_days')} ci={pr.get('ci95')} "
                         f"{'; '.join(v['why'])}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
