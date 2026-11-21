"""PM-08-07 (IA-155, protocol ``PM-08-07``): the profile cards that must be measured before they are built - OFF the server.

    python -m scripts.lab_fichas <lab-export-v2 folder> --out <result.json> [--rules backend/config/rules]

One verdict per card (PASA, NO PASA or INSUFICIENTE), each with its rule from the protocol:

* E, style of play: eight per-match dimensions (possession, passes, pass accuracy, shots, share of shots inside the box, corners,
  fouls, offsides); season s against s+1 of the teams that stay in the same league (Spearman across teams), and their coverage;
* P, similar teams: the 3 nearest neighbours (standardised dimensions inside the league season) in the first half of the season
  against the second half (Jaccard), against the Jaccard expected by chance;
* A, players one yellow card from a ban: the yellow cards with a player in the events against the team statistics, per competition
  season, AND the accumulation rule coded in ``config/rules`` (without it the card is not built, whatever the data say);
* T, the coach of the match: share of match sides with a coach id (tracked competitions);
* I, open identity of referees and coaches: share of distinct people with an external identifier in ``core.entity_ids``.

The coach's career is not here (OP-12). A PASS builds nothing: building is another task with the owner's decision.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

KEY = "PM-08-07"
DIMS = ("possession_pct", "passes", "pass_accuracy", "shots", "inside_share", "corners", "fouls", "offsides")
STYLE_SEASONS = (2021, 2025)
COVERAGE_FROM = datetime(2024, 7, 1, tzinfo=UTC)
MIN_TEAMS = 10
MIN_HALF = 10
MIN_MATCHES = 10
K = 3
REPS = 2000
ACCUMULATION_WORDS = ("accumulat", "acumulaci", "suspension_after", "yellow_card_ban", "amonestaciones")


# ── E: style stability ───────────────────────────────────────────────────────────────────────────────────────────────────────


def spearman(a: NDArray[np.float64], b: NDArray[np.float64]) -> float | None:
    if a.size < 3:
        return None
    ra = np.argsort(np.argsort(a)).astype(np.float64)
    rb = np.argsort(np.argsort(b)).astype(np.float64)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def style_stability(means: Mapping[tuple[int, int], Mapping[int, NDArray[np.float64]]]) -> dict[str, Any]:
    """``means[(league, season)][team]`` = the eight dimension means. Pairs of consecutive seasons with >= MIN_TEAMS teams in both."""
    per_dim: dict[str, list[float]] = {d: [] for d in DIMS}
    pairs = 0
    for (league, season), teams in sorted(means.items()):
        nxt = means.get((league, season + 1))
        if nxt is None:
            continue
        common = sorted(set(teams) & set(nxt))
        if len(common) < MIN_TEAMS:
            continue
        pairs += 1
        a = np.array([teams[t] for t in common])
        b = np.array([nxt[t] for t in common])
        for j, d in enumerate(DIMS):
            ok = ~np.isnan(a[:, j]) & ~np.isnan(b[:, j])
            if ok.sum() >= MIN_TEAMS:
                r = spearman(a[ok, j], b[ok, j])
                if r is not None:
                    per_dim[d].append(r)
    medians = {d: (float(np.median(v)) if v else None) for d, v in per_dim.items()}
    return {"pairs": pairs, "median_spearman": medians, "pairs_per_dim": {d: len(v) for d, v in per_dim.items()}}


# ── P: similar teams ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def neighbours(x: NDArray[np.float64], k: int = K) -> list[set[int]]:
    z = (x - x.mean(axis=0)) / np.where(x.std(axis=0) > 0, x.std(axis=0), 1.0)
    d = np.sqrt(((z[:, None, :] - z[None, :, :]) ** 2).sum(axis=2))
    np.fill_diagonal(d, np.inf)
    return [set(np.argsort(row, kind="stable")[:k].tolist()) for row in d]


def jaccard(a: set[int], b: set[int]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def jaccard_by_chance(n: int, k: int = K) -> float:
    """Expected Jaccard of two independent random k-sets out of the n - 1 other teams (hypergeometric overlap)."""
    m = n - 1
    total = math.comb(m, k)
    return sum(math.comb(k, x) * math.comb(m - k, k - x) / total * (x / (2 * k - x)) for x in range(0, k + 1))


def similar_stability(halves: Mapping[tuple[int, int], tuple[NDArray[np.float64], NDArray[np.float64]]], *, seed: int
                      ) -> dict[str, Any]:
    """``halves[(league, season)]`` = (first-half means, second-half means), same team order; rows with a missing value dropped."""
    vals: list[float] = []
    chance: list[float] = []
    for _key, (a, b) in sorted(halves.items()):
        ok = ~np.isnan(a).any(axis=1) & ~np.isnan(b).any(axis=1)
        if ok.sum() < MIN_TEAMS:
            continue
        na, nb = neighbours(a[ok]), neighbours(b[ok])
        vals.append(float(np.mean([jaccard(x, y) for x, y in zip(na, nb, strict=True)])))
        chance.append(jaccard_by_chance(int(ok.sum())))
    if not vals:
        return {"league_seasons": 0}
    v = np.array(vals)
    rng = np.random.default_rng(seed)
    boot = v[rng.integers(0, v.size, size=(REPS, v.size))].mean(axis=1)
    lo, hi = np.quantile(boot, [0.025, 0.975])
    return {"league_seasons": int(v.size), "mean_jaccard": float(v.mean()), "ci": [float(lo), float(hi)],
            "chance": float(np.mean(chance))}


# ── A, T, I ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def accumulation_rule_coded(rules_dir: Path | None) -> dict[str, Any]:
    """What the coded regulations say about yellow-card accumulation (a ban after N yellows), read literally from the YAML files."""
    if rules_dir is None or not rules_dir.exists():
        return {"read": False, "files": 0, "with_accumulation": []}
    files = sorted(rules_dir.glob("*/*.yaml"))
    hits, fair_play = [], []
    for f in files:
        text = f.read_text(encoding="utf-8").lower()
        if any(w in text for w in ACCUMULATION_WORDS):
            hits.append(f.parent.name)
        if "disciplinary_points" in text or "fair_play" in text or "yellow_cards_fewer" in text:
            fair_play.append(f.parent.name)
    return {"read": True, "files": len(files), "with_accumulation": sorted(set(hits)), "only_fair_play_tiebreak": sorted(set(fair_play))}


def verdicts(e: Mapping[str, Any], e_cov: float, p: Mapping[str, Any], a: Mapping[str, Any], t: Mapping[str, Any],
             i: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    if e["pairs"] < 30:
        out["E"] = "INSUFICIENTE"
    else:
        strong = sum(1 for v in e["median_spearman"].values() if v is not None and v >= 0.6)
        out["E"] = "PASA" if strong >= 5 and e_cov >= 0.5 else "NO PASA"
    if p.get("league_seasons", 0) < 30:
        out["P"] = "INSUFICIENTE"
    else:
        out["P"] = "PASA" if p["ci"][0] >= 0.40 and p["ci"][0] >= p["chance"] + 0.15 else "NO PASA"
    if a["league_seasons"] < 20:
        out["A"] = "INSUFICIENTE"
    elif a["share_agree"] < 0.80:
        out["A"] = "NO PASA"
    else:
        out["A"] = "PASA" if a["rule"]["with_accumulation"] else "INSUFICIENTE"
    out["T"] = "INSUFICIENTE" if t["league_seasons"] < 20 else ("PASA" if t["share"] >= 0.90 else "NO PASA")
    if i["referees"] < 200 or i["coaches"] < 200:
        out["I"] = "INSUFICIENTE"
    else:
        out["I"] = "PASA" if i["referee_share"] >= 0.80 and i["coach_share"] >= 0.80 else "NO PASA"
    return out


# ── the run ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

STYLE_SQL = """
WITH m AS ({matches}),
ts AS (SELECT * FROM core_fixture_team_stats WHERE source = 'api-football')
SELECT m.comp, m.season, m.kickoff_at, m.fixture_id, CASE WHEN o.team_side = 'home' THEN m.home ELSE m.away END AS team,
       o.possession_pct, o.passes, CASE WHEN o.passes > 0 THEN o.passes_accurate::DOUBLE / o.passes END AS pass_accuracy,
       o.shots, CASE WHEN o.shots > 0 THEN o.shots_inside_box::DOUBLE / o.shots END AS inside_share, o.corners, o.fouls, o.offsides
  FROM m JOIN ts o ON o.fixture_id = m.fixture_id
 WHERE m.ctype = 'league' AND m.closed AND m.season BETWEEN {lo} AND {hi}
 ORDER BY m.comp, m.season, team, m.kickoff_at, m.fixture_id
"""


def run(con: Any, *, rules_dir: Path | None, seed: int) -> dict[str, Any]:
    from scripts import lab_pm_common as lc

    st = con.sql(STYLE_SQL.format(matches=lc.MATCHES_SQL, lo=STYLE_SEASONS[0], hi=STYLE_SEASONS[1])).df()
    # coverage of the eight dimensions per league season (team-match rows with all eight, over all finished league matches x 2)
    played = con.sql(f"SELECT comp, season, count(*) * 2 AS sides FROM ({lc.MATCHES_SQL}) m WHERE ctype = 'league' AND closed "
                     f"AND season BETWEEN {STYLE_SEASONS[0]} AND {STYLE_SEASONS[1]} GROUP BY 1, 2").fetchall()
    full = st.dropna(subset=list(DIMS)).groupby(["comp", "season"]).size().to_dict()
    cov = {(int(c), int(s)): (full.get((c, s), 0) / n if n else 0.0) for c, s, n in played}
    e_cov = float(np.mean([v >= 0.8 for v in cov.values()])) if cov else 0.0
    means: dict[tuple[int, int], dict[int, NDArray[np.float64]]] = defaultdict(dict)
    halves: dict[tuple[int, int], tuple[list[NDArray[np.float64]], list[NDArray[np.float64]]]] = defaultdict(lambda: ([], []))
    for (comp, season, team), g in st.groupby(["comp", "season", "team"], sort=True):
        x = g[list(DIMS)].to_numpy(dtype=np.float64)
        if len(g) >= MIN_MATCHES:
            with np.errstate(invalid="ignore"):
                col_n = (~np.isnan(x)).sum(axis=0)
                mu = np.where(col_n >= MIN_MATCHES, np.nanmean(np.where(np.isnan(x), np.nan, x), axis=0), np.nan)
            means[(int(comp), int(season))][int(team)] = mu
        h = len(g) // 2
        if h >= MIN_HALF:
            with np.errstate(invalid="ignore"):
                halves[(int(comp), int(season))][0].append(np.nanmean(x[:h], axis=0))
                halves[(int(comp), int(season))][1].append(np.nanmean(x[len(g) - h:], axis=0))
    e = style_stability(means)
    p = similar_stability({k: (np.array(a), np.array(b)) for k, (a, b) in halves.items() if len(a) >= MIN_TEAMS}, seed=seed)

    since = COVERAGE_FROM.date().isoformat()
    a_rows = con.execute(f"""
        WITH m AS ({lc.MATCHES_SQL}),
        ts AS (SELECT fixture_id, team_side, yellow_cards FROM core_fixture_team_stats
                WHERE source = 'api-football' AND yellow_cards IS NOT NULL),
        ev AS (SELECT fixture_id, team_side, count(*) AS y FROM core_fixture_events
                WHERE source = 'api-football' AND event_type = 'Card' AND detail = 'Yellow Card' AND provider_player_id IS NOT NULL
                GROUP BY 1, 2)
        SELECT m.cs_id, m.comp, m.ctype, avg(CASE WHEN coalesce(ev.y, 0) = ts.yellow_cards THEN 1.0 ELSE 0.0 END) AS agree,
               count(*) AS sides
          FROM m JOIN ts ON ts.fixture_id = m.fixture_id LEFT JOIN ev ON ev.fixture_id = m.fixture_id AND ev.team_side = ts.team_side
         WHERE m.kickoff_at >= TIMESTAMPTZ '{since}' GROUP BY 1, 2, 3
    """).fetchall()
    rule = accumulation_rule_coded(rules_dir)
    a_ok = [r for r in a_rows if r[3] >= 0.95]
    a = {"league_seasons": len(a_rows), "share_agree": (len(a_ok) / len(a_rows)) if a_rows else 0.0,
         "median_agree": float(np.median([r[3] for r in a_rows])) if a_rows else None,
         "by_priority": _share_by(a_rows, lambda r: r[1] in lc.PRIORITY, lambda r: r[3] >= 0.95), "rule": rule}

    t_rows = con.sql(f"""
        WITH m AS ({lc.MATCHES_SQL})
        SELECT m.cs_id, m.comp, count(*) * 2 AS sides,
               count(l1.coach_id) + count(l2.coach_id) AS with_coach
          FROM m
          LEFT JOIN core_fixture_lineups l1 ON l1.fixture_id = m.fixture_id AND l1.team_side = 'home' AND l1.source = 'api-football'
          LEFT JOIN core_fixture_lineups l2 ON l2.fixture_id = m.fixture_id AND l2.team_side = 'away' AND l2.source = 'api-football'
         WHERE m.is_tracked AND m.kickoff_at >= TIMESTAMPTZ '{since}' GROUP BY 1, 2
    """).fetchall()
    sides = sum(r[2] for r in t_rows)
    t = {"league_seasons": len(t_rows), "sides": int(sides), "share": (sum(r[3] for r in t_rows) / sides) if sides else 0.0,
         "priority_share": _ratio([r for r in t_rows if r[1] in lc.PRIORITY], 3, 2)}

    ref = lc.one(con, f"""
        WITH m AS ({lc.MATCHES_SQL}),
        o AS (SELECT DISTINCT f.alias_id FROM core_fixture_officials f JOIN m ON m.fixture_id = f.fixture_id
               WHERE f.role = 'referee' AND m.kickoff_at >= TIMESTAMPTZ '{since}'),
        p AS (SELECT DISTINCT coalesce(a.entity_type || ':' || a.entity_id::VARCHAR, 'alias:' || o.alias_id::VARCHAR) AS person,
                     a.entity_type, a.entity_id
                FROM o LEFT JOIN core_entity_aliases a ON a.id = o.alias_id)
        SELECT count(*), count(*) FILTER (WHERE EXISTS (SELECT 1 FROM core_entity_ids e
                                                         WHERE e.entity_type = p.entity_type AND e.entity_id = p.entity_id))
          FROM p
    """)
    coach_types = [r[0] for r in con.execute("SELECT DISTINCT entity_type FROM core_entity_ids").fetchall()]
    ctype = "coach" if "coach" in coach_types else next((x for x in coach_types if "coach" in str(x)), "coach")
    co = lc.one(con, f"""
        WITH m AS ({lc.MATCHES_SQL}),
        c AS (SELECT DISTINCT l.coach_id FROM core_fixture_lineups l JOIN m ON m.fixture_id = l.fixture_id
               WHERE l.coach_id IS NOT NULL AND m.kickoff_at >= TIMESTAMPTZ '{since}')
        SELECT count(*), count(*) FILTER (WHERE EXISTS (SELECT 1 FROM core_entity_ids e
                                                         WHERE e.entity_type = '{ctype}' AND e.entity_id = c.coach_id))
          FROM c
    """)
    systems = con.sql("SELECT entity_type, system, count(*) FROM core_entity_ids GROUP BY 1, 2 ORDER BY 3 DESC").fetchall()
    i = {"referees": int(ref[0]), "referees_with_id": int(ref[1]), "referee_share": (ref[1] / ref[0]) if ref[0] else 0.0,
         "coaches": int(co[0]), "coaches_with_id": int(co[1]), "coach_share": (co[1] / co[0]) if co[0] else 0.0,
         "coach_entity_type": ctype, "systems": [list(s) for s in systems]}
    v = verdicts(e, e_cov, p, a, t, i)
    return {"verdicts": v, "E": {**e, "coverage_share": e_cov, "league_seasons": len(cov)}, "P": p, "A": a, "T": t, "I": i}


def _ratio(rows: Sequence[Sequence[Any]], num: int, den: int) -> float | None:
    d = sum(r[den] for r in rows)
    return (sum(r[num] for r in rows) / d) if d else None


def _share_by(rows: Sequence[Sequence[Any]], key: Any, good: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, sel in (("prioritarias", [r for r in rows if key(r)]), ("resto", [r for r in rows if not key(r)])):
        out[name] = {"n": len(sel), "share": (sum(1 for r in sel if good(r)) / len(sel)) if sel else None}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    import json

    from fbi.research import protocol
    from scripts import lab_pm_common as lc

    p = protocol.require(KEY)
    ap = argparse.ArgumentParser(prog="lab_fichas", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--rules", type=Path, default=Path(__file__).resolve().parents[1] / "config" / "rules")
    args = ap.parse_args(argv)
    con = lc.open_export(args.folder, need=("core.fixture_team_stats", "core.fixture_events", "core.fixture_lineups",
                                            "core.fixture_officials", "core.entity_aliases", "core.entity_ids"))
    res = run(con, rules_dir=args.rules, seed=p.seed)
    lc.write_json(args.out, {"stamp": lc.stamp(KEY, args.folder).as_json(), **res})
    print(json.dumps(res["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
