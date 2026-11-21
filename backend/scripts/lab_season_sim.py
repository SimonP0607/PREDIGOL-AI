"""PM-09-07 (IA-156, protocol ``PM-09-07``): season probabilities by simulation, validated on CLOSED seasons - OFF the server.

    python -m scripts.lab_season_sim <lab-export-v2 folder> --out <result.json> [--sims 10000]

For every closed double round-robin league season (10 to 24 teams, every ordered pair exactly once, all played) and two cuts (the
kick-off of the first match that leaves at least 1/3 and 2/3 of the matches played), the matches left are played out ``sims`` times
with the score distributions of OUR goal model - ``fbi.competitions.scenario_store.fit_scores``, the very function scenarios-v2 uses
(Dixon-Coles with the promoted spec, Poisson fallback, 730 days of the same competition, results known 3 h after kick-off) - and with
a reference where every team is equal (a Poisson with only the league's mean home and away goals in that training window). Tables are
ranked by points (3/1/0), goal difference, goals for and a seeded draw. Each objective (champion, top four, bottom three) gets the
share of seasons that meet it; the truth is the final table of the real results (a tie after goals for across the objective's line
counts as met in equal parts). Brier, Brier skill score with a bootstrap of league seasons, ECE in 10 equal groups and the extreme
groups against Wilson intervals: the rule of the protocol.

The probabilities stay in the LAB: publishing them needs DM-14 and the owner's signature. Uses production code read-only; no database.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

KEY = "PM-09-07"
SIMS = 10_000
CUTS = (1, 2)
OBJECTIVES = ("champion", "top4", "bottom3")
MIN_TEAMS, MAX_TEAMS = 10, 24
FROM_SEASON, TO_SEASON = 2019, 2025
MIN_SEASONS = 100
BOOT = 2000
ECE_MAX = 0.03
EXTREME = (0.1, 0.9)
EXTREME_MIN = 20
SCORE_CAP = 10


@dataclass(frozen=True, slots=True)
class Game:
    fixture_id: int
    kickoff_at: datetime
    home: int
    away: int
    gh: int
    ga: int


def is_double_round_robin(games: Sequence[Game]) -> tuple[bool, int]:
    teams = {g.home for g in games} | {g.away for g in games}
    n = len(teams)
    pairs = {(g.home, g.away) for g in games}
    ok = MIN_TEAMS <= n <= MAX_TEAMS and len(games) == n * (n - 1) == len(pairs) and all(g.home != g.away for g in games)
    return ok, n


def cut_index(n_games: int, k: int) -> int:
    """Index (in kick-off order) of the first match that leaves at least k/3 of the matches played."""
    return max(0, math.ceil(k * n_games / 3) - 1)


def table_points(teams: Sequence[int], games: Sequence[Game]) -> dict[int, tuple[int, int, int]]:
    pts = dict.fromkeys(teams, 0)
    gd = dict.fromkeys(teams, 0)
    gf = dict.fromkeys(teams, 0)
    for g in games:
        gf[g.home] += g.gh
        gf[g.away] += g.ga
        gd[g.home] += g.gh - g.ga
        gd[g.away] += g.ga - g.gh
        if g.gh > g.ga:
            pts[g.home] += 3
        elif g.gh < g.ga:
            pts[g.away] += 3
        else:
            pts[g.home] += 1
            pts[g.away] += 1
    return {t: (pts[t], gd[t], gf[t]) for t in teams}


def truth(final: Mapping[int, tuple[int, int, int]], n: int) -> dict[str, dict[int, float]]:
    """Whether each team met each objective in the real final table; a tie after goals for across a line is shared."""
    order = sorted(final, key=lambda t: final[t], reverse=True)
    out: dict[str, dict[int, float]] = {o: {} for o in OBJECTIVES}
    lines = {"champion": (0, 1), "top4": (0, 4), "bottom3": (n - 3, n)}
    for obj, (lo, hi) in lines.items():
        for t in order:
            key = final[t]
            tied = [i for i, u in enumerate(order) if final[u] == key]
            inside = sum(1 for i in tied if lo <= i < hi)
            out[obj][t] = inside / len(tied)
    return out


def simulate(teams: Sequence[int], start: Mapping[int, tuple[int, int, int]], left: Sequence[tuple[int, int]],
             matrices: Sequence[NDArray[np.float64]], *, sims: int, rng: np.random.Generator) -> dict[str, dict[int, float]]:
    """Share of simulated seasons in which each team meets each objective. ``left``: (home, away) of each match left, with its
    score matrix in ``matrices`` (rows home goals, columns away goals)."""
    n = len(teams)
    idx = {t: i for i, t in enumerate(teams)}
    pts = np.tile(np.array([start[t][0] for t in teams], dtype=np.int64), (sims, 1))
    gd = np.tile(np.array([start[t][1] for t in teams], dtype=np.int64), (sims, 1))
    gf = np.tile(np.array([start[t][2] for t in teams], dtype=np.int64), (sims, 1))
    for (h, a), m in zip(left, matrices, strict=True):
        flat = np.asarray(m, dtype=np.float64).ravel()
        cdf = np.cumsum(flat / flat.sum())
        draw = np.minimum(np.searchsorted(cdf, rng.random(sims), side="right"), flat.size - 1)
        hg, ag = np.divmod(draw, m.shape[1])
        i, j = idx[h], idx[a]
        gf[:, i] += hg
        gf[:, j] += ag
        gd[:, i] += hg - ag
        gd[:, j] += ag - hg
        pts[:, i] += np.where(hg > ag, 3, np.where(hg == ag, 1, 0))
        pts[:, j] += np.where(ag > hg, 3, np.where(hg == ag, 1, 0))
    key = (pts * 1_000_000 + (gd + 500) * 1_000 + gf).astype(np.float64) + rng.random((sims, n)) * 0.5
    rank = np.argsort(np.argsort(-key, axis=1), axis=1)  # 0 = first
    return {
        "champion": {t: float((rank[:, idx[t]] == 0).mean()) for t in teams},
        "top4": {t: float((rank[:, idx[t]] < 4).mean()) for t in teams},
        "bottom3": {t: float((rank[:, idx[t]] >= n - 3).mean()) for t in teams},
    }


def poisson_matrix(lh: float, la: float, cap: int = SCORE_CAP) -> NDArray[np.float64]:
    k = np.arange(cap + 1)
    ph = np.exp(-lh) * lh ** k / np.array([math.factorial(int(i)) for i in k])
    pa = np.exp(-la) * la ** k / np.array([math.factorial(int(i)) for i in k])
    m = np.outer(ph, pa)
    return m / m.sum()


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def brier(p: NDArray[np.float64], y: NDArray[np.float64]) -> float:
    return float(np.mean((p - y) ** 2))


def ece(p: NDArray[np.float64], y: NDArray[np.float64], bins: int = 10) -> float:
    order = np.argsort(p, kind="stable")
    groups = np.array_split(order, bins)
    return float(sum(len(g) / p.size * abs(p[g].mean() - y[g].mean()) for g in groups if len(g)))


def bss_interval(p: NDArray[np.float64], q: NDArray[np.float64], y: NDArray[np.float64], blocks: NDArray[np.int64], *, reps: int,
                 seed: int) -> tuple[float, float, float]:
    """Brier skill score of ``p`` against the reference ``q`` and its percentile interval (whole blocks resampled)."""
    ids, inv = np.unique(blocks, return_inverse=True)
    se_p = np.bincount(inv, weights=(p - y) ** 2, minlength=ids.size)
    se_q = np.bincount(inv, weights=(q - y) ** 2, minlength=ids.size)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, ids.size, size=(reps, ids.size))
    boot = 1.0 - se_p[draws].sum(axis=1) / se_q[draws].sum(axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return float(1.0 - se_p.sum() / se_q.sum()), float(lo), float(hi)


def extremes(p: NDArray[np.float64], y: NDArray[np.float64]) -> list[dict[str, Any]]:
    from scripts.lab_pm_common import wilson

    out = []
    for name, mask in (("p<=0.1", p <= EXTREME[0]), ("p>=0.9", p >= EXTREME[1])):
        n = int(mask.sum())
        if n == 0:
            continue
        lo, hi = wilson(float(y[mask].sum()), n)
        mean_p = float(p[mask].mean())
        out.append({"group": name, "n": n, "mean_p": mean_p, "observed": float(y[mask].mean()), "wilson": [lo, hi],
                    "counts": n >= EXTREME_MIN, "ok": (n < EXTREME_MIN) or (lo <= mean_p <= hi)})
    return out


def evaluate(units: Sequence[Mapping[str, Any]], *, seed: int, reps: int = BOOT) -> dict[str, Any]:
    """``units``: one per (league season, cut, objective, team) with ``p``, ``q`` (reference), ``y`` and ``season_block``."""
    res: dict[str, Any] = {}
    all_ok = True
    blocks_seen = {u["season_block"] for u in units}
    for cut in CUTS:
        for obj in OBJECTIVES:
            sel = [u for u in units if u["cut"] == cut and u["objective"] == obj]
            if not sel:
                all_ok = False
                continue
            p = np.array([u["p"] for u in sel])
            q = np.array([u["q"] for u in sel])
            y = np.array([u["y"] for u in sel])
            b = np.array([u["season_block"] for u in sel], dtype=np.int64)
            bss, lo, hi = bss_interval(p, q, y, b, reps=reps, seed=seed)
            e = ece(p, y)
            ext = extremes(p, y)
            ok = lo > 0 and e <= ECE_MAX and all(x["ok"] for x in ext)
            all_ok &= ok
            eps = 1e-12
            log_p = float(np.mean(-(y * np.log(np.clip(p, eps, 1)) + (1 - y) * np.log(np.clip(1 - p, eps, 1)))))
            res[f"{obj}@{cut}/3"] = {"n": len(sel), "brier": brier(p, y), "brier_ref": brier(q, y), "bss": bss, "bss_ci": [lo, hi],
                                     "ece": e, "ece_ref": ece(q, y), "extremes": ext, "log_score": log_p, "ok": ok}
    seasons = len(blocks_seen)
    verdict = "INSUFICIENTE" if seasons < MIN_SEASONS else "PASA" if all_ok else "NO PASA"
    return {"verdict": verdict, "league_seasons": seasons, "by_objective": res}


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def run(con: Any, *, sims: int, seed: int, xi: float, penalty: float, history_days: int, log: Any = print
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from fbi.competitions import scenario_store as ss
    from scripts import lab_pm_common as lc

    df = con.sql(f"SELECT * FROM ({lc.MATCHES_SQL}) m WHERE ctype = 'league' ORDER BY comp, kickoff_at, fixture_id").df()
    standings = _final_standings(con)
    spec = ss.GoalSpec(xi, penalty, history_days)
    rng = np.random.default_rng(seed)
    units: list[dict[str, Any]] = []
    audit: dict[str, Any] = {"considered": 0, "not_double_round_robin": 0, "provider_points_differ": 0, "no_provider_table": 0,
                             "fit_failed_cuts": 0, "evaluated": 0, "line_ties": 0, "seasons": []}
    history_by_comp: dict[int, list[Any]] = defaultdict(list)
    for r in df.itertuples(index=False):
        history_by_comp[int(r.comp)].append(ss.Played(r.kickoff_at.to_pydatetime(), int(r.home), int(r.away), int(r.gh), int(r.ga),
                                                      bool(r.neutral)))
    block = 0
    for (comp, cs_id, season), g in df.groupby(["comp", "cs_id", "season"], sort=True):
        if not (FROM_SEASON <= int(season) <= TO_SEASON) or not bool(g["closed"].iloc[0]):
            continue
        audit["considered"] += 1
        games = [Game(int(x.fixture_id), x.kickoff_at.to_pydatetime(), int(x.home), int(x.away), int(x.gh), int(x.ga))
                 for x in g.itertuples(index=False)]
        ok, n = is_double_round_robin(games)
        if not ok:
            audit["not_double_round_robin"] += 1
            continue
        teams = sorted({x.home for x in games} | {x.away for x in games})
        final = table_points(teams, games)
        prov = standings.get(int(cs_id))
        if prov is None:
            audit["no_provider_table"] += 1
        elif any(prov.get(t) != final[t][0] for t in teams):
            audit["provider_points_differ"] += 1
            continue
        tr = truth(final, n)
        audit["line_ties"] += sum(1 for o in OBJECTIVES for v in tr[o].values() if 0 < v < 1)
        games.sort(key=lambda x: (x.kickoff_at, x.fixture_id))
        block += 1
        for cut in CUTS:
            cut_at = games[cut_index(len(games), cut)].kickoff_at
            played = [x for x in games if x.kickoff_at <= cut_at]
            left = [x for x in games if x.kickoff_at > cut_at]
            if not left:
                continue
            at = cut_at + ss.RESULT_AVAILABLE_AFTER + timedelta(minutes=1)
            history = [m for m in history_by_comp[int(comp)] if m.kickoff_at <= cut_at]
            targets = [ss.Target(x.fixture_id, x.home, x.away) for x in left]
            scores, info = ss.fit_scores(history, targets, at=at, spec=spec)
            if "error" in info or len(scores) != len(left):
                audit["fit_failed_cuts"] += 1
                continue
            start = table_points(teams, played)
            pairs = [(x.home, x.away) for x in left]
            model = simulate(teams, start, pairs, [scores[x.fixture_id] for x in left], sims=sims, rng=rng)
            train = [m for m in history if m.kickoff_at + ss.RESULT_AVAILABLE_AFTER < at
                     and m.kickoff_at >= at - timedelta(days=history_days)]
            mh = float(np.mean([m.home_goals for m in train]))
            ma = float(np.mean([m.away_goals for m in train]))
            ref_m = poisson_matrix(mh, ma)
            ref = simulate(teams, start, pairs, [ref_m] * len(left), sims=sims, rng=rng)
            for obj in OBJECTIVES:
                for t in teams:
                    units.append({"season_block": block, "comp": int(comp), "season": int(season),
                                  "cut": cut, "objective": obj, "team": t, "p": model[obj][t], "q": ref[obj][t], "y": tr[obj][t]})
            audit["evaluated"] += 1
        audit["seasons"].append({"comp": int(comp), "season": int(season), "teams": n})
        log(f"{comp}:{season} n={n} units={len(units)}")
    return units, audit


def _final_standings(con: Any) -> dict[int, dict[int, int]]:
    """The provider's last table of each season (points by team), from core.standings; seasons with groups are skipped."""
    rows = con.execute("""
        WITH last AS (SELECT competition_season_id AS cs, max(snapshot_at) AS at FROM core_standings GROUP BY 1)
        SELECT s.competition_season_id, s.team_id, s.points, s."group"
          FROM core_standings s JOIN last l ON l.cs = s.competition_season_id AND l.at = s.snapshot_at
    """).fetchall()
    out: dict[int, dict[int, int]] = defaultdict(dict)
    groups: dict[int, set[Any]] = defaultdict(set)
    for cs, team, points, group in rows:
        out[int(cs)][int(team)] = int(points) if points is not None else -1
        groups[int(cs)].add(group)
    return {cs: v for cs, v in out.items() if len(groups[cs]) == 1}


def main(argv: Sequence[str] | None = None) -> int:
    import json

    from fbi.research import protocol
    from scripts import lab_pm_common as lc

    p = protocol.require(KEY)
    ap = argparse.ArgumentParser(prog="lab_season_sim", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sims", type=int, default=SIMS)
    args = ap.parse_args(argv)
    con = lc.open_export(args.folder, need=("core.fixtures", "core.fixture_results", "core.standings",
                                            "analytics.promoted_forecast_spec"))
    spec_row = lc.one(con, "SELECT spec FROM analytics_promoted_forecast_spec ORDER BY promoted_at DESC LIMIT 1")
    spec = json.loads(spec_row[0]) if spec_row else {}
    hyper = spec["goal"]["dixon_coles"]
    units, audit = run(con, sims=args.sims, seed=p.seed, xi=float(hyper["xi"]), penalty=float(hyper["penalty"]),
                       history_days=int(spec.get("history_days", 730)))
    ev = evaluate(units, seed=p.seed)
    lc.write_json(args.out, {"stamp": lc.stamp(KEY, args.folder).as_json(), "spec": spec, "sims": args.sims, "audit": audit,
                             **ev, "by_priority": _by(units, lambda u: "prioritarias" if u["comp"] in lc.PRIORITY else "resto",
                                                     p.seed)})
    print(json.dumps({"verdict": ev["verdict"], "league_seasons": ev["league_seasons"]}, ensure_ascii=False))
    for k, v in ev["by_objective"].items():
        print(f"{k:14s} n={v['n']:5d} bss={v['bss']:.3f} [{v['bss_ci'][0]:.3f}, {v['bss_ci'][1]:.3f}] ece={v['ece']:.3f} ok={v['ok']}")
    return 0


def _by(units: Sequence[Mapping[str, Any]], key: Any, seed: int) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for u in units:
        groups[key(u)].append(u)
    return {k: evaluate(v, seed=seed)["by_objective"] for k, v in groups.items()}


if __name__ == "__main__":
    raise SystemExit(main())
