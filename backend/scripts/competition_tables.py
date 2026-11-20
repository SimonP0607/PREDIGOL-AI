"""The tables of a competition season computed from its rules file (BE-075, plan PM, PM-09-01), in SHADOW, from the command line.

    python -m scripts.competition_tables show --league 239 --season 2026 [--cup-winner "Copa BetPlay DIMAYOR 2026=1138"]
    python -m scripts.competition_tables check --league 239 --season 2026     # against the provider's own tables

Both commands open the database READ-ONLY and write nothing: they read ``core.fixtures``, ``core.fixture_results`` and
``core.standings`` of the season (and of the earlier seasons an average counts), apply ``decisions/<season>.yaml`` and compute
with ``fbi.competitions.season_tables``. Nothing is shown to a reader: ``FBI_COMPETITION_TABLES`` stays off until the owner signs
the cotejo (DOC-008) and DM-14. ``check`` compares every computed table with the provider's table of the same clubs (the Fase I
tables, the «Tabla Anual») and exits 1 on any difference. Exit 2 when it cannot run.

IA-149 (PM-03-09): a shadow tool, so it also reads a version coded in shadow (``state: shadow``, waiting for the owner's cotejo:
Primera B 240 and Copa Colombia 241), and says so (``rules_state``); ``rules_for`` keeps answering «reglamento no codificado» to
every reader.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.competitions import rules as rl
from fbi.competitions import season_tables as st

OK, NO, CANNOT = 0, 1, 2

MATCHES_SQL = """
SELECT s.season, f.provider_fixture_id, f.round, f.status_short, th.provider_team_id, ta.provider_team_id,
       r.goals_home, r.goals_away, r.pen_home, r.pen_away
  FROM core.fixtures f
  JOIN core.competition_seasons s ON s.id = f.competition_season_id
  JOIN core.competitions c ON c.id = s.competition_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE c.provider_league_id = %(league)s AND s.season = ANY(%(seasons)s)
 ORDER BY f.kickoff_at, f.id
"""

NAMES_SQL = """
SELECT DISTINCT t.provider_team_id, t.name
  FROM core.fixtures f
  JOIN core.competition_seasons s ON s.id = f.competition_season_id
  JOIN core.competitions c ON c.id = s.competition_id
  JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
 WHERE c.provider_league_id = %(league)s AND s.season = %(season)s
"""

PROVIDER_SQL = """
WITH cs AS (SELECT s.id FROM core.competitions c JOIN core.competition_seasons s ON s.competition_id = c.id
             WHERE c.provider_league_id = %(league)s AND s.season = %(season)s),
     last AS (SELECT st.group_key, max(st.snapshot_at) AS at FROM core.standings st JOIN cs ON cs.id = st.competition_season_id
               GROUP BY 1)
SELECT st.group_key, st.snapshot_at, st.rank, t.provider_team_id, st.points, st.played, st.goals_for, st.goals_against
  FROM core.standings st JOIN cs ON cs.id = st.competition_season_id
  JOIN last l ON l.group_key = st.group_key AND l.at = st.snapshot_at
  JOIN core.teams t ON t.id = st.team_id
 ORDER BY 1, 3
"""


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="competition_tables", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("show", "check"))
    ap.add_argument("--league", type=int, required=True, help="the provider's league id")
    ap.add_argument("--season", type=int, required=True, help="the provider's season key")
    ap.add_argument("--cup-winner", action="append", default=[], metavar="NAME=TEAM",
                    help="show: the winner of another competition a place names (provider team id)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def _connect(args: argparse.Namespace) -> psycopg.Connection[Any]:
    from fbi.core.config import settings as platform

    conn = psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC -c statement_timeout=60000")
    conn.read_only = True
    return conn


def seasons_needed(rules: rl.CompetitionRules, season: int) -> list[int]:
    past = {p.season for t in rules.tables for p in t.past}
    return sorted({season, *past})


def read(conn: psycopg.Connection[Any], league: int, seasons: Sequence[int]) -> list[st.Match]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(MATCHES_SQL, {"league": league, "seasons": list(seasons)})
        return [st.Match(int(s), int(f), None if rd is None else str(rd), str(stt), int(h), int(a),
                         None if gh is None else int(gh), None if ga is None else int(ga),
                         None if ph is None else int(ph), None if pa is None else int(pa))
                for s, f, rd, stt, h, a, gh, ga, ph, pa in cur.fetchall()]


def names(conn: psycopg.Connection[Any], league: int, season: int) -> dict[int, str]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(NAMES_SQL, {"league": league, "season": season})
        return {int(t): str(n) for t, n in cur.fetchall()}


def provider_tables(conn: psycopg.Connection[Any], league: int, season: int) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(PROVIDER_SQL, {"league": league, "season": season})
        for g, at, rank, team, pts, pl, gf, ga in cur.fetchall():
            out.setdefault(str(g), []).append({"snapshot_at": at.isoformat(), "rank": int(rank), "team": int(team),
                                               "points": int(pts), "played": int(pl), "goals_for": int(gf),
                                               "goals_against": int(ga)})
    return out


def compare(reading: st.Reading, provider: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Every computed table (not the average) against the provider's table of the same clubs and the same matches played (nine
    rows in ten at least: one missing match still pairs) that agrees best with it - an Apertura and a Clausura have the same clubs
    and the same number of matches, so the closest one is the one compared: the rows that differ in points, played or goals, and
    whether the order is the provider's. A computed table with no such provider table is not listed."""
    keys = ("played", "points", "goals_for", "goals_against")
    out: list[dict[str, Any]] = []
    for t in (*reading.phases, *(x for x in reading.tables if x.kind != "average")):
        mine = {int(r["team"]): r for r in t.rows}
        best: dict[str, Any] | None = None
        for label, rows in sorted(provider.items()):
            if {r["team"] for r in rows} != set(mine):
                continue
            if sum(1 for r in rows if r["played"] == mine[r["team"]]["played"]) < 0.9 * len(rows):
                continue  # another scope of the same clubs (a tournament's table against a phase's)
            diffs = [{"team": r["team"], "provider": [r[k] for k in keys], "computed": [mine[r["team"]][k] for k in keys]}
                     for r in rows if [r[k] for k in keys] != [mine[r["team"]][k] for k in keys]]
            same_order = [r["team"] for r in sorted(rows, key=lambda r: r["rank"])] == t.order()
            found = {"table": t.key, "provider_table": label, "snapshot_at": rows[0]["snapshot_at"],
                     "rows_compared": len(rows), "differences": diffs, "same_order": same_order}
            if best is None or len(diffs) < len(best["differences"]):
                best = found
        if best is not None:
            out.append(best)
    return out


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    answer = rl.rules_for(args.league, args.season, include_shadow=True)
    if not isinstance(answer, rl.Coded):
        return answer.as_json(), NO
    cups: dict[str, int] = {}
    for item in args.cup_winner:
        name, _, team = item.rpartition("=")
        if not name or not team.isdigit():
            return {"error": f"--cup-winner {item!r}: NAME=TEAM (provider team id)"}, CANNOT
        cups[name] = int(team)
    decisions = st.load_decisions(args.league)
    with _connect(args) as conn:
        matches = read(conn, args.league, seasons_needed(answer.rules, args.season))
        team_names = names(conn, args.league, args.season)
        provider = provider_tables(conn, args.league, args.season) if args.command == "check" else {}
    if not any(m.season == args.season for m in matches):
        return {"error": "season not in the database"}, CANNOT
    reading = st.compute(answer.rules, args.season, matches, decisions=decisions, cup_winners=cups)
    head = {"shadow": True, "switch": {"name": st.SWITCH, "on": st.switch_on()},
            "rules_file": answer.file.path, "rules_sha256": answer.file.sha256, "rules_state": answer.rules.state}
    if args.command == "check":
        comparisons = compare(reading, provider)
        ok = bool(comparisons) and all(not c["differences"] and c["same_order"] for c in comparisons)
        return {**head, "comparisons": comparisons, "decisions": reading.as_json()["decisions"],
                "problems": list(reading.decisions.problems)}, OK if ok else NO
    return {**head, "names": {str(k): v for k, v in sorted(team_names.items())}, **reading.as_json()}, OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result, code = run(args)
    except psycopg.Error as exc:
        result, code = {"error": f"database: {type(exc).__name__}"}, CANNOT
    except rl.RulesError as exc:
        result, code = {"error": str(exc)}, NO
    print(json.dumps(result, ensure_ascii=False, indent=None if args.as_json else 2, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
