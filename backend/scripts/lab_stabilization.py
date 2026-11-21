"""PM-10-08 (IA-154, protocol ``PM-10-08``): how many matches each team statistic needs to be stable, per league - OFF the server.

    python -m scripts.lab_stabilization <lab-export-v2 folder> --out <result.json> [--table backend/src/fbi/stats/stabilization_v1.json]

Reliability of a team's mean over n matches is the share of the spread between teams that is not chance:
R(n) = tau2 / (tau2 + s2w/n), with s2w the spread of one match around the team's own level (pooled within teams) and tau2 the real
spread between teams (method of moments: the variance of the season means minus the mean sampling variance s2w/n_i). So n_R =
R/(1-R) * s2w/tau2 matches give reliability R: n50 and n70. Each league pools its closed seasons weighting by teams; the interval
resamples teams inside each season. VALIDATION (the card: halves of the season): each team's matches in date order, first half
against second half; the Pearson correlation of the half means across teams must reach R(m) - 0.10 of the same league in 70 % of the
eligible leagues for the statistic to PASS. tau2 <= 0 is "does not stabilise in one season" (n is null).

Same data the web reads (``core.fixture_team_stats`` of source ``api-football``, as ``fbi.stats.data``); goals from the result.
Pure arithmetic after the export is read: no database, no network, no clock in the result. Nothing reads the table it writes: it may
propose RAISING a minimum (``max(current, n50)``), never lowering one without the owner's decision.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

KEY = "PM-10-08"
VERSION = "stabilization-v1"
RELIABILITIES = (0.5, 0.7)
MIN_TEAMS = 10
MIN_MATCHES = 10
MIN_COVERAGE = 0.8
MIN_SEASONS = 2
MIN_LEAGUES = 5
PASS_SHARE = 0.70
TOLERANCE = 0.10
BOOT = 1000
FROM_SEASON = 2019
CURRENT_MIN_MATCHES = 3
"""``fbi.stats.team.MIN_MATCHES`` (team-agg-v1) on 21-nov-2026: the convention this measurement may raise, never lower."""
SCOPES = (3, 5, 10, 20)
PRIORITY = (1, 2, 3, 4, 13, 49)

RAW = ("shots", "shots_on_target", "shots_inside_box", "corners", "fouls", "offsides", "yellow_cards", "saves", "possession_pct",
       "passes", "pass_accuracy", "expected_goals", "goals")


@dataclass(frozen=True, slots=True)
class StatDef:
    name: str
    column: str
    side: str  # "for" (the team's own value) or "against" (the rival's)


STATS: tuple[StatDef, ...] = tuple(
    [StatDef(f"{c}_for", c, "for") for c in RAW]
    + [StatDef(f"{c}_against", c, "against") for c in RAW if c != "possession_pct"]
)

ROWS_SQL = """
WITH m AS ({matches}),
ts AS (
  SELECT fixture_id, team_side, shots, shots_on_target, shots_inside_box, corners, fouls, offsides, yellow_cards, saves,
         possession_pct, passes, CASE WHEN passes > 0 THEN passes_accurate::DOUBLE / passes END AS pass_accuracy, expected_goals
    FROM core_fixture_team_stats WHERE source = 'api-football'
)
SELECT m.fixture_id, m.kickoff_at, m.comp, m.cs_id, m.season, side.s AS side,
       CASE WHEN side.s = 'home' THEN m.home ELSE m.away END AS team,
       {own}, {opp},
       CASE WHEN side.s = 'home' THEN m.gh ELSE m.ga END AS goals_for,
       CASE WHEN side.s = 'home' THEN m.ga ELSE m.gh END AS goals_against
  FROM m CROSS JOIN (VALUES ('home'), ('away')) side(s)
  LEFT JOIN ts o ON o.fixture_id = m.fixture_id AND o.team_side = side.s
  LEFT JOIN ts r ON r.fixture_id = m.fixture_id AND r.team_side <> side.s
 WHERE m.ctype = 'league' AND m.closed AND m.season >= {from_season}
 ORDER BY m.comp, m.season, team, m.kickoff_at, m.fixture_id
"""


def rows_sql(matches_sql: str) -> str:
    cols = [c for c in RAW if c != "goals"]
    own = ", ".join(f"o.{c} AS {c}_for" for c in cols)
    opp = ", ".join(f"r.{c} AS {c}_against" for c in cols if c != "possession_pct")
    return ROWS_SQL.format(matches=matches_sql, own=own, opp=opp, from_season=FROM_SEASON)


# ── the arithmetic (pure) ────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SeasonParts:
    """One league season of one statistic: per team, its values in date order."""

    teams: int
    s2w: float
    tau2: float
    half_r: float | None
    random_half_r: float | None
    half_m: int
    means: NDArray[np.float64]
    sizes: NDArray[np.float64]
    within: NDArray[np.float64]


def components(means: NDArray[np.float64], sizes: NDArray[np.float64], within: NDArray[np.float64]) -> tuple[float, float]:
    """(s2w, tau2): pooled within-team variance and the method-of-moments between-team variance."""
    dof = sizes - 1.0
    s2w = float((dof * within).sum() / dof.sum())
    tau2 = float(np.var(means, ddof=1) - np.mean(s2w / sizes))
    return s2w, tau2


def n_for(reliability: float, s2w: float, tau2: float) -> float | None:
    """Matches that make the reliability ``reliability``; None when there is no real spread between teams (tau2 <= 0)."""
    if tau2 <= 0 or s2w <= 0:
        return None
    return reliability / (1.0 - reliability) * s2w / tau2


def reliability_at(n: float, s2w: float, tau2: float) -> float:
    if tau2 <= 0:
        return 0.0
    return n / (n + s2w / tau2)


def _pearson(a: NDArray[np.float64], b: NDArray[np.float64]) -> float | None:
    if a.size < 3 or np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def season_parts(series: Sequence[NDArray[np.float64]], rng: np.random.Generator) -> SeasonParts | None:
    """``series``: one array per team (its values in date order, missing values already dropped)."""
    kept = [s for s in series if s.size >= MIN_MATCHES]
    if len(kept) < MIN_TEAMS:
        return None
    means = np.array([s.mean() for s in kept])
    sizes = np.array([float(s.size) for s in kept])
    within = np.array([s.var(ddof=1) for s in kept])
    s2w, tau2 = components(means, sizes, within)
    m = int(np.median([s.size // 2 for s in kept]))
    first = np.array([s[: s.size // 2].mean() for s in kept])
    second = np.array([s[s.size - s.size // 2:].mean() for s in kept])
    shuffled = [rng.permutation(s) for s in kept]
    r_first = np.array([s[: s.size // 2].mean() for s in shuffled])
    r_second = np.array([s[s.size - s.size // 2:].mean() for s in shuffled])
    return SeasonParts(len(kept), s2w, tau2, _pearson(first, second), _pearson(r_first, r_second), m, means, sizes, within)


def pooled(parts: Sequence[SeasonParts]) -> tuple[float, float]:
    w = np.array([p.teams for p in parts], dtype=np.float64)
    return float((w * [p.s2w for p in parts]).sum() / w.sum()), float((w * [p.tau2 for p in parts]).sum() / w.sum())


def bootstrap_n(parts: Sequence[SeasonParts], reliability: float, *, reps: int, rng: np.random.Generator
                ) -> tuple[float | None, float | None, float]:
    """Percentile interval of n_R when the teams of each season are resampled; and the share of replicas with tau2 <= 0."""
    w = np.array([p.teams for p in parts], dtype=np.float64)
    s2w_acc = np.zeros(reps)
    tau2_acc = np.zeros(reps)
    for p, wt in zip(parts, w, strict=True):
        idx = rng.integers(0, p.teams, size=(reps, p.teams))
        mu, n, v = p.means[idx], p.sizes[idx], p.within[idx]
        s2w = ((n - 1) * v).sum(axis=1) / (n - 1).sum(axis=1)
        tau2 = mu.var(axis=1, ddof=1) - (s2w[:, None] / n).mean(axis=1)
        s2w_acc += wt * s2w
        tau2_acc += wt * tau2
    s2w_b, tau2_b = s2w_acc / w.sum(), tau2_acc / w.sum()
    ok = tau2_b > 0
    vals = np.where(ok, reliability / (1 - reliability) * s2w_b / np.where(ok, tau2_b, 1.0), np.inf)
    with np.errstate(invalid="ignore"):
        lo, hi = np.quantile(vals, [0.025, 0.975])
    return (float(lo) if np.isfinite(lo) else None, float(hi) if np.isfinite(hi) else None, float((~ok).mean()))


def league_result(parts: Sequence[SeasonParts], *, rng: np.random.Generator, reps: int = BOOT) -> dict[str, Any]:
    s2w, tau2 = pooled(parts)
    out: dict[str, Any] = {"seasons": len(parts), "teams": int(sum(p.teams for p in parts)), "s2w": s2w, "tau2": tau2,
                           "ratio": (s2w / tau2) if tau2 > 0 else None}
    for r in RELIABILITIES:
        tag = f"n{int(r * 100)}"
        out[tag] = n_for(r, s2w, tau2)
        lo, hi, share = bootstrap_n(parts, r, reps=reps, rng=rng)
        out[f"{tag}_ci"] = [lo, hi]
        out[f"{tag}_no_spread_share"] = share
    out["reliability_at"] = {str(n): reliability_at(n, s2w, tau2) for n in SCOPES}
    observed = [p.half_r for p in parts if p.half_r is not None]
    predicted = [reliability_at(p.half_m, s2w, tau2) for p in parts if p.half_r is not None]
    randomised = [p.random_half_r for p in parts if p.random_half_r is not None]
    out["half_r"] = float(np.mean(observed)) if observed else None
    out["half_r_predicted"] = float(np.mean(predicted)) if predicted else None
    out["random_half_r"] = float(np.mean(randomised)) if randomised else None
    out["validated"] = bool(observed) and out["half_r"] >= out["half_r_predicted"] - TOLERANCE
    return out


def verdict(leagues: Mapping[int, Mapping[str, Any]]) -> tuple[str, float | None]:
    if len(leagues) < MIN_LEAGUES:
        return "INSUFICIENTE", None
    share = sum(1 for v in leagues.values() if v["validated"]) / len(leagues)
    return ("PASA" if share >= PASS_SHARE else "NO PASA"), share


def _median(values: Sequence[float | None]) -> float | None:
    """Median over leagues, a league that does not stabilise (None) counting as infinitely many matches."""
    vals = [math.inf if v is None else v for v in values]
    if not vals:
        return None
    m = float(np.median(vals))
    return m if math.isfinite(m) else None


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def measure(rows: Any, *, seed: int, reps: int = BOOT) -> dict[str, Any]:
    """``rows``: a pandas frame of ``rows_sql``. Returns the whole result (per statistic: verdict, global and per league)."""
    rng = np.random.default_rng(seed)
    result: dict[str, Any] = {}
    coverage: dict[str, dict[str, float]] = defaultdict(dict)
    for st in STATS:
        col = st.name
        if col not in rows.columns:
            continue
        per_league: dict[int, list[SeasonParts]] = defaultdict(list)
        for (comp, _season), g in rows.groupby(["comp", "season"], sort=True):
            present = g[col].notna()
            cov = float(present.mean()) if len(g) else 0.0
            coverage[col][f"{comp}:{_season}"] = cov
            if cov < MIN_COVERAGE:
                continue
            series = [t[col].dropna().to_numpy(dtype=np.float64) for _, t in g.groupby("team", sort=True)]
            parts = season_parts(series, rng)
            if parts is not None:
                per_league[int(comp)].append(parts)
        leagues = {comp: league_result(ps, rng=rng, reps=reps) for comp, ps in per_league.items() if len(ps) >= MIN_SEASONS}
        v, share = verdict(leagues)
        result[col] = {
            "verdict": v, "validated_share": share, "eligible_leagues": len(leagues),
            "n50_median": _median([x["n50"] for x in leagues.values()]),
            "n70_median": _median([x["n70"] for x in leagues.values()]),
            "no_spread_leagues": sum(1 for x in leagues.values() if x["n50"] is None),
            "reliability_at_median": {str(n): _median([x["reliability_at"][str(n)] for x in leagues.values()]) for n in SCOPES},
            "priority": {str(k): leagues[k] | {} for k in sorted(leagues) if k in PRIORITY},
            "leagues": {str(k): leagues[k] for k in sorted(leagues)},
        }
    return {"stats": result, "coverage": coverage}


def table_of(measured: Mapping[str, Any], stamp: Mapping[str, Any], names: Mapping[int, str]) -> dict[str, Any]:
    """The versioned file for ``fbi/stats``: only the statistics that PASS carry n50/n70; nothing reads it yet."""
    stats: dict[str, Any] = {}
    for name, r in measured["stats"].items():
        row: dict[str, Any] = {"verdict": r["verdict"], "eligible_leagues": r["eligible_leagues"]}
        if r["verdict"] == "PASA" and r["n50_median"] is None:
            row["note"] = "no se estabiliza en una temporada en la mayoría de las ligas: sin mínimo medido"
        elif r["verdict"] == "PASA":
            n50 = r["n50_median"]
            row |= {"n50": _round_up(n50), "n70": _round_up(r["n70_median"]),
                    "proposed_min_matches": max(CURRENT_MIN_MATCHES, _round_up(n50) or CURRENT_MIN_MATCHES),
                    "by_league": {k: {"name": names.get(int(k), k), "n50": _round_up(v["n50"]), "n70": _round_up(v["n70"])}
                                  for k, v in r["leagues"].items()}}
        stats[name] = row
    return {
        "version": VERSION, "protocol": dict(stamp.get("protocol", {})), "export": dict(stamp.get("export", {})),
        "method": ("n_R = R/(1-R) * s2w/tau2 por liga (temporadas cerradas desde 2019, ponderadas por equipos), validado con la "
                   "correlación entre primera y segunda mitad de temporada; mediana de las ligas. Solo informativo: puede subir un "
                   "mínimo de muestra, nunca bajarlo sin decisión del dueño."),
        "current_min_matches": CURRENT_MIN_MATCHES, "stats": stats,
    }


def _round_up(x: float | None) -> int | None:
    return None if x is None or not math.isfinite(x) else math.ceil(x)


def main(argv: Sequence[str] | None = None) -> int:
    from fbi.research import protocol
    from scripts import lab_pm_common as lc

    protocol.require(KEY)
    ap = argparse.ArgumentParser(prog="lab_stabilization", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--table", type=Path)
    ap.add_argument("--reps", type=int, default=BOOT)
    args = ap.parse_args(argv)
    con = lc.open_export(args.folder, need=("core.fixtures", "core.fixture_results", "core.fixture_team_stats"))
    rows = con.sql(rows_sql(lc.MATCHES_SQL)).df()
    seed = protocol.require(KEY).seed
    measured = measure(rows, seed=seed, reps=args.reps)
    names = dict(con.sql("SELECT id, name FROM core_competitions").fetchall())
    st = lc.stamp(KEY, args.folder).as_json()
    lc.write_json(args.out, {"stamp": st, "rows": len(rows), **measured,
                             "names": {str(k): v for k, v in names.items()}})
    if args.table:
        lc.write_json(args.table, table_of(measured, st, names))
    for name, r in measured["stats"].items():
        print(f"{name:28s} {r['verdict']:12s} ligas={r['eligible_leagues']:3d} n50={r['n50_median']} n70={r['n70_median']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
