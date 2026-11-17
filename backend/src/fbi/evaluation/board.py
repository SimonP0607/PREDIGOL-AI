"""The validation board by layer, family and market (IA-113, AD-K02): ``board-v1`` under the preregistered protocol ``AD-K02``.

For each cell - a layer of decisions in the shadow, a family (``fbi.lifecycle.reader.family_of``) and a market - and for each family as a
whole, over the evaluations after the match (AD-K01, ``eval-sel-v1``) of a period:

    calibration     ECE over ten equal-width bins of the probability judged, and the bins themselves (mean predicted, observed, n)
    vs the market   the paired difference of the mean log loss (primary) and of the Brier score (= the RPS of a binary selection),
                    probability judged minus the market's de-vigged probability of the same moment
    vs the yardstick  the mean CLV (``clv-v1``) against the price rule's (INT-A10, IA-054): +5,77 % [5,28; 6,24] in 2.705 selections
    the sample      the selections that carry all three (a full result, the market's probability and a close) against the NEEDED 300

THE POPULATION is the selections the layer would take: its standing decision CONFIRMED them in the shadow (``taken``: approved, or
parked only by the validation of their market - ``lifecycle-map-v1``). A market is validated by the edge of what it would publish, not
by every candidate it looked at; each cell also says how many candidates it had (``candidates``).

Every interval resamples whole Bogotá days (2.000 replicates, the protocol's seed) at the level Bonferroni corrects to: ``1 - 0,05/m``, with
``m`` the cells and families of this run that reach the needed sample. THE VERDICT (``verdict``) is the protocol's and nothing else:
INSUFICIENTE below the sample; VALIDADO only when the three rules hold; NO_VALIDADO otherwise, saying which rule failed.

A verdict activates nothing: no switch, threshold, model, pick or reader reads the board. It is computed on demand and keeps nothing; its
only readers are the owner's views (C-03) and command. Pure: no database, no clock.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

import numpy as np

from fbi.core.calendar import local_day
from fbi.research import protocol

VERSION: Final = "board-v1"
PROTOCOL: Final = "AD-K02"
NEEDED: Final = 300
ECE_MAX: Final = 0.03
BINS: Final = 10
ALPHA: Final = 0.05
REPLICATES: Final = 2000
VARA_MEAN: Final = 0.0577
VARA_LOW: Final = 0.0528
VARA_HIGH: Final = 0.0624
"""The price rule's CLV (INT-A10, IA-054; consensus snapshots 12-oct to 10-nov-2026, n = 2.705), frozen in the protocol."""
ALL_MARKETS: Final = "*"
VERDICTS: Final[tuple[str, ...]] = ("VALIDADO", "NO_VALIDADO", "INSUFICIENTE")
CHECKS: Final[tuple[str, ...]] = ("supera_al_mercado", "calibrada", "supera_la_vara")


@dataclass(frozen=True, slots=True)
class Scored:
    """What the board reads of one evaluation."""

    layer: str
    family: str
    market_key: str
    day: date
    p: float
    seal: str
    hit: int | None
    p_market: float | None
    clv: float | None
    taken: bool = True

    @property
    def complete(self) -> bool:
        """Carries the three measures on the same selection (what the sample counts)."""
        return self.hit is not None and self.p_market is not None and self.clv is not None


def scored_of(row: Mapping[str, Any]) -> Scored:
    """A ``Scored`` from a row of ``intel.selection_evaluations`` (or an evaluation's ``row``)."""
    def f(v: Any) -> float | None:
        return None if v is None else float(v)

    p = f(row["p_judged"])
    assert p is not None
    return Scored(layer=str(row["layer"]), family=str(row["family"]), market_key=str(row["market_key"]), day=local_day(row["kickoff_at"]),
                  p=p, seal=str(row["seal"]), hit=None if row["hit"] is None else int(row["hit"]), p_market=f(row["p_market"]),
                  clv=f(row["clv"]), taken=bool(row["taken"]))


# ── the measures ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _log_loss(p: float, hit: int) -> float:
    q = min(max(p, 1e-6), 1 - 1e-6)
    return -math.log(q if hit else 1 - q)


def ece(pairs: Sequence[tuple[float, int]], bins: int = BINS) -> tuple[float | None, list[dict[str, Any]]]:
    """The expected calibration error over equal-width bins (weighted by the bins' counts) and the bins with something in them."""
    if not pairs:
        return None, []
    acc: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for p, h in pairs:
        acc[min(int(p * bins), bins - 1)].append((p, h))
    out, total = [], 0.0
    for b in sorted(acc):
        xs = acc[b]
        pred = sum(p for p, _ in xs) / len(xs)
        obs = sum(h for _, h in xs) / len(xs)
        total += len(xs) * abs(pred - obs)
        out.append({"bin": b, "pred_pct": round(100 * pred, 1), "observed_pct": round(100 * obs, 1), "n": len(xs)})
    return total / len(pairs), out


def by_day_mean_ci(values: Sequence[tuple[date, float]], *, level: float, seed: int, replicates: int = REPLICATES
                   ) -> tuple[float | None, float | None, float | None]:
    """The mean of the values and its interval at ``level`` resampling whole days (percentile bootstrap, ``replicates`` draws of as many
    days as there are). Deterministic for a seed (``numpy.random.default_rng``)."""
    if not values:
        return None, None, None
    sums: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for d, v in values:
        sums[d][0] += v
        sums[d][1] += 1
    days = sorted(sums)
    s = np.array([sums[d][0] for d in days])
    n = np.array([sums[d][1] for d in days])
    mean = float(s.sum() / n.sum())
    if len(days) < 2:
        return mean, None, None
    idx = np.random.default_rng(seed).integers(0, len(days), size=(replicates, len(days)))
    stats = np.sort(s[idx].sum(axis=1) / n[idx].sum(axis=1))
    tail = (1 - level) / 2
    lo = stats[max(0, min(replicates - 1, math.floor(tail * replicates)))]
    hi = stats[max(0, min(replicates - 1, math.ceil((1 - tail) * replicates) - 1))]
    return mean, float(lo), float(hi)


def sd(xs: Sequence[float]) -> float | None:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


# ── the verdict ──────────────────────────────────────────────────────────────────────────────────────────────────────

def verdict(sample: int, checks: Mapping[str, bool | None], needed: int = NEEDED) -> tuple[str, list[str]]:
    """The protocol's verdict and the rules that failed. Below the sample: INSUFICIENTE, whatever the checks say. With it: VALIDADO only
    when every one of the three rules is True (a rule that could not be measured is a failure, never a pass)."""
    if sample < needed:
        return "INSUFICIENTE", []
    failed = [c for c in CHECKS if checks.get(c) is not True]
    return ("NO_VALIDADO", failed) if failed else ("VALIDADO", [])


def _r(x: float | None, nd: int = 6) -> float | None:
    return None if x is None else round(x, nd)


def group(items: Sequence[Scored], *, level: float, seed: int, needed: int = NEEDED) -> dict[str, Any]:
    """Every measure of one cell (or family) and its verdict."""
    full = [s for s in items if s.complete]
    pairs = [(s.p, int(s.hit)) for s in full if s.hit is not None]
    e, bins = ece(pairs)
    ll = [(s.day, _log_loss(s.p, int(s.hit)) - _log_loss(float(s.p_market), int(s.hit))) for s in full
          if s.hit is not None and s.p_market is not None]
    br = [(s.day, (s.p - int(s.hit)) ** 2 - (float(s.p_market) - int(s.hit)) ** 2) for s in full
          if s.hit is not None and s.p_market is not None]
    cl = [(s.day, float(s.clv)) for s in full if s.clv is not None]
    ll_m, ll_lo, ll_hi = by_day_mean_ci(ll, level=level, seed=seed)
    br_m, br_lo, br_hi = by_day_mean_ci(br, level=level, seed=seed + 1)
    cl_m, cl_lo, cl_hi = by_day_mean_ci(cl, level=level, seed=seed + 2)
    model_ll = sum(_log_loss(s.p, int(s.hit)) for s in full if s.hit is not None) / len(full) if full else None
    checks: dict[str, bool | None] = {
        "supera_al_mercado": None if ll_hi is None else ll_hi < 0,
        "calibrada": None if e is None else e <= ECE_MAX,
        "supera_la_vara": None if cl_lo is None else cl_lo > VARA_HIGH,
    }
    word, failed = verdict(len(full), checks, needed)
    s_clv = sd([v for _, v in cl])
    return {
        "sample": len(full), "needed": needed, "selections": len(items), "days": len({s.day for s in full}),
        "not_scored": sum(1 for s in items if s.hit is None), "without_market": sum(1 for s in items if s.p_market is None),
        "without_close": sum(1 for s in items if s.clv is None),
        "calibrated_share": _r(sum(1 for s in full if s.seal == "calibrada") / len(full), 4) if full else None,
        "calibration": {"ece": _r(e), "bins": bins, "max": ECE_MAX},
        "log_loss": {"model": _r(model_ll), "diff_vs_market": _r(ll_m), "low": _r(ll_lo), "high": _r(ll_hi)},
        "brier": {"diff_vs_market": _r(br_m), "low": _r(br_lo), "high": _r(br_hi)},
        "clv": {"mean": _r(cl_m), "low": _r(cl_lo), "high": _r(cl_hi), "vara": VARA_MEAN, "vara_high": VARA_HIGH,
                "minus_vara": None if cl_m is None else _r(cl_m - VARA_MEAN),
                "mde": None if s_clv is None or not full else _r(2.80 * s_clv / math.sqrt(len(full)))},
        "checks": checks, "verdict": word, "failed": failed,
    }


def build(items: Iterable[Scored], *, needed: int = NEEDED, seed: int | None = None) -> dict[str, Any]:
    """The board: one entry per (layer, family, market) and per (layer, family, ``*``), each with its verdict. ``m`` (Bonferroni) is
    counted before any interval is computed: the groups that reach the needed sample."""
    p = protocol.require(PROTOCOL)
    s = p.seed if seed is None else seed
    cells: dict[tuple[str, str, str], list[Scored]] = defaultdict(list)
    candidates: dict[tuple[str, str, str], int] = defaultdict(int)
    for it in items:
        for key in ((it.layer, it.family, it.market_key), (it.layer, it.family, ALL_MARKETS)):
            candidates[key] += 1
            if it.taken:
                cells[key].append(it)
            else:
                cells.setdefault(key, [])
    m = sum(1 for xs in cells.values() if sum(1 for x in xs if x.complete) >= needed)
    level = 1 - ALPHA / max(m, 1)
    out = []
    for (layer, family, market), xs in sorted(cells.items()):
        g = group(xs, level=level, seed=s, needed=needed)
        out.append({"layer": layer, "family": family, "market": market, "candidates": candidates[(layer, family, market)], **g})
    counts = {v: sum(1 for c in out if c["verdict"] == v) for v in VERDICTS}
    return {"version": VERSION, "protocol": protocol.stamp(PROTOCOL), "signed_by_owner": False,
            "bonferroni": {"m": m, "alpha": ALPHA, "level": round(level, 6)}, "needed": needed, "cells": out, "counts": counts,
            "notice_es": "Un veredicto no activa nada; un acierto no valida el mercado."}


def from_rows(rows: Iterable[Mapping[str, Any]]) -> list[Scored]:
    return [scored_of(r) for r in rows]
