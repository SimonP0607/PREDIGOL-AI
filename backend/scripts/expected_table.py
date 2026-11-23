"""PM-09-06: the expected table with the provider's xG (``fbi.stats.expected_table``) - IN SHADOW, the owner's read-only command.

    python -m scripts.expected_table show --league 39 --season 2025 [--at 2026-11-21T12:00:00Z]   # one table (rows only if visible)
    python -m scripts.expected_table eligible                                                    # where it would appear (xG B or more)
    python -m scripts.expected_table check --league 39 --season 2025                              # recomputed independently

Inside the worker's container (``docker exec predigol-worker python -m scripts.expected_table ...``). Reads only, 0 requests. Nothing a
reader sees reads the table: it waits for the owner's publication signature (DM-14). ``check`` recomputes every team's expected points
with an independent query and SciPy's Skellam distribution (the difference of two Poisson variables), and exits 1 on any difference.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any

INDEPENDENT_SQL = """
SELECT f.home_team_id, f.away_team_id, r.goals_home, r.goals_away,
       (SELECT t.expected_goals FROM core.fixture_team_stats t
         WHERE t.fixture_id = f.id AND t.team_side = 'home' AND t.source = 'api-football' AND t.fetched_at <= %(at)s
         ORDER BY t.fetched_at DESC LIMIT 1) AS xh,
       (SELECT t.expected_goals FROM core.fixture_team_stats t
         WHERE t.fixture_id = f.id AND t.team_side = 'away' AND t.source = 'api-football' AND t.fetched_at <= %(at)s
         ORDER BY t.fetched_at DESC LIMIT 1) AS xa
  FROM core.fixture_results r JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE f.competition_season_id = %(cs)s AND f.status_group = 'finished' AND r.settled_at <= %(at)s
"""
"""The same matches by correlated subqueries (a different way to take the newest xG of each side), for the check."""


def independent(rows: Sequence[Sequence[Any]]) -> dict[int, tuple[int, float, int]]:
    """Every team's ``(matches, expected points, points)`` with Skellam: P(win) = P(D > 0), P(draw) = P(D = 0), D = home - away."""
    from scipy.stats import skellam

    acc: dict[int, list[float]] = defaultdict(lambda: [0, 0.0, 0])
    for home, away, gh, ga, xh, xa in rows:
        if xh is None or xa is None:
            continue
        mu1, mu2 = float(xh), float(xa)
        if mu1 == 0 and mu2 == 0:
            p_home, p_draw = 0.0, 1.0
        elif mu2 == 0:
            p_home, p_draw = 1 - float(skellam.cdf(0, mu1, 1e-12)), float(skellam.pmf(0, mu1, 1e-12))
        elif mu1 == 0:
            p_home, p_draw = 1 - float(skellam.cdf(0, 1e-12, mu2)), float(skellam.pmf(0, 1e-12, mu2))
        else:
            p_home, p_draw = float(skellam.sf(0, mu1, mu2)), float(skellam.pmf(0, mu1, mu2))
        p_away = 1 - p_home - p_draw
        for team, mine, gf, gc in ((home, p_home, gh, ga), (away, p_away, ga, gh)):
            row = acc[int(team)]
            row[0] += 1
            row[1] += 3 * mine + p_draw
            row[2] += 3 if gf > gc else 1 if gf == gc else 0
    return {t: (int(r[0]), r[1], int(r[2])) for t, r in acc.items()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("show", "check"):
        p = sub.add_parser(name)
        p.add_argument("--league", type=int, required=True, help="the provider's league id")
        p.add_argument("--season", type=int, required=True)
        p.add_argument("--at", type=datetime.fromisoformat)
    sub.add_parser("eligible")
    args = parser.parse_args(argv)

    import psycopg

    from fbi.core.clock import now
    from fbi.core.config import settings
    from fbi.stats import expected_table as xt

    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name="expected_table") as conn:
        conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET statement_timeout = '90s'")
        if args.cmd == "eligible":
            rows = xt.eligible(conn)
            for r in rows:
                print(r)
            by: dict[str, int] = defaultdict(int)
            for r in rows:
                by[r["visibility"]] += 1
            print({"competiciones": len(rows), **by})
            return 0
        at = args.at or now()
        found = conn.execute("SELECT cs.id FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id "
                             "WHERE c.provider_league_id = %s AND cs.season = %s", (args.league, args.season)).fetchone()
        if found is None:
            print({"error": "temporada_desconocida"})
            return 1
        result = xt.expected_table(conn, int(found[0]), at=at)
        assert result is not None
        if args.cmd == "show":
            print(json.dumps(result.as_json(), ensure_ascii=False, indent=1))
            return 0
        other = independent(conn.execute(INDEPENDENT_SQL, {"cs": int(found[0]), "at": at}).fetchall())
        differences = 0
        for line in result.lines:
            n, xpts, pts = other.get(line.team_id, (0, 0.0, 0))
            same = line.matches == n and line.points == pts and abs(line.xpts - xpts) < 1e-6
            differences += not same
            print({"team_id": line.team_id, "name": line.name, "modulo": [line.matches, round(line.xpts, 6), line.points],
                   "independiente": [n, round(xpts, 6), pts], "igual": same})
        differences += len(set(other) - {x.team_id for x in result.lines})
        print({"equipos": len(result.lines), "partidos": result.matches, "sin_xg": result.without_xg,
               "visibilidad": result.visibility, "nivel_xg": result.xg_level, "diferencias": differences})
        return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
