"""The performance of the readers and of the sources (IA-135, AD-K03): ``perf-v1`` under the preregistered protocol ``AD-K03``. Pure: no
database, no clock, no model.

READERS AGAINST THE RULES, ON THE SAME SELECTIONS. For each reader of the shadow (the Match and the Statistics agents by version; each
arm of the Council) and each settled selection that the rules (``rules-review-v1``) also judged before kick-off:

    kept by the rules     the rules' word is not DOWNGRADE or REJECT (what decision-v1's filter 6 lets through)
    vetoed by the reader  its stance is against (CONCERN, REJECT_SIGNAL, DOWNGRADE, REJECT)
    difference            clv x (kept by the rules and not vetoed - kept by the rules): what adding the reader's veto to the rules
                          changes in the value against the close of what passes, per selection examined (the metric of
                          ``review-retire-v1``, so that AD-D11 reads the same number)

The mean difference has its interval by a bootstrap of whole Bogotá days, at the Bonferroni level ``1 - 0,05/m`` (``m`` the readers that
reach the sample). APORTA when the interval is above 0, RESTA when below, SIN_DIFERENCIA when it covers 0, INSUFICIENTE below the sample
the power calculation of the protocol fixed (``NEEDED`` selections examined, ``MIN_DAYS`` days, ``MIN_DISCORDANT`` selections where the
veto changes something). Beside it, the attribution of ``attr-v1`` with Wilson intervals: the share of hits among the stances that took
a side, the share of stances toward the close, the share without a side.

SOURCES BY TYPE OF FACT. Each fact a decision cited and ``eval-sel-v1`` judged after the match (``sostenido``, ``contradicho``,
``no_evaluable``), counted ONCE per fact, by its source and its type (``out``, ``starts``, ``available``): the share held among the
resolved with its Wilson interval, measured from ``MIN_FACTS`` resolved facts (the minimum of AD-C08). The mean CLV of the selections that
cite the source is reported as a description, never as an effect.

A verdict activates nothing: no weight, threshold, version or reader reads it (AD-K07 is the only road, with the owner's signature).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import NormalDist
from typing import Any, Final

import numpy as np

from fbi.research import protocol

VERSION: Final = "perf-v1"
PROTOCOL: Final = "AD-K03"
AGAINST: Final = frozenset({"CONCERN", "REJECT_SIGNAL", "DOWNGRADE", "REJECT"})
NO_SIDE: Final = frozenset({"ABSTAIN", "NEUTRAL"})
RULES_STOP: Final = frozenset({"DOWNGRADE", "REJECT"})
"""The rules' words that stop a selection in decision-v1's filter 6 (CAUTELA)."""
DELTA: Final = 0.01
"""The difference the sample must see: one point of CLV per selection examined."""
SIGMA_PLAN: Final = 0.13
"""The planning spread of the CLV (IA-054: +5,77 % [5,28; 6,24] in 2.705 selections, sigma ~ 0,127 rounded up)."""
NEEDED: Final = protocol.n_for_mean(SIGMA_PLAN, DELTA)
"""1.327 selections examined per reader: the power calculation of the protocol (alpha 0,05 two-sided, power 0,80)."""
MIN_DAYS: Final = 14
MIN_DISCORDANT: Final = 30
MIN_FACTS: Final = 30
ALPHA: Final = 0.05
REPLICATES: Final = 2000
SEED: Final = 20261117
FACT_TYPES: Final[tuple[str, ...]] = ("out", "starts", "available")
UNATTRIBUTED: Final[Mapping[str, str]] = {"player": "attr-v1 no lee la postura del lector Jugador: sin atribución no hay medida"}
VERDICTS: Final[tuple[str, ...]] = ("APORTA", "RESTA", "SIN_DIFERENCIA", "INSUFICIENTE")
Z95: Final = NormalDist().inv_cdf(0.975)


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """The Wilson score interval of ``k`` in ``n`` (``fbi.ai.intervals.wilson``, held equal by a test), None without cases."""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def by_day(values: Sequence[tuple[date, float]], *, level: float = 0.95, seed: int = SEED,
           replicates: int = REPLICATES) -> tuple[float | None, float | None, float | None]:
    """(mean, low, high): the mean of the values and its two-sided interval at ``level`` by resampling whole days with replacement."""
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


def _r(x: float | None, nd: int = 6) -> float | None:
    return None if x is None else round(x, nd)


def _share(k: int, n: int) -> dict[str, Any]:
    ci = wilson(k, n)
    return {"k": k, "n": n, "share": _r(k / n, 4) if n else None, "ci95": None if ci is None else [_r(ci[0], 4), _r(ci[1], 4)]}


# ── readers ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Judged:
    """One settled selection and one reader: the reader's stance (attr-v1, before kick-off), the rules' word and the value against the
    close of the post-mortem the attribution kept."""

    reader: str
    """``<agent>/<version>`` (``council/<version>@<arm>`` for an arm of the Council)."""
    fixture_id: int
    selection: str
    """``<market>:<selection>:<line>``."""
    day: date
    stance: str
    rules_word: str | None
    clv: float | None
    outcome: str
    toward_close: bool | None

    @property
    def examined(self) -> bool:
        return self.rules_word is not None and self.clv is not None and math.isfinite(self.clv)

    @property
    def kept_by_rules(self) -> bool:
        return self.rules_word not in RULES_STOP

    @property
    def vetoed(self) -> bool:
        return self.stance in AGAINST

    @property
    def discordant(self) -> bool:
        return self.kept_by_rules and self.vetoed

    @property
    def difference(self) -> float:
        return -(self.clv or 0.0) if self.discordant else 0.0


def reader_key(agent: str, version: str, arm: str | None = None) -> str:
    return f"{agent}/{version}" + (f"@{arm}" if agent == "council" and arm and arm != "*" else "")


def _sized(items: Sequence[Judged]) -> tuple[bool, list[str]]:
    ex = [j for j in items if j.examined]
    days = {j.day for j in ex}
    disc = sum(1 for j in ex if j.discordant)
    why: list[str] = []
    if len(ex) < NEEDED:
        why.append(f"examinadas {len(ex)} de {NEEDED}")
    if len(days) < MIN_DAYS:
        why.append(f"días {len(days)} de {MIN_DAYS}")
    if disc < MIN_DISCORDANT:
        why.append(f"vetos que cambian algo {disc} de {MIN_DISCORDANT}")
    return not why, why


def reader_entry(items: Sequence[Judged], *, m: int) -> dict[str, Any]:
    """The protocol over one reader's selections, its interval at the level corrected for ``m`` readers."""
    ex = [j for j in items if j.examined]
    sized, missing = _sized(items)
    level = 1 - ALPHA / max(1, m)
    mean, lo, hi = by_day([(j.day, j.difference) for j in ex], level=level)
    if not sized or lo is None or hi is None:
        verdict = "INSUFICIENTE"
    elif lo > 0:
        verdict = "APORTA"
    elif hi < 0:
        verdict = "RESTA"
    else:
        verdict = "SIN_DIFERENCIA"
    diffs = [j.difference for j in ex]
    sd = float(np.std(diffs, ddof=1)) if len(diffs) > 1 else None
    mde = protocol.mde_for_mean(sd, len(diffs), alpha=ALPHA / max(1, m)) if sd and len(diffs) > 0 else None
    sided = [j for j in items if j.outcome in ("HIT", "MISS")]
    toward = [j for j in items if j.toward_close is not None]
    vetoed = [(j.day, j.clv or 0.0) for j in ex if j.vetoed]
    passed = [(j.day, j.clv or 0.0) for j in ex if not j.vetoed]
    v_mean, v_lo, v_hi = by_day(vetoed)
    p_mean, p_lo, p_hi = by_day(passed)
    return {
        "verdict": verdict, "missing": missing, "selections": len(items), "examined": len(ex), "days": len({j.day for j in ex}),
        "matches": len({j.fixture_id for j in ex}), "kept_by_rules": sum(1 for j in ex if j.kept_by_rules),
        "vetoed": sum(1 for j in ex if j.vetoed), "discordant": sum(1 for j in ex if j.discordant),
        "difference": {"mean": _r(mean), "low": _r(lo), "high": _r(hi), "level": round(level, 6), "sd": _r(sd), "mde": _r(mde)},
        "attribution": {"hits": _share(sum(1 for j in sided if j.outcome == "HIT"), len(sided)),
                        "toward_close": _share(sum(1 for j in toward if j.toward_close), len(toward)),
                        "no_side": _share(sum(1 for j in items if j.stance in NO_SIDE), len(items))},
        "clv": {"vetoed": {"n": len(vetoed), "mean": _r(v_mean), "ci95": [_r(v_lo), _r(v_hi)]},
                "not_vetoed": {"n": len(passed), "mean": _r(p_mean), "ci95": [_r(p_lo), _r(p_hi)]}},
    }


def readers(judged: Iterable[Judged]) -> dict[str, Any]:
    """Every reader's entry; ``m`` (Bonferroni) is the number of readers that reach the sample. The readers without attribution are
    named, INSUFICIENTE, with why."""
    by: dict[str, list[Judged]] = defaultdict(list)
    for j in judged:
        by[j.reader].append(j)
    m = sum(1 for items in by.values() if _sized(items)[0])
    out: dict[str, Any] = {k: reader_entry(v, m=m) for k, v in sorted(by.items())}
    for agent, why in UNATTRIBUTED.items():
        if not any(k.startswith(agent + "/") for k in out):
            out[f"{agent}/*"] = {"verdict": "INSUFICIENTE", "missing": [why], "selections": 0, "examined": 0}
    return {"bonferroni": {"m": m, "level": round(1 - ALPHA / max(1, m), 6)}, "readers": out}


# ── sources ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Cited:
    """One fact a decision cited, as eval-sel-v1 judged it, with its source and the selection that cited it."""

    evidence_id: int
    source: str | None
    fact_type: str | None
    status: str
    day: date
    fixture_id: int
    selection: str
    clv: float | None


def sources(cited: Iterable[Cited]) -> dict[str, Any]:
    """Per (source, type): the share held among the resolved facts (each fact once), with Wilson, its relation to the pooled share of
    every other source's facts of that type, and the description of the CLV of the selections that cite it."""
    facts: dict[int, Cited] = {}
    selections: dict[tuple[str, str], dict[tuple[int, str], tuple[date, float]]] = defaultdict(dict)
    unknown = 0
    for c in cited:
        if c.source is None or c.fact_type not in FACT_TYPES:
            unknown += 1
            continue
        facts.setdefault(c.evidence_id, c)
        if c.clv is not None and math.isfinite(c.clv):
            selections[(c.source, c.fact_type)][(c.fixture_id, c.selection)] = (c.day, c.clv)
    cells: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"sostenido": 0, "contradicho": 0, "no_evaluable": 0})
    for f in facts.values():
        assert f.source is not None and f.fact_type is not None
        cells[(f.source, f.fact_type)][f.status if f.status in ("sostenido", "contradicho") else "no_evaluable"] += 1
    pooled: dict[str, tuple[int, int]] = {}
    for t in FACT_TYPES:
        held = sum(v["sostenido"] for (_, ft), v in cells.items() if ft == t)
        res = held + sum(v["contradicho"] for (_, ft), v in cells.items() if ft == t)
        pooled[t] = (held, res)
    out: list[dict[str, Any]] = []
    for (src, t), v in sorted(cells.items()):
        resolved = v["sostenido"] + v["contradicho"]
        share = _share(v["sostenido"], resolved)
        held_all, res_all = pooled[t]
        others = (held_all - v["sostenido"], res_all - resolved)
        rest = None if others[1] == 0 else others[0] / others[1]
        relation = "insuficiente"
        if resolved >= MIN_FACTS and share["ci95"] is not None and rest is not None:
            lo, hi = share["ci95"]
            relation = "por_encima" if lo > rest else "por_debajo" if hi < rest else "no_se_distingue"
        sels = list(selections.get((src, t), {}).values())
        mean, lo2, hi2 = by_day(sels)
        out.append({"source": src, "fact_type": t, "status": "medida" if resolved >= MIN_FACTS else "INSUFICIENTE",
                    "held": share, "unevaluable": v["no_evaluable"], "relation_to_others": relation,
                    "others_share": _r(rest, 4), "citing_selections": {"n": len(sels), "mean_clv": _r(mean), "ci95": [_r(lo2), _r(hi2)],
                                                                         "note": "descriptivo, no es un efecto"}})
    return {"min_facts": MIN_FACTS, "facts": len(facts), "without_source_or_type": unknown, "cells": out,
            "measured": sum(1 for c in out if c["status"] == "medida")}


def report(judged: Iterable[Judged], cited: Iterable[Cited], *, period: Mapping[str, str]) -> dict[str, Any]:
    """The whole report under the protocol: readers and sources. It keeps nothing and decides nothing."""
    return {"version": VERSION, "protocol": protocol.stamp(PROTOCOL), "signed_by_owner": False, "period": dict(period),
            "needed": {"examined": NEEDED, "days": MIN_DAYS, "discordant": MIN_DISCORDANT, "facts": MIN_FACTS},
            **readers(judged), "sources": sources(cited), "decides": False,
            "notice_es": "Informa, no decide: ningún peso, umbral ni versión cambia sin el aprendizaje controlado (AD-K07)."}


__all__ = ["AGAINST", "ALPHA", "DELTA", "FACT_TYPES", "MIN_DAYS", "MIN_DISCORDANT", "MIN_FACTS", "NEEDED", "NO_SIDE", "PROTOCOL",
           "REPLICATES", "RULES_STOP", "SEED", "SIGMA_PLAN", "UNATTRIBUTED", "VERDICTS", "VERSION", "Cited", "Judged", "by_day",
           "reader_entry", "reader_key", "readers", "report", "sources", "wilson"]
