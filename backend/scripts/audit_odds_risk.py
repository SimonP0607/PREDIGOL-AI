"""Is the daily rule's taste for long odds paid for? The evidence behind the risk stage (risk-v1, daily-set-v4).

    python -m scripts.audit_odds_risk            # read-only; prints the tables of docs/owner/P5_SELECCION_RIESGO_CONTEXTO.md

On the settled picks - the last pre-kick-off evaluation of each selection by each model family (a re-evaluation is
never counted twice) - it reports, by odds taken and by the model-market gap: hit rate against the model's and the
market's probability, return with a 95 % interval (bootstrap over MATCHES, since the picks of one match move
together) and closing-line value. Then a ROLLING WALK-FORWARD by Bogotá day: each day's thresholds (an odds cap and a
gap cap) are chosen on the days before it only - at least 1,000 settled selections - and that day is judged with them;
nothing of a day is seen when choosing for it. It does the same for the daily set's own choice (the five best
pessimistic growths a day, one per match). It changes nothing.
"""

from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from collections.abc import Sequence
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from fbi.core.config import settings

BOG = ZoneInfo("America/Bogota")
CAPS: tuple[float | None, ...] = (None, 2.2, 2.5, 3.0, 3.5, 4.0, 5.0)
GAPS: tuple[float | None, ...] = (None, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20)
SETTLED_SQL = """
WITH last AS (
  SELECT DISTINCT ON (p.fixture_id, p.market_key, p.selection, p.line, m.name)
         p.id, p.fixture_id, p.market_key, p.selection, p.line, m.name AS model, p.market_odds::float AS odds,
         p.p_calibrated::float AS p, p.p_calibrated_lo::float AS p_low, p.p_market_fair::float AS p_mkt,
         p.p_push::float AS p_push, f.kickoff_at
    FROM picks.picks p JOIN core.fixtures f ON f.id = p.fixture_id
    JOIN models.model_versions v ON v.id = p.model_version_id JOIN models.model_registry m ON m.id = v.model_id
   WHERE p.created_at < f.kickoff_at AND p.odds_captured_at < f.kickoff_at AND p.market_odds IS NOT NULL
   ORDER BY p.fixture_id, p.market_key, p.selection, p.line, m.name, p.created_at DESC, p.id DESC)
SELECT l.*, r.result_status, r.profit_units::float AS profit, lv.lv_devigged::float AS lv
  FROM last l JOIN picks.pick_results r ON r.pick_id = l.id
  LEFT JOIN picks.pick_line_value lv ON lv.pick_id = l.id
 WHERE r.result_status NOT IN ('pending', 'void')
"""


def roi_ci(sample: Sequence[dict[str, Any]], rng: random.Random, b: int = 200) -> tuple[float, float, float]:
    by_fix: dict[int, list[float]] = defaultdict(list)
    for r in sample:
        by_fix[r["fixture_id"]].append(r["profit"])
    groups = list(by_fix.values())
    n = sum(len(g) for g in groups)
    point = sum(sum(g) for g in groups) / n
    stats = []
    for _ in range(b):
        pick = [groups[rng.randrange(len(groups))] for _ in range(len(groups))]
        stats.append(sum(sum(g) for g in pick) / sum(len(g) for g in pick))
    stats.sort()
    return point, stats[int(0.025 * b)], stats[int(0.975 * b)]


def line(label: str, sample: Sequence[dict[str, Any]], rng: random.Random) -> None:
    if not sample:
        print(f"  {label:34} n=0")
        return
    point, lo, hi = roi_ci(sample, rng)
    hit = sum(1 for r in sample if r["result_status"] in ("win", "half_win")) / len(sample)
    lvs = [r["lv"] for r in sample if r["lv"] is not None]
    mean = lambda k: sum(r[k] for r in sample) / len(sample)  # noqa: E731
    print(f"  {label:34} n={len(sample):5d} hit={hit:5.1%} p_model={mean('p'):5.1%} p_mkt={mean('p_mkt'):5.1%} "
          f"implied={sum(1 / r['odds'] for r in sample) / len(sample):5.1%} ROI={point:+6.1%} [{lo:+6.1%},{hi:+6.1%}] "
          f"CLV={(sum(lvs) / len(lvs) if lvs else float('nan')):+5.1%}")


def keep(r: dict[str, Any], cap: float | None, gap: float | None) -> bool:
    return (cap is None or r["odds"] <= cap) and (gap is None or r["p"] - r["p_mkt"] <= gap)


def elg(r: dict[str, Any], f: float = 0.01) -> float:
    p = (r["p_low"] or 0) * (1 - (r["p_push"] or 0))
    q = max(0.0, 1 - p - (r["p_push"] or 0))
    return p * math.log(1 + f * (r["odds"] - 1)) + q * math.log(1 - f)


def daily(sample: Sequence[dict[str, Any]], cap: float | None = None, gap: float | None = None) -> list[dict[str, Any]]:
    """The daily set's own choice: per Bogotá day, the five best pessimistic growths, one per match."""
    by_day: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for r in sample:
        if r["p_low"] is not None and keep(r, cap, gap) and elg(r) > 0:
            by_day[r["kickoff_at"].astimezone(BOG).date()].append(r)
    chosen = []
    for opts in by_day.values():
        seen: set[int] = set()
        for r in sorted(opts, key=lambda x: -elg(x)):
            if r["fixture_id"] not in seen:
                chosen.append(r)
                seen.add(r["fixture_id"])
            if len(seen) == 5:
                break
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(prog="audit_odds_risk", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--min-train", type=int, default=1000, help="settled selections before a day to judge it")
    args = parser.parse_args()
    rng = random.Random(7)
    with psycopg.connect(settings.database.psycopg_url.replace("postgresql+psycopg://", "postgresql://"),
                         row_factory=dict_row) as conn:
        conn.read_only = True
        rows = [r for r in conn.execute(SETTLED_SQL).fetchall() if r["profit"] is not None and r["odds"] and r["p_mkt"]]
    if not rows:
        print("no settled selections")
        return 0
    rows.sort(key=lambda r: r["kickoff_at"])
    print(f"settled selections: {len(rows)} ({rows[0]['kickoff_at']:%Y-%m-%d} .. {rows[-1]['kickoff_at']:%Y-%m-%d})")
    print("\n== by odds taken")
    for lo, hi in ((1.0, 1.5), (1.5, 1.8), (1.8, 2.2), (2.2, 3.0), (3.0, 5.0), (5.0, 99.0)):
        line(f"odds {lo:.2f}-{hi:.2f}", [r for r in rows if lo <= r["odds"] < hi], rng)
    print("\n== by model-market gap (p_model - p_market)")
    for lo, hi in ((-1.0, 0.05), (0.05, 0.08), (0.08, 0.12), (0.12, 0.16), (0.16, 0.25), (0.25, 1.0)):
        line(f"gap {lo:+.2f}..{hi:+.2f}", [r for r in rows if lo <= r["p"] - r["p_mkt"] < hi], rng)
    print("\n== rolling walk-forward by Bogotá day")
    days = sorted({r["kickoff_at"].astimezone(BOG).date() for r in rows})
    all_rule, all_none, day_rule, day_none = [], [], [], []
    for d in days:
        before = [r for r in rows if r["kickoff_at"].astimezone(BOG).date() < d]
        today = [r for r in rows if r["kickoff_at"].astimezone(BOG).date() == d]
        if len(before) < args.min_train or not today:
            continue
        grid = []
        for cap in CAPS:
            for gap in GAPS:
                s = [r for r in before if keep(r, cap, gap)]
                if len(s) >= 500:
                    grid.append((sum(r["profit"] for r in s) / len(s), cap, gap))
        grid.sort(key=lambda x: -x[0])
        _, cap, gap = grid[0]
        print(f"  {d}: odds<={cap} gap<={gap}  ({len(today)} settled that day)")
        all_rule += [r for r in today if keep(r, cap, gap)]
        all_none += today
        day_rule += daily(today, cap, gap)
        day_none += daily(today)
    line("all selections, no rule", all_none, rng)
    line("all selections, the day's rule", all_rule, rng)
    line("daily set, no rule", day_none, rng)
    line("daily set, the day's rule", day_rule, rng)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
