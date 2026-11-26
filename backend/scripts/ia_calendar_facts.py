"""Rest, congestion, the next match, the minutes of the usual starters and the probable rotation of each side of the coming matches, as calculated facts (RP-4.3,
``calendar-facts-v1`` and ``minutes-facts-v1``). Reading only: it writes nothing.

    python -m scripts.ia_calendar_facts                      # the next 3 days: how many sides have a fact, how many with a whole calendar
    python -m scripts.ia_calendar_facts --days 7 --sheet 20  # plus the sentences of 20 matches
    python -m scripts.ia_calendar_facts --json

The facts are written by the worker only with ``FBI_CALENDAR_FACTS`` on. This command shows how many of the sides of the coming matches have a fact (the plan's
acceptance is 95 % of the matches followed with a market, over 7 days) and how many of them rest on a calendar that is whole. ``--dsn`` overrides the database.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai import calendar_facts as cf

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"


def report(reads: Sequence[cf.Read], *, sheet: int) -> dict[str, Any]:
    sides = 2 * len(reads)
    facts = [f for r in reads for f in r.facts if f.story == "calendar"]
    whole = sum(1 for f in facts if f.calculation["whole"])
    minutes = sum(1 for r in reads for f in r.facts if f.story == "minutes")
    rotation = sum(1 for r in reads for f in r.facts if f.story == "rotation")
    return {"version": cf.VERSION, "matches": len(reads), "sides": sides, "with_fact": len(facts), "whole_calendar": whole, "not_whole": len(facts) - whole,
            "without_fact": sides - len(facts), "coverage": None if not sides else round(len(facts) / sides, 4),
            "minutes_facts": minutes, "rotation_facts": rotation,
            "sheet": [{"fixture_id": r.match.fixture_id, "competition": r.competition, "kickoff": r.match.kickoff.isoformat(), "home": r.home, "away": r.away,
                       "facts": [{"side": f.side, "claim": f.claim} for f in r.facts]} for r in [r for r in reads if r.facts][:sheet]]}


def lines(doc: dict[str, Any]) -> list[str]:
    cover = "sin partidos" if doc["coverage"] is None else f"{100 * doc['coverage']:.1f} %"
    out = [f"Calendario de cada equipo ({doc['version']}): {doc['with_fact']} de {doc['sides']} lados con hecho ({cover}); calendario completo en "
           f"{doc['whole_calendar']}, incompleto en {doc['not_whole']}; sin hecho (sin partido previo): {doc['without_fact']}",
           f"Minutos de los titulares habituales: {doc['minutes_facts']} lados; rotación probable: {doc['rotation_facts']} lados"]
    for row in doc["sheet"]:
        out.append(f"{row['kickoff'][:16]} · {row['competition']} · {row['home']} - {row['away']}")
        out += [f"    {f['side']}: {f['claim']}" for f in row["facts"]]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_calendar_facts", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--sheet", type=int, default=0, help="list this many matches with their sentences")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    if args.days < 1 or args.sheet < 0:
        ap.error("--days must be at least 1 and --sheet cannot be negative")
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        doc = report(cf.collect(conn, at=datetime.now(UTC), ahead=timedelta(days=args.days)), sheet=args.sheet)
    sys.stdout.write((json.dumps(doc, indent=1, ensure_ascii=False) if args.as_json else "\n".join(lines(doc))) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
