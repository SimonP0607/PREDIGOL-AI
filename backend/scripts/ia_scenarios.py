"""The scenarios engine (``scenarios-v2``, IA-082, plan piece AD-B02) from the command line.

    python -m scripts.ia_scenarios read --league 239 --season 2026 [--at 2026-11-14T14:46:00Z] [--sims 2000] [--no-sim]
    python -m scripts.ia_scenarios compare --since 2026-11-14 --until 2026-11-21 [--league 71 --league 239] [--no-sim]
    python -m scripts.ia_scenarios replay --league 39 --season 2025
    python -m scripts.ia_scenarios run                      # the worker's shadow step, by hand (only with FBI_SCENARIOS=shadow)

``read`` is a reading of a competition season at a moment (now by default); ``compare`` takes the packets of the matches that kicked
off in the window (the newest one before each kick-off, the one the readers' chronicle used) and says, side by side, which of
stakes-v5's statements the engine contradicts; ``replay`` replays a closed season day by day and holds every claim to the final table.
These three open the database READ-ONLY. ``run`` writes, only to ``intel.scenario_readings`` (migration 0147, append-only), and only
when ``FBI_SCENARIOS=shadow``. Nothing here calls a provider, a language model or a web page. Exit 0; 1 when a check fails (a
contradiction inside a reading, a false claim in a replay); 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

from fbi.competitions import rules as rl
from fbi.competitions import scenario_compare as cmp
from fbi.competitions import scenario_replay as rp
from fbi.competitions import scenario_store as store
from fbi.competitions import scenarios as sc

OK, NO, CANNOT = 0, 1, 2

PACKETS_SQL: Final = """
SELECT DISTINCT ON (p.fixture_id) p.fixture_id, p.id, p.as_of, p.content->'stakes', c.provider_league_id, s.season,
       f.home_team_id, f.away_team_id
  FROM ai.match_packets p
  JOIN core.fixtures f ON f.id = p.fixture_id
  JOIN core.competition_seasons s ON s.id = f.competition_season_id
  JOIN core.competitions c ON c.id = s.competition_id
 WHERE c.provider_league_id = ANY(%(leagues)s) AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
   AND p.as_of <= f.kickoff_at AND p.content ? 'stakes'
 ORDER BY p.fixture_id, p.as_of DESC, p.id DESC
"""

SEASON_MATCHES_SQL: Final = """
SELECT f.id, f.round, f.home_team_id, f.away_team_id, f.kickoff_at, r.goals_home, r.goals_away
  FROM core.fixtures f JOIN core.competition_seasons s ON s.id = f.competition_season_id
  JOIN core.competitions c ON c.id = s.competition_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE c.provider_league_id = %(league)s AND s.season = %(season)s AND f.kickoff_at IS NOT NULL
 ORDER BY f.kickoff_at, f.id
"""

FINAL_SQL: Final = """
WITH cs AS (SELECT s.id FROM core.competitions c JOIN core.competition_seasons s ON s.competition_id = c.id
             WHERE c.provider_league_id = %(league)s AND s.season = %(season)s),
     last AS (SELECT group_key, max(snapshot_at) AS at FROM core.standings WHERE competition_season_id IN (SELECT id FROM cs) GROUP BY 1)
SELECT st.group_key, st.rank, st.team_id FROM core.standings st JOIN last l ON l.group_key = st.group_key AND l.at = st.snapshot_at
 WHERE st.competition_season_id IN (SELECT id FROM cs)
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_scenarios", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("read", "compare", "replay", "run"))
    ap.add_argument("--league", type=int, action="append", default=[], help="the provider's league id (compare: repeatable)")
    ap.add_argument("--season", type=int, help="read/replay: the provider's season key")
    ap.add_argument("--at", type=datetime.fromisoformat, help="read: the moment (default: now)")
    ap.add_argument("--since", type=date.fromisoformat, help="compare: first kick-off day (UTC)")
    ap.add_argument("--until", type=date.fromisoformat, help="compare: last kick-off day (UTC), included")
    ap.add_argument("--sims", type=int, default=sc.DEFAULT_SIMS)
    ap.add_argument("--no-sim", action="store_true", help="read/compare: certification only (no model, no simulation)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def _connect(args: argparse.Namespace, *, write: bool) -> psycopg.Connection[Any]:
    from fbi.core.config import settings as platform

    conn = psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC -c statement_timeout=90000")
    if not write:
        conn.read_only = True
    return conn


def _summary(reading: dict[str, Any]) -> dict[str, Any]:
    tables = []
    for t in reading.get("tables", []):
        teams = []
        for row in sorted(t["teams"], key=lambda r: (r["puesto"] or 99, r["team"])):
            teams.append({"team": row["team"], "puesto": row["puesto"], "puntos": row["puntos"], "quedan": row["partidos_restantes"],
                          "objetivos": [f"{o['objetivo']}<={o['terminar_entre_los']}:{o['estado']}"
                                        + ("" if o["probabilidad"] is None else f":{o['probabilidad']:.3f}")
                                        + (":condicional" if o["condicional"] else "") for o in row["objetivos"]],
                          "sin_objetivo": (reading.get("teams") or {}).get(str(row["team"]), {}).get("demostrado")})
        tables.append({"key": t["key"], "played": t["played"], "pending": t["pending"], "flags": t["flags"],
                       "simulation": t["simulation"], "teams": teams})
    return {"version": reading["version"], "status": reading["status"], "at": reading["at"], "league_id": reading["league_id"],
            "season": reading["season"], "model": reading.get("model"), "skipped": reading.get("skipped"),
            "contradicciones": reading.get("contradicciones", 0), "tables": tables}


def cmd_read(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if len(args.league) != 1 or args.season is None:
        return {"error": "read needs one --league and --season"}, CANNOT
    at = (args.at or datetime.now(UTC)).astimezone(UTC)
    with _connect(args, write=False) as conn:
        reading = store.read_season(conn, args.league[0], args.season, at=at, sims=args.sims, simulate=not args.no_sim)
    if reading is None:
        return {"error": "season not in the database"}, CANNOT
    return (reading if args.as_json else _summary(reading)), NO if reading.get("contradicciones") else OK


def cmd_compare(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.since is None or args.until is None:
        return {"error": "compare needs --since and --until"}, CANNOT
    lib = rl.library()
    leagues = args.league or sorted({f.rules.league_id for f in lib.files if f.rules.state == "coded"})
    since = datetime.combine(args.since, time(0), tzinfo=UTC)
    until = datetime.combine(args.until + timedelta(days=1), time(0), tzinfo=UTC)
    per: dict[int, Counter[str]] = defaultdict(Counter)
    examples: list[dict[str, Any]] = []
    with _connect(args, write=False) as conn:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(PACKETS_SQL, {"leagues": leagues, "since": since, "until": until})
            packets = cur.fetchall()
        for fid, pid, as_of, stakes, league, season, home, away in packets:
            reading = store.read_season(conn, int(league), int(season), at=as_of, sims=args.sims, simulate=not args.no_sim,
                                        focus=[int(fid)])
            if reading is None:
                continue
            c = per[int(league)]
            c["packets"] += 1
            for side, team in (("home", int(home)), ("away", int(away))):
                block = (stakes or {}).get(side)
                result = cmp.compare_side(block, reading, team)
                c["sides"] += 1
                c[f"rule:{(block or {}).get('rule')}"] += 1
                c["settled"] += bool(result.get("settled"))
                c["contradicted"] += bool(result.get("contradice"))
                for k in result["contradicciones"]:
                    c[k["tipo"]] += 1
                if result.get("contradice") and len(examples) < 25:
                    examples.append({"fixture": int(fid), "packet": int(pid), "as_of": as_of.isoformat(), "team": team,
                                     "rule": (block or {}).get("rule"), "pressure": (block or {}).get("pressure"),
                                     "contradicciones": result["contradicciones"]})
    total: Counter[str] = Counter()
    for c in per.values():
        total.update(c)
    return {"version": cmp.VERSION, "engine": sc.VERSION, "window": [args.since.isoformat(), args.until.isoformat()],
            "by_league": {str(k): dict(v) for k, v in sorted(per.items())}, "total": dict(total), "examples": examples}, OK


def cmd_replay(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if len(args.league) != 1 or args.season is None:
        return {"error": "replay needs one --league and --season"}, CANNOT
    league = args.league[0]
    answer = rl.rules_for(league, args.season)
    with _connect(args, write=False) as conn, conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SEASON_MATCHES_SQL, {"league": league, "season": args.season})
        matches = [rp.Match(sc.Fixture(int(i), None if rd is None else str(rd), int(h), int(a),
                                       None if gh is None or ga is None else int(gh), None if gh is None or ga is None else int(ga)),
                            ko) for i, rd, h, a, ko, gh, ga in cur.fetchall()]
        cur.execute(FINAL_SQL, {"league": league, "season": args.season})
        final: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for g, rank, team in cur.fetchall():
            final[str(g)].append((int(rank), int(team)))
    if not matches:
        return {"error": "season not in the database"}, CANNOT
    report = rp.replay(answer, matches, final=final)
    return report, NO if report.get("false_claims") else OK


def cmd_run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if store.mode() != "shadow":
        return {"skipped": f"{store.SWITCH} is not 'shadow': nothing is written"}, OK
    with _connect(args, write=True) as conn:
        report = store.run_shadow(conn, at=datetime.now(UTC), code_version=os.environ.get("FBI_CODE_VERSION"), sims=args.sims)
        conn.commit()
    return report, NO if report.get("errors") else OK


COMMANDS = {"read": cmd_read, "compare": cmd_compare, "replay": cmd_replay, "run": cmd_run}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result, code = COMMANDS[args.command](args)
    except psycopg.Error as exc:
        result, code = {"error": f"database: {type(exc).__name__}"}, CANNOT
    print(json.dumps(result, ensure_ascii=False, indent=None if args.as_json else 2, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
