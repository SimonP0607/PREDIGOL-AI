"""Dependence between parlay legs - measured from history, never assumed.

Within one match, selections are strongly dependent (a home win and over 2.5 share the same goals): a
parlay never holds two legs of one match, nor two of one team (``fbi.parlays.persist``). Across matches
the remaining dependence is the shared environment of a competition's matchday - refereeing, weather, a
league's scoring that weekend. It is measured here, per market, as the INTRA-CLASS CORRELATION of the
outcomes of the matches a competition played on the same day (one-way ANOVA estimator, standard error
by bootstrap over days), from settled results only.

How the parlays use it (rule ``parlay-v4``): the joint probability of the legs is the product of their
probabilities, corrected to second order (Bahadur) for the pairs that share a competition and a day -
but only with a correlation that is significantly NEGATIVE (its upper bound below zero), because a
positive one would RAISE the joint probability and the parlay is already priced at its pessimistic end:
an estimate is allowed to make a parlay look worse, never better. Every parlay also caps how many legs
one competition may hold (exposure), whatever the estimate.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row, tuple_row

VERSION = "icc-v1"
MARKETS = ("home_win", "draw", "away_win", "over_2_5", "btts")
BOOTSTRAP = 200
MIN_GROUPS = 30

OUTCOMES_SQL = """
SELECT f.competition_season_id AS grp_season, (f.kickoff_at AT TIME ZONE 'UTC')::date AS grp_day,
       r.outcome_1x2, r.total_goals, r.btts
  FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s AND r.outcome_1x2 IS NOT NULL
   AND r.total_goals IS NOT NULL AND r.btts IS NOT NULL
"""


@dataclass(frozen=True, slots=True)
class Estimate:
    market: str
    rho: float
    se: float
    n_groups: int
    n_matches: int

    @property
    def upper(self) -> float:
        return self.rho + 1.96 * self.se

    @property
    def significant_negative(self) -> bool:
        return self.n_groups >= MIN_GROUPS and self.upper < 0


def indicator(market: str, row: dict[str, Any]) -> int:
    if market == "home_win":
        return int(row["outcome_1x2"] == "Home")
    if market == "draw":
        return int(row["outcome_1x2"] == "Draw")
    if market == "away_win":
        return int(row["outcome_1x2"] == "Away")
    if market == "over_2_5":
        return int(int(row["total_goals"]) >= 3)
    if market == "btts":
        return int(bool(row["btts"]))
    raise ValueError(market)


def icc(groups: Sequence[Sequence[int]]) -> float:
    """One-way ANOVA intra-class correlation of 0/1 outcomes in groups of unequal size (>= 2 each)."""
    groups = [g for g in groups if len(g) >= 2]
    k = len(groups)
    n = sum(len(g) for g in groups)
    if k < 2 or n <= k:
        return 0.0
    grand = sum(sum(g) for g in groups) / n
    ssb = sum(len(g) * (sum(g) / len(g) - grand) ** 2 for g in groups)
    ssw = sum(sum((x - sum(g) / len(g)) ** 2 for x in g) for g in groups)
    msb = ssb / (k - 1)
    msw = ssw / (n - k)
    n0 = (n - sum(len(g) ** 2 for g in groups) / n) / (k - 1)
    denom = msb + (n0 - 1) * msw
    return 0.0 if denom <= 0 else (msb - msw) / denom


def estimate(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, seed: int = 7) -> list[Estimate]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(OUTCOMES_SQL, {"since": since, "until": until})
        rows = [dict(r) for r in cur.fetchall()]
    grouped: dict[tuple[int, date], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        grouped[(int(r["grp_season"]), r["grp_day"])].append(r)
    groups = [g for g in grouped.values() if len(g) >= 2]
    out: list[Estimate] = []
    rng = random.Random(seed)
    for market in MARKETS:
        data = [[indicator(market, r) for r in g] for g in groups]
        rho = icc(data)
        boots = []
        for _ in range(BOOTSTRAP if len(data) >= MIN_GROUPS else 0):
            sample = [data[rng.randrange(len(data))] for _ in range(len(data))]
            boots.append(icc(sample))
        se = statistics_stdev(boots) if len(boots) > 1 else 1.0
        out.append(Estimate(market, round(rho, 5), round(se, 5), len(data), sum(len(g) for g in data)))
    return out


def statistics_stdev(xs: Sequence[float]) -> float:
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def store(conn: psycopg.Connection[Any], estimates: list[Estimate], *, at: datetime, since: date, until: date) -> int:
    with conn.cursor(row_factory=tuple_row) as cur:
        for e in estimates:
            cur.execute("INSERT INTO ai.correlation_estimates (estimated_at, scope, market, rho, se, n_groups, n_matches, "
                        "window_from, window_to, version) VALUES (%s, 'same_competition_day', %s, %s, %s, %s, %s, %s, %s, %s)",
                        (at, e.market, e.rho, e.se, e.n_groups, e.n_matches, since, until, VERSION))
    return len(estimates)


def latest(conn: psycopg.Connection[Any]) -> dict[str, Estimate]:
    try:
        with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT DISTINCT ON (market) market, rho, se, n_groups, n_matches FROM ai.correlation_estimates "
                        "ORDER BY market, estimated_at DESC, id DESC")
            rows = [dict(r) for r in cur.fetchall()]
    except psycopg.errors.UndefinedTable:
        return {}
    return {r["market"]: Estimate(r["market"], float(r["rho"]), float(r["se"]), int(r["n_groups"]),
                                  int(r["n_matches"])) for r in rows}


def market_of(market_key: str, selection: str) -> str | None:
    """The measured market a selection belongs to (its outcome indicator), if any."""
    if market_key == "1X2":
        return {"Home": "home_win", "Draw": "draw", "Away": "away_win"}.get(selection)
    if market_key == "OU":
        return "over_2_5"
    if market_key == "BTTS":
        return "btts"
    return None


def joint_probability(probs: Sequence[float], pairs: Sequence[tuple[int, int, float]]) -> float:
    """P(all legs win) = prod(p) * (1 + sum over correlated pairs of rho_ij * sqrt((1-p_i)(1-p_j)/(p_i p_j))),
    the Bahadur expansion to second order; clipped to [0, min(p)]."""
    base = math.prod(probs)
    if base <= 0:
        return 0.0
    adj = 1.0
    for i, j, rho in pairs:
        pi, pj = probs[i], probs[j]
        if 0 < pi < 1 and 0 < pj < 1:
            adj += rho * math.sqrt((1 - pi) * (1 - pj) / (pi * pj))
    return max(0.0, min(min(probs), base * adj))
