"""PM-08-05: the difficulty of a team's coming matches (``fbi.competitions.schedule_difficulty``) - IN SHADOW, the owner's read-only command.

    python -m scripts.schedule_difficulty show --team 1137 [--at 2026-11-20T12:00:00Z]     # core.teams.id
    python -m scripts.schedule_difficulty league --league 239 --season 2026                # every team of a season, and the league's mean
    python -m scripts.schedule_difficulty check --league 239 --season 2026 [--teams 10]    # the index recomputed by an independent query

Inside the worker's container (``docker exec predigol-worker python -m scripts.schedule_difficulty ...``). Reads only, 0 requests.
Nothing a reader sees reads the index: it waits for the owner's publication signature (DM-14). Exit 1 when ``check`` finds a difference.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

INDEPENDENT_SQL = """
WITH run AS (
  SELECT elo_version, run_id FROM features.elo_ratings WHERE computed_at <= %(at)s
   GROUP BY 1, 2 ORDER BY max(computed_at) DESC LIMIT 1
), coming AS (
  SELECT f.id, f.kickoff_at, f.is_neutral, (f.home_team_id = %(team)s) AS at_home,
         CASE WHEN f.home_team_id = %(team)s THEN f.away_team_id ELSE f.home_team_id END AS rival
    FROM core.fixtures f
   WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s) AND f.kickoff_at > %(at)s
     AND f.kickoff_at < %(at)s + interval '60 days' AND f.created_at <= %(at)s AND f.status_group IN ('scheduled', 'postponed')
   ORDER BY f.kickoff_at, f.id LIMIT 5
), rated AS (
  SELECT c.*, (SELECT e.rating_after FROM features.elo_ratings e, run
                WHERE e.elo_version = run.elo_version AND e.run_id = run.run_id AND e.team_id = c.rival AND e.kickoff_at <= %(at)s
                ORDER BY e.kickoff_at DESC, e.fixture_id DESC LIMIT 1) AS elo
    FROM coming c
)
SELECT count(elo), avg(elo + CASE WHEN is_neutral THEN 0 WHEN at_home THEN -65 ELSE 65 END) FROM rated
"""
"""The same index by PostgreSQL alone (a different way to find the run and the last rating), for the check."""


def _season_teams(conn: Any, league: int, season: int) -> tuple[int | None, list[int]]:
    row = conn.execute("SELECT cs.id FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id "
                       "WHERE c.provider_league_id = %s AND cs.season = %s", (league, season)).fetchone()
    if row is None:
        return None, []
    teams = conn.execute("SELECT DISTINCT t FROM core.fixtures f, LATERAL (VALUES (f.home_team_id), (f.away_team_id)) v(t) "
                         "WHERE f.competition_season_id = %s ORDER BY 1", (row[0],)).fetchall()
    return int(row[0]), [int(t[0]) for t in teams]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("--team", type=int, required=True)
    s.add_argument("--at", type=datetime.fromisoformat)
    for name in ("league", "check"):
        p = sub.add_parser(name)
        p.add_argument("--league", type=int, required=True, help="the provider's league id")
        p.add_argument("--season", type=int, required=True)
        p.add_argument("--at", type=datetime.fromisoformat)
        p.add_argument("--teams", type=int, default=10)
    args = parser.parse_args(argv)

    import psycopg

    from fbi.competitions import schedule_difficulty as sd
    from fbi.core.clock import now
    from fbi.core.config import settings

    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name="schedule_difficulty") as conn:
        conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET statement_timeout = '90s'")
        at = args.at or now()
        if args.cmd == "show":
            print(json.dumps(sd.team_difficulty(conn, args.team, at=at).as_json(), ensure_ascii=False, indent=1))
            return 0
        cs, teams = _season_teams(conn, args.league, args.season)
        if cs is None:
            print({"error": "temporada_desconocida"})
            return 1
        if args.cmd == "league":
            n, mean = sd.league_mean(conn, cs, at=at)
            print({"league": args.league, "season": args.season, "teams": len(teams), "rated": n,
                   "league_mean_elo": None if mean is None else round(mean, 1)})
            for team in teams:
                d = sd.team_difficulty(conn, team, at=at).difficulty.as_json()
                print({"team_id": team, **d, "vs_league": None if mean is None or d["index"] is None else round(d["index"] - mean, 1)})
            return 0
        differences = 0
        for team in teams[: args.teams]:
            mine = sd.team_difficulty(conn, team, at=at).difficulty
            row = conn.execute(INDEPENDENT_SQL, {"team": team, "at": at}).fetchone()
            n, index = (int(row[0]), None if row[1] is None else float(row[1])) if row else (0, None)
            same = mine.n == n and ((mine.index is None and index is None) or (
                mine.index is not None and index is not None and abs(mine.index - index) < 1e-6))
            differences += not same
            print({"team_id": team, "modulo": [mine.n, mine.index], "sql": [n, index], "igual": same})
        print({"equipos": min(len(teams), args.teams), "diferencias": differences})
        return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
