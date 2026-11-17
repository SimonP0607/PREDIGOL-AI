"""The coded competition rules (IA-072, plan piece AD-B01), from the command line.

    python -m scripts.ia_rules check                       # the files and the coverage hold to the schema (no database)
    python -m scripts.ia_rules show --league 239 --season 2026 [--on 2026-09-01]   # what rules_for answers
    python -m scripts.ia_rules status                      # coverage against the tracked competitions, versions loaded
    python -m scripts.ia_rules load [--dry-run]            # after a deploy: record the versions in core.competition_rules
    python -m scripts.ia_rules reconstruct --league 39 --season 2025 --phase season.league --group "Premier League"

``load`` is the only command that writes, and only to the append-only table of migration 0143 (idempotent: a version already
recorded writes nothing). Every other command opens the database read-only (``status``, ``reconstruct``) or not at all
(``check``, ``show``). Nothing here calls a model or a web page. Exit 0; 1 when a check fails (an invalid file, a tracked
competition missing from the coverage, a reconstruction that disagrees); 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from fbi.competitions import reconstruction as rc
from fbi.competitions import rules as rl
from fbi.competitions import rules_store as store

OK, NO, CANNOT = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_rules", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("check", "show", "status", "load", "reconstruct"))
    ap.add_argument("--league", type=int, help="show/reconstruct: the provider's league id")
    ap.add_argument("--season", type=int, help="show/reconstruct: the provider's season key")
    ap.add_argument("--on", type=date.fromisoformat, help="show: the day (YYYY-MM-DD)")
    ap.add_argument("--phase", help="reconstruct: tournament.phase of the rules file (e.g. season.league)")
    ap.add_argument("--group", action="append", default=[], help="reconstruct: a provider table (core.standings.group_key)")
    ap.add_argument("--dry-run", action="store_true", help="load: what it would record, without writing")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def cmd_check(_args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    problems = rl.validate()
    if problems:
        return {"valid": False, "problems": problems}, NO
    return {"valid": True, **rl.summary(rl.Library.read())}, OK


def cmd_show(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.league is None or args.season is None:
        return {"error": "show needs --league and --season"}, CANNOT
    answer = rl.rules_for(args.league, args.season, on=args.on)
    out = answer.as_json()
    if isinstance(answer, rl.Coded):
        out["rules"] = answer.file.as_json()
    return out, OK


def _connect(args: argparse.Namespace, *, write: bool) -> psycopg.Connection[Any]:
    from fbi.core.config import settings as platform

    conn = psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC -c statement_timeout=60000")
    if not write:
        conn.read_only = True
    return conn


def cmd_status(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    lib = rl.Library.read()
    with _connect(args, write=False) as conn:
        tracked = store.tracked(conn)
        recorded = store.loaded(conn)
    summary = rl.summary(lib, {i: n for i, (n, _t) in tracked.items()})
    files = {(f.rules.league_id, f.rules.version): f.sha256 for f in lib.files}
    db = {(r["league_id"], r["version"]): r["sha256"] for r in recorded}
    summary["tracked"] = {"leagues": sum(1 for _n, t in tracked.values() if t == "league"),
                          "cups": sum(1 for _n, t in tracked.values() if t != "league")}
    summary["load_needed"] = sorted(f"{k[0]} v{k[1]}" for k, sha in files.items() if db.get(k) != sha)
    return summary, NO if summary["tracked_missing_from_coverage"] else OK


def cmd_load(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    problems = rl.validate()
    if problems:
        return {"error": "the files do not validate; nothing loaded", "problems": problems}, NO
    files = rl.load_files()
    planned = [{"league_id": f.rules.league_id, "version": f.rules.version, "file": f.path, "sha256": f.sha256} for f in files]
    if args.dry_run:
        return {"dry_run": True, "planned": planned}, OK
    with _connect(args, write=True) as conn:
        done = store.load(conn, files, at=datetime.now(UTC), code_version=os.environ.get("FBI_CODE_VERSION"))
        conn.commit()
    return {"loaded": [{"league_id": d.league_id, "version": d.version, "file": d.path, "created": d.created} for d in done],
            "note": "a version already recorded writes nothing (created = false)"}, OK


def cmd_reconstruct(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.league is None or args.season is None or not args.phase:
        return {"error": "reconstruct needs --league, --season and --phase"}, CANNOT
    answer = rl.rules_for(args.league, args.season)
    if not isinstance(answer, rl.Coded):
        return answer.as_json(), NO
    with _connect(args, write=False) as conn:
        data = store.season_data(conn, args.league, args.season)
    if data is None:
        return {"error": "season not in the database"}, CANNOT
    groups = args.group or (list(data.tables) if len(data.tables) == 1 else [])
    if not groups or any(g not in data.tables for g in groups):
        return {"error": "name the provider tables with --group", "tables": sorted(data.tables)}, CANNOT
    comparisons = rc.reconstruct(answer.rules, args.phase, data.matches, {g: data.tables[g] for g in groups})
    out = {"league_id": args.league, "season": args.season, "phase": args.phase, "rules_file": answer.file.path,
           "comparisons": [c.as_json() for c in comparisons],
           "snapshot_at": {g: data.snapshot_at[g].isoformat() for g in groups}}
    return out, OK if all(c.identical for c in comparisons) else NO


COMMANDS = {"check": cmd_check, "show": cmd_show, "status": cmd_status, "load": cmd_load, "reconstruct": cmd_reconstruct}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result, code = COMMANDS[args.command](args)
    except psycopg.Error as exc:
        result, code = {"error": f"database: {type(exc).__name__}"}, CANNOT
    except rl.RulesError as exc:
        result, code = {"error": str(exc)}, NO
    print(json.dumps(result, ensure_ascii=False, indent=None if args.as_json else 2, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
