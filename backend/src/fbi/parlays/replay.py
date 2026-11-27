"""The optimism of the joint probability of a parlay, measured on the history of the decisions the shadow kept (plan RP-11.1, finding H23,
``parlay-replay-v1``).

The question is the plan's: how much optimism is there in the joint of a parlay, said before the matches, against how often those combinations really came in?
The answer is built the way the plan says, and no more:

1. the legs are the selections of the shadow that were confirmed, with the probability the shadow gave them and, when it had one, the market's; each is settled
   (``win`` or ``loss``; a ``void`` or a leg not settled yet takes no part: it is counted apart, never filled in);
2. a combination is two or three legs of DIFFERENT matches and DIFFERENT teams that kick off on the same day (the rule of every parlay, ``fbi.parlays.engine
   .guard``, is not relaxed to get more combinations);
3. its joint is the product of its legs' probabilities (what a parlay without a correction says); it came in when every leg won;
4. per band of joint probability: the joint said (mean), the frequency that came in and the difference. Overall: the same, with an interval.

THE INTERVAL is what keeps the report honest. The combinations of one day share their legs, so they are not independent: counting them as if they were would
make the interval look far narrower than it is. The interval is a bootstrap that resamples whole DAYS (a block of every combination of the day) with a fixed seed,
and the report also gives the number of days and of distinct legs next to the number of combinations. No threshold is invented here: the plan asks for a report
with its interval and 1.500 combinations or more; whether the error is inside a bound is for the acceptance criteria the owner approved to say, so
``within_bound`` is never decided by this module.

Pure: it reads nothing and writes nothing.
"""

from __future__ import annotations

import itertools
import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

VERSION: Final = "parlay-replay-v1"
MAX_LEGS: Final = 3
MIN_COMBINATIONS: Final = 1500
"""The plan's acceptance: the calibration error is measured over this many combinations or more (the same number the door of the parlays asks)."""
BANDS: Final = ((0.0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.35), (0.35, 1.0001))
BOOTSTRAP: Final = 1000
SEED: Final = 20261127
Z: Final = 1.96


@dataclass(frozen=True, slots=True)
class Leg:
    chain_key: str
    fixture_id: int
    day: date
    teams: frozenset[int]
    p: float
    p_market: float | None
    result: str | None
    """The newest settlement of the leg: ``win``, ``loss``, ``void`` or None (not settled yet)."""


@dataclass(frozen=True, slots=True)
class Combination:
    day: date
    chains: tuple[str, ...]
    p_joint: float
    p_market_joint: float | None
    won: bool


def usable(legs: Sequence[Leg]) -> tuple[list[Leg], dict[str, int]]:
    """The legs that can be replayed and what was left out, said apart: a void leg, a leg not settled, a leg without a probability."""
    out: list[Leg] = []
    left = {"anuladas": 0, "sin_liquidar": 0, "sin_probabilidad": 0, "resultado_desconocido": 0}
    for leg in legs:
        if leg.result is None:
            left["sin_liquidar"] += 1
        elif leg.result == "void":
            left["anuladas"] += 1
        elif leg.result not in ("win", "loss"):
            left["resultado_desconocido"] += 1
        elif not 0.0 < leg.p < 1.0:
            left["sin_probabilidad"] += 1
        else:
            out.append(leg)
    return out, left


def combinations(legs: Sequence[Leg], *, max_legs: int = MAX_LEGS) -> list[Combination]:
    """Every combination of two to ``max_legs`` usable legs of one day, of distinct matches and with no team in two legs."""
    by_day: dict[date, list[Leg]] = defaultdict(list)
    for leg in legs:
        by_day[leg.day].append(leg)
    out: list[Combination] = []
    for day in sorted(by_day):
        pool = sorted(by_day[day], key=lambda leg: leg.chain_key)
        for size in range(2, max_legs + 1):
            for combo in itertools.combinations(pool, size):
                if len({leg.fixture_id for leg in combo}) != size:
                    continue
                teams = [t for leg in combo for t in leg.teams]
                if len(set(teams)) != len(teams):
                    continue
                market = [leg.p_market for leg in combo]
                out.append(Combination(day, tuple(leg.chain_key for leg in combo), math.prod(leg.p for leg in combo),
                                       None if any(m is None for m in market) else math.prod(m for m in market if m is not None),
                                       all(leg.result == "win" for leg in combo)))
    return out


def _stats(items: Sequence[Combination], *, market: bool = False) -> dict[str, Any]:
    pool = [c for c in items if c.p_market_joint is not None] if market else list(items)
    n = len(pool)
    if not n:
        return {"n": 0, "said": None, "came_in": None, "optimism": None}
    said = sum((c.p_market_joint if market else c.p_joint) or 0.0 for c in pool) / n
    came = sum(1 for c in pool if c.won) / n
    return {"n": n, "said": said, "came_in": came, "optimism": said - came}


def _bands(items: Sequence[Combination]) -> list[dict[str, Any]]:
    rows = []
    for low, high in BANDS:
        sel = [c for c in items if low <= c.p_joint < high]
        row = {"from": low, "to": min(high, 1.0), **_stats(sel)}
        rows.append(row)
    return rows


def _interval(items: Sequence[Combination], *, market: bool, seed: int = SEED, rounds: int = BOOTSTRAP) -> tuple[float, float] | None:
    """The 95 % interval of the optimism, resampling whole days (the combinations of a day share their legs)."""
    pool = [c for c in items if c.p_market_joint is not None] if market else list(items)
    days: dict[date, list[Combination]] = defaultdict(list)
    for c in pool:
        days[c.day].append(c)
    keys = sorted(days)
    if len(keys) < 2:
        return None
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(rounds):
        sample = [c for k in (rng.choice(keys) for _ in keys) for c in days[k]]
        draws.append(_stats(sample, market=market)["optimism"])
    draws.sort()
    return draws[int(0.025 * (len(draws) - 1))], draws[math.ceil(0.975 * (len(draws) - 1))]


def report(legs: Sequence[Leg], *, max_legs: int = MAX_LEGS, seed: int = SEED, rounds: int = BOOTSTRAP) -> dict[str, Any]:
    """The report of the replay: the combinations, the optimism overall and per band, with its interval, and what was left out."""
    usable_legs, left = usable(legs)
    combos = combinations(usable_legs, max_legs=max_legs)
    by_size: dict[int, int] = defaultdict(int)
    for c in combos:
        by_size[len(c.chains)] += 1
    overall = _stats(combos)
    interval = _interval(combos, market=False, seed=seed, rounds=rounds)
    market = _stats(combos, market=True)
    market_interval = _interval(combos, market=True, seed=seed, rounds=rounds)
    return {
        "version": VERSION, "legs": len(legs), "legs_replayed": len(usable_legs), "left_out": left,
        "combinations": len(combos), "by_size": dict(sorted(by_size.items())), "days": len({c.day for c in combos}),
        "distinct_legs": len({k for c in combos for k in c.chains}), "enough": len(combos) >= MIN_COMBINATIONS, "needed": MIN_COMBINATIONS,
        "model": {**overall, "interval": interval}, "market": {**market, "interval": market_interval}, "bands": _bands(combos),
        "within_bound": None,
        "note": "within_bound lo decide los criterios de aceptación aprobados, no este informe; el intervalo remuestrea días enteros porque las combinaciones "
                "de un día comparten sus selecciones.",
        "rule": "dos o tres selecciones de partidos y equipos distintos del mismo día; la conjunta es el producto; aciertan si todas aciertan",
    }


def legs_of(rows: Sequence[Mapping[str, Any]]) -> list[Leg]:
    """The legs from the rows the script reads (one per confirmed chain, with its newest settlement). Pure."""
    out = []
    for r in rows:
        p = r.get("p")
        out.append(Leg(str(r["chain_key"]), int(r["fixture_id"]), r["day"], frozenset(int(t) for t in r["teams"]),
                       0.0 if p is None else float(p), None if r.get("p_market") is None else float(r["p_market"]),
                       None if r.get("result") is None else str(r["result"])))
    return out


__all__ = ["BANDS", "MAX_LEGS", "MIN_COMBINATIONS", "VERSION", "Combination", "Leg", "combinations", "legs_of", "report", "usable"]
