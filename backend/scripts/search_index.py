"""The search index of AD-I01 (IA-078): ``core.search_entries``. 0 provider requests; reads the core tables only.

    python -m scripts.search_index status              # built or not, when, rows, size of the view and its indexes
    python -m scripts.search_index refresh             # dry run: says what it would do and whether the moment is allowed
    python -m scripts.search_index refresh --apply     # fill it (the first time) or refresh it CONCURRENTLY (afterwards)

Run it as the owner of the database (``docker compose run --rm ops python -m scripts.search_index refresh --apply``): only
the owner of a materialized view may refresh it. It refuses between 03:50 and 05:00 UTC and while a ``fixtures_sync`` run is
open (the moment the plan reserves for the night's jobs), unless ``--force``. The first fill locks the empty view for its
duration (about 8 s on a copy of production's names, 17-nov-2026); every later refresh is CONCURRENTLY: readers keep the
previous rows until the new ones are ready (about 17 s on the same copy). Nothing is written anywhere else.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from datetime import time as dtime
from typing import Any

import psycopg

from fbi.core.config import settings

QUIET_FROM, QUIET_TO = dtime(3, 50), dtime(5, 0)
"""The night's window the plan keeps free (AD-I01): never built between 03:50 and 05:00 UTC."""

STATE_SQL = """
SELECT c.relispopulated AS populated, c.reltuples::bigint AS rows_estimate,
       pg_total_relation_size(c.oid) AS total_bytes, pg_relation_size(c.oid) AS table_bytes
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'core' AND c.relname = 'search_entries' AND c.relkind = 'm'
"""

OPEN_SYNC_SQL = """
SELECT count(*) FROM raw.ingestion_runs
 WHERE status = 'running' AND job_type = 'fixtures_sync' AND started_at > now() - interval '6 hours'
"""


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.search_index", description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    p = sub.add_parser("refresh")
    p.add_argument("--apply", action="store_true", help="refresh it (without: a dry run)")
    p.add_argument("--force", action="store_true", help="also inside 03:50-05:00 UTC or during fixtures_sync")
    return ap


def in_quiet_window(at: datetime) -> bool:
    moment = at.astimezone(UTC).time()
    return QUIET_FROM <= moment < QUIET_TO


def refusal(at: datetime, open_syncs: int) -> str | None:
    """Why the refresh must not run now (None: it may)."""
    if in_quiet_window(at):
        return "03:50-05:00 UTC is kept for the night's jobs"
    if open_syncs:
        return f"{open_syncs} fixtures_sync run(s) open"
    return None


def state(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    row = conn.execute(STATE_SQL).fetchone()
    if row is None:
        return {"exists": False}
    populated, rows, total, table = row
    out: dict[str, Any] = {"exists": True, "populated": bool(populated), "rows_estimate": int(rows),
                           "total_mb": round(total / 2**20, 1), "table_mb": round(table / 2**20, 1)}
    if populated:
        found = conn.execute("SELECT indexed_at, count(*) FROM core.search_entries GROUP BY indexed_at").fetchall()
        out["indexed_at"] = found[0][0] if found else None
        out["by_kind"] = dict(conn.execute("SELECT kind, count(*) FROM core.search_entries GROUP BY kind ORDER BY kind")
                              .fetchall())
    return out


def refresh(conn: psycopg.Connection[Any], *, apply: bool, force: bool) -> int:
    now = datetime.now(UTC)
    before = state(conn)
    if not before["exists"]:
        _print({"error": "core.search_entries does not exist: run the migrations (0145) first"})
        return 1
    syncs = int((conn.execute(OPEN_SYNC_SQL).fetchone() or (0,))[0])
    why = refusal(now, syncs)
    mode = "CONCURRENTLY" if before["populated"] else "first fill"
    plan = {"mode": mode, "now_utc": now, "refused": why, "forced": force, "before": before, "apply": apply}
    if why and not force:
        _print(plan | {"done": False})
        return 2
    if not apply:
        _print(plan | {"done": False, "note": "dry run: add --apply"})
        return 0
    conn.execute("SET statement_timeout = '15min'")
    conn.execute("SET lock_timeout = '10s'")
    started = time.perf_counter()
    sql = ("REFRESH MATERIALIZED VIEW CONCURRENTLY core.search_entries" if before["populated"]
           else "REFRESH MATERIALIZED VIEW core.search_entries")
    conn.execute(sql)
    conn.commit()
    conn.execute("ANALYZE core.search_entries")
    conn.commit()
    _print(plan | {"done": True, "seconds": round(time.perf_counter() - started, 1), "after": state(conn)})
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.command == "status":
            _print(state(conn))
            return 0
        return refresh(conn, apply=args.apply, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
