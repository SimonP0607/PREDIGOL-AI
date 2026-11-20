"""The quality probe of API-Football's «goals prevented» (plan PM, PM-05-05; BE-068). Read only, 0 requests.

    python -m scripts.goals_prevented_probe                  # last 60 days of finished matches
    python -m scripts.goals_prevented_probe --days 120 --json

The provider's team statistic ``goals_prevented`` (``core.fixture_team_stats``) is the goalkeeper's shots faced, valued, minus the goals
conceded. Its own pieces are not stored, so it is set against what PrediGol does keep: the opponent's xG minus the goals conceded
(``expected_goals`` of the other side, ``core.fixture_results``). The two are not the same measure (xG before the shot, the provider's
after it) but they must agree on the sign most of the time and move together; a field that does not is not published.

PASS when, over the team-matches that report both: at least ``MIN_SAMPLE``; Pearson correlation >= ``MIN_CORRELATION``; the sign agrees
in >= ``MIN_SIGN_AGREEMENT`` of the matches where the reference is not near 0; no value outside +-``MAX_ABS``. Then, and only then,
``FBI_STATS_GOALS_PREVENTED`` may be turned on (``fbi.stats.extras``).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

MIN_SAMPLE: Final = 200
MIN_CORRELATION: Final = 0.6
MIN_SIGN_AGREEMENT: Final = 0.7
NEAR_ZERO: Final = 0.25
"""A reference within this of 0 says nothing about the sign: those matches are left out of the agreement."""
MAX_ABS: Final = 5.0

PROBE_SQL: Final = """
WITH t AS (
    SELECT f.id, s.team_side, s.goals_prevented AS gp, o.expected_goals AS opp_xg,
           CASE WHEN s.team_side = 'home' THEN r.goals_away ELSE r.goals_home END AS conceded
      FROM core.fixtures f
      JOIN core.fixture_results r ON r.fixture_id = f.id
      JOIN core.fixture_team_stats s ON s.fixture_id = f.id AND s.source = 'api-football'
      JOIN core.fixture_team_stats o ON o.fixture_id = f.id AND o.source = 'api-football' AND o.team_side <> s.team_side
     WHERE f.status_group = 'finished' AND f.kickoff_at >= now() - make_interval(days => %(days)s) AND f.kickoff_at < now()
)
SELECT count(*) AS team_matches,
       count(*) FILTER (WHERE gp IS NOT NULL) AS with_gp,
       count(*) FILTER (WHERE gp IS NOT NULL AND opp_xg IS NOT NULL AND conceded IS NOT NULL) AS both,
       corr(gp, opp_xg - conceded) FILTER (WHERE opp_xg IS NOT NULL AND conceded IS NOT NULL) AS correlation,
       avg((sign(gp) = sign(opp_xg - conceded))::int) FILTER (WHERE gp IS NOT NULL AND abs(opp_xg - conceded) > %(near)s)
           AS sign_agreement,
       avg(abs(gp - (opp_xg - conceded))) FILTER (WHERE opp_xg IS NOT NULL AND conceded IS NOT NULL) AS mean_abs_gap,
       min(gp) AS min_gp, max(gp) AS max_gp, count(*) FILTER (WHERE abs(gp) > %(max_abs)s) AS out_of_range,
       count(DISTINCT id) FILTER (WHERE gp IS NOT NULL) AS matches
  FROM t
"""


def verdict(r: dict[str, Any]) -> dict[str, Any]:
    """PASS or FAIL, and every reason it fails."""
    reasons = []
    if (r["both"] or 0) < MIN_SAMPLE:
        reasons.append(f"muestra {r['both']} < {MIN_SAMPLE}")
    if r["correlation"] is None or float(r["correlation"]) < MIN_CORRELATION:
        reasons.append(f"correlación {r['correlation']} < {MIN_CORRELATION}")
    if r["sign_agreement"] is None or float(r["sign_agreement"]) < MIN_SIGN_AGREEMENT:
        reasons.append(f"signo {r['sign_agreement']} < {MIN_SIGN_AGREEMENT}")
    if (r["out_of_range"] or 0) > 0:
        reasons.append(f"{r['out_of_range']} valores fuera de ±{MAX_ABS}")
    return {"verdict": "PASS" if not reasons else "FAIL", "reasons": reasons}


def main(argv: list[str] | None = None) -> int:
    from fbi.core.config import settings

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        conn.read_only = True
        conn.execute("SET statement_timeout = '90s'")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(PROBE_SQL, {"days": args.days, "near": NEAR_ZERO, "max_abs": MAX_ABS})
            row = dict(cur.fetchone() or {})
    out = {k: (float(v) if v is not None and not isinstance(v, int) else v) for k, v in row.items()} | verdict(row)
    print(json.dumps(out, indent=None if args.json else 1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
