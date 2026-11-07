"""The single registry of promotions (``registry-v1``, Plan Maestro IA, phase P0), from the command line.

    python -m scripts.ia_registry list                                       # every decision of every ledger, oldest first
    python -m scripts.ia_registry list --type calibrator --json
    python -m scripts.ia_registry show --type agent --key 1X2                # the history of one key and what is in force
    python -m scripts.ia_registry show --type model --key model_code --at 2026-10-23T00:00:00+00:00

Read-only (``fbi.governance.promotions``): nothing is written to any ledger. Exit 0, or 2 when it cannot run (a bad argument); ``show``
exits 1 when the key has no record at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg

from fbi.governance import promotions as registry

COMMANDS = ("list", "show")
OK, NO, CANNOT = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_registry", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--type", choices=registry.ENTITY_TYPES, help="the kind of entity")
    ap.add_argument("--key", help="show: the key (e.g. OU/dixon_coles, 1X2, model_code, forecast_spec, neutral_venue, a gate)")
    ap.add_argument("--at", help="the registry as of this moment (ISO 8601 with its offset)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the result as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def line_of(p: registry.Promotion) -> str:
    flag = "" if p.effective else " (declared in code, not on record)"
    return (f"  {p.at.isoformat(timespec='minutes')}  {p.entity_type:<14} {p.entity_key:<22} {p.version or '-':<28} {p.decision:<13}"
            f" {p.decided_by:<6} {p.gate_version or '-':<14} {p.source_table}#{p.source_id}{flag}  {p.reason[:80]}")


def run(args: argparse.Namespace, conn: psycopg.Connection[Any]) -> tuple[dict[str, Any] | str, int]:
    at = None
    if args.at:
        try:
            at = datetime.fromisoformat(args.at)
        except ValueError:
            return {"error": f"{args.at!r} is not a moment (ISO 8601)"}, CANNOT
        if at.tzinfo is None:
            return {"error": "--at needs its offset (e.g. +00:00)"}, CANNOT
    if args.command == "list":
        rows = registry.all_promotions(conn, at=at, entity_type=args.type)
        if args.as_json:
            return {"version": registry.VERSION, "at": args.at, "promotions": [p.as_json() for p in rows]}, OK
        return "\n".join([f"{registry.VERSION}: {len(rows)} decisions", *(line_of(p) for p in rows)]), OK
    if not args.type or not args.key:
        return {"error": "show needs --type and --key"}, CANNOT
    records = registry.all_promotions(conn, at=at)
    rows = registry.history_of(records, args.type, args.key)
    now = registry.current_of(records, args.type, args.key)
    code = OK if rows else NO
    if args.as_json:
        return {"version": registry.VERSION, "at": args.at, "entity_type": args.type, "key": args.key,
                "current": None if now is None else now.as_json(), "history": [p.as_json() for p in rows]}, code
    state = "no record" if now is None else (f"in force: {now.version or '-'} ({now.decision}, {now.at.isoformat(timespec='minutes')})"
                                             if now.in_force else f"nothing in force; last: {now.decision} {now.at.isoformat(timespec='minutes')}")
    return "\n".join([f"{registry.VERSION} {args.type} {args.key}: {state}", *(line_of(p) for p in rows)]), code


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        conn.read_only = True
        out, code = run(args, conn)
        conn.rollback()
    if isinstance(out, str):
        sys.stdout.write(out + "\n")
    else:
        sys.stdout.write(json.dumps(out, indent=1, default=str, ensure_ascii=False) + "\n")
        if code == CANNOT and "error" in out:
            sys.stderr.write(f"{out['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
