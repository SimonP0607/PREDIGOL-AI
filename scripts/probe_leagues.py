"""P3: probe the candidate leagues before any is tracked (fbi.catalog.league_probe).

    python -m scripts.probe_leagues --plan                     # candidates, current season and flags; no request
    python -m scripts.probe_leagues --max-requests 160         # probe every candidate, 3 requests each at most
    python -m scripts.probe_leagues --league 244 --league 43   # only these

Candidates come from config/expansion.yaml (the 50 of the capacity report). Each league's season is the one
raw.league_coverage - the /leagues answer on disk - marks current; a candidate without one is reported and skipped.
Every answer is stored in RAW under one ``league_probe`` run. The report goes to data/expansion/<stamp>-probe/
(PROBE.md and probe.json). This never tracks a league: that is a separate step, batch by batch.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import psycopg
import yaml
from psycopg.rows import dict_row

from fbi.catalog.league_probe import LeagueProbe, probe_leagues
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config" / "expansion.yaml"
OUT = REPO / "data" / "expansion"

CURRENT_SQL = """
SELECT provider_league_id AS league, season, league_name, country, league_type, start_date, end_date,
       events, lineups, statistics_fixtures, statistics_players, standings, injuries, odds,
       (SELECT c.is_tracked FROM core.competitions c WHERE c.provider_league_id = lc.provider_league_id) AS tracked
  FROM raw.league_coverage lc
 WHERE provider_league_id = ANY(%(ids)s) AND is_current
"""


def candidates(path: Path = CONFIG) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return sorted(raw["candidates"], key=lambda c: int(c["rank"]))


def markdown(rows: list[dict[str, Any]], probes: dict[int, LeagueProbe], run_id: int | None) -> str:
    lines = ["# P3 - candidate league probe", "", f"run {run_id}" if run_id else "plan only (no request)", "",
             "| # | League | Season | Ends | Fixtures | Finished | Ahead | Unresolved | Sampled | Events | Line-ups | "
             "Team stats | Player stats | Data | Goals = events | Table rows / games |",
             "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in rows:
        p = probes.get(int(r["league_id"]))
        if p is None:
            lines.append(f"| {r['rank']} | {r['name']} ({r['league_id']}) | {r.get('season') or '-'} | "
                         f"{r.get('end_date') or '-'} | " + " | ".join(["-"] * 12) + " |")
            continue
        d = p.as_dict()
        lines.append(
            f"| {r['rank']} | {r['name']} ({r['league_id']}) | {p.season} | {r.get('end_date') or '-'} | {p.fixtures} | "
            f"{p.finished} | {p.upcoming} | {p.unresolved_results} | {p.sampled} | {d['events']} | {d['lineups']} | "
            f"{d['team_stats']} | {d['player_stats']} | **{p.data_score}** | {p.consistency} | "
            f"{p.table_rows} / {p.table_games if p.table_games is not None else f'{p.table_groups} tables'} |")
    errors = [f"* {p.league}: {e}" for p in probes.values() for e in p.errors]
    examples = [f"* {p.league}: {e}" for p in probes.values() for e in p.examples]
    if errors:
        lines += ["", "## Errors", *errors]
    if examples:
        lines += ["", "## Goal events that do not add up to the score", *examples]
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> int:
    cands = candidates()
    if args.league:
        cands = [c for c in cands if int(c["league_id"]) in set(args.league)]
    with psycopg.connect(settings.database.psycopg_url) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(CURRENT_SQL, {"ids": [int(c["league_id"]) for c in cands]})
            current = {int(r["league"]): r for r in cur.fetchall()}
        rows = [{**c, **current.get(int(c["league_id"]), {})} for c in cands]
        missing = [c for c in rows if "season" not in c]
        if args.plan:
            for r in rows:
                print(f"{r['rank']:>3} {r['league_id']:>5} {r['name'][:34]:34} {r.get('season', '-')!s:5} "
                      f"ends {r.get('end_date', '-')!s:10} tracked {r.get('tracked')!s:5} events {r.get('events')!s:5} "
                      f"lineups {r.get('lineups')!s:5} stats {r.get('statistics_fixtures')!s:5} "
                      f"players {r.get('statistics_players')!s:5} odds {r.get('odds')}")
            print(f"{len(rows)} candidate(s), {len(missing)} without a current season; "
                  f"at most {3 * (len(rows) - len(missing))} requests to probe them all")
            return 0
        from fbi.providers.api_football import ApiFootballProvider
        from scripts.capture_odds import _client

        targets = [(int(r["league_id"]), int(r["season"])) for r in rows if "season" in r]
        provider = ApiFootballProvider(_client(max_requests=args.max_requests))
        at = now()
        try:
            probes, run_id = await probe_leagues(conn, provider, targets, at=at, max_requests=args.max_requests)
        finally:
            await provider.aclose()
    by_league = {p.league: p for p in probes}
    folder = OUT / f"{at:%Y%m%dT%H%M%SZ}-probe"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "probe.json").write_text(json.dumps(
        {"at": at.isoformat(), "run_id": run_id, "probes": [p.as_dict() for p in probes],
         "without_current_season": [c["league_id"] for c in missing]}, indent=1, default=str), encoding="utf-8")
    (folder / "PROBE.md").write_text(markdown(rows, by_league, run_id), encoding="utf-8")
    print(f"{len(probes)} league(s) probed in run {run_id}: {sum(p.requests for p in probes)} requests; "
          f"report {folder.relative_to(REPO)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.runtime.log_level)
    ap = argparse.ArgumentParser(prog="probe_leagues", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="show the candidates and stop (no request)")
    ap.add_argument("--league", type=int, action="append", help="only this league (repeatable)")
    ap.add_argument("--max-requests", type=int, default=160)
    return asyncio.run(run(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
