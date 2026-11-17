"""The current coach of a team and the corrections of the open careers his match sheets contradict (AD-H03; IA-075).
0 provider requests.

    python -m scripts.coach_current show 541 529                # the current coach of these teams, with source and date
    python -m scripts.coach_current audit                       # the rule over every team: answers, corrections it would write
    python -m scripts.coach_current counts                      # teams by open careers, provider-only and net of corrections
    python -m scripts.coach_current close                       # dry run: how many corrections would be written
    python -m scripts.coach_current close --apply               # write them (append-only; a second pass writes nothing)
    python -m scripts.coach_current retract 17 --note "..." --apply   # withdraw one correction

Nothing here writes ``core.coach_careers`` or any provider table. The actor recorded is ``script:coach_current``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.people import current_coach_store as store

ACTOR = "script:coach_current"


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m scripts.coach_current", description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("show")
    p.add_argument("team_ids", type=int, nargs="+")
    sub.add_parser("audit")
    sub.add_parser("counts")
    p = sub.add_parser("close")
    p.add_argument("--team", type=int, action="append", dest="teams")
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("retract")
    p.add_argument("correction_id", type=int)
    p.add_argument("--note", required=True)
    p.add_argument("--apply", action="store_true")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging("WARNING")
    args = build_parser().parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        conn.execute("SET statement_timeout = '10min'")
        if args.command == "show":
            _print(store.current_coach(conn, args.team_ids))
        elif args.command == "audit":
            _print(store.audit(conn))
        elif args.command == "counts":
            _print(store.team_open_counts(conn))
        elif args.command == "close":
            _print(store.close(conn, apply=args.apply, actor=ACTOR, team_ids=args.teams).as_dict())
        elif args.command == "retract":
            _print(store.retract(conn, args.correction_id, actor=ACTOR, note=args.note, apply=args.apply))
        if getattr(args, "apply", False):
            conn.commit()
        else:
            conn.rollback()
    return 0


if __name__ == "__main__":
    sys.exit(main())
