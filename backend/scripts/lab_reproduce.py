"""PM-12-02 (OPS-013): reproduce a LAB backtest session on the laptop, from an export of ``scripts.lab_export``, with DuckDB.

    python scripts/lab_export.py verify <folder>          # first: the files are the ones the manifest describes
    python scripts/lab_reproduce.py <folder>              # then: recompute every run's 1X2 log loss and Brier score

No database and no PrediGol package are needed: DuckDB reads the Parquet files of the export. For each run of the session
(``analytics.backtest_runs``) it takes the run's 1X2 probabilities (``analytics.backtest_samples``: the three selections of each
match) and the regulation-time result of the match (``core.fixture_results``, ``reg_goals_*``, else ``ft_goals_*``: what the
walk-forward settles on), and computes, as ``fbi.models.metrics`` does:

* log loss: the mean over matches of ``-ln(max(p of what happened, 1e-15))``;
* Brier: the mean over matches of ``sum_k (p_k - 1[k happened])^2``.

It compares them with the figures the server stored for the run. The probabilities were stored rounded to 6 decimals, so the
recomputed figures may differ from the stored ones by a few millionths: ``TOLERANCE``. It also checks that the outcome the server
recorded for each sample (``outcome_correct``) is the one the result gives. Exit 0 when every run reproduces.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

EPS = 1e-15
TOLERANCE = 2e-5

_SQL = """
WITH res AS (
  SELECT fixture_id,
         CASE WHEN coalesce(reg_goals_home, ft_goals_home) > coalesce(reg_goals_away, ft_goals_away) THEN 'Home'
              WHEN coalesce(reg_goals_home, ft_goals_home) = coalesce(reg_goals_away, ft_goals_away) THEN 'Draw'
              ELSE 'Away' END AS happened
    FROM read_parquet(?) WHERE coalesce(reg_goals_home, ft_goals_home) IS NOT NULL
), s AS (
  SELECT backtest_run_id AS run, fixture_id, selection, p_calibrated AS p, outcome_correct
    FROM read_parquet(?) WHERE market_key = '1X2'
), m AS (
  SELECT s.run, s.fixture_id,
         max(CASE WHEN s.selection = r.happened THEN s.p END) AS p_happened,
         sum(power(s.p - CASE WHEN s.selection = r.happened THEN 1 ELSE 0 END, 2)) AS brier,
         count(*) AS selections,
         sum(CASE WHEN (s.selection = r.happened) <> s.outcome_correct THEN 1 ELSE 0 END) AS outcome_disagrees
    FROM s JOIN res r USING (fixture_id) GROUP BY 1, 2
)
SELECT run, count(*) AS matches, avg(-ln(greatest(p_happened, ?))) AS logloss, avg(brier) AS brier,
       sum(CASE WHEN selections <> 3 THEN 1 ELSE 0 END) AS incomplete, sum(outcome_disagrees) AS outcome_disagrees
  FROM m GROUP BY 1 ORDER BY 1
"""


def reproduce(folder: Path) -> list[dict[str, Any]]:
    import duckdb

    con = duckdb.connect()
    runs = {int(r[0]): {"name": r[1], "n": r[2], "logloss": r[3], "brier": r[4]} for r in con.execute(
        "SELECT id, name, n_samples, logloss, brier_score FROM read_parquet(?)",
        [str(folder / "analytics.backtest_runs.parquet")]).fetchall()}
    rows = con.execute(_SQL, [str(folder / "core.fixture_results.parquet"),
                              str(folder / "analytics.backtest_samples.parquet"), EPS]).fetchall()
    out = []
    for run, matches, logloss, brier, incomplete, disagrees in rows:
        stored = runs.get(int(run), {})
        ll_diff = None if stored.get("logloss") is None else abs(float(logloss) - float(stored["logloss"]))
        br_diff = None if stored.get("brier") is None else abs(float(brier) - float(stored["brier"]))
        ok = (ll_diff is not None and ll_diff <= TOLERANCE and br_diff is not None and br_diff <= TOLERANCE
              and int(matches) == int(stored.get("n") or -1) and not incomplete and not disagrees)
        out.append({"run": int(run), "name": stored.get("name"), "matches": int(matches), "stored_n": stored.get("n"),
                    "logloss": round(float(logloss), 6), "stored_logloss": stored.get("logloss"),
                    "brier": round(float(brier), 6), "stored_brier": stored.get("brier"),
                    "incomplete": int(incomplete), "outcome_disagrees": int(disagrees), "reproduced": ok})
    return out


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(__doc__)
        return 2
    rows = reproduce(Path(args[0]))
    for r in rows:
        print(f"run {r['run']:>3} {str(r['name'])[:44]:44} n {r['matches']:>5}/{r['stored_n']}  "
              f"log loss {r['logloss']:.6f} vs {r['stored_logloss']}  Brier {r['brier']:.6f} vs {r['stored_brier']}  "
              f"{'REPRODUCED' if r['reproduced'] else 'DIFFERS'}")
    print(json.dumps({"runs": len(rows), "reproduced": sum(r["reproduced"] for r in rows)}, default=str))
    return 0 if rows and all(r["reproduced"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
