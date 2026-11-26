"""The coach, the usual formation and the referee of the coming matches, as calculated facts (RP-4.4 first tranche, ``people-facts-v1``). Reading only.

    python -m scripts.ia_people_facts                       # the next 3 days: how many matches have each fact and how many lack it
    python -m scripts.ia_people_facts --days 7 --sheet 30   # plus the sheet of 30 matches, in Spanish, to check against the club and the provider
    python -m scripts.ia_people_facts --json

The facts are written by the worker only with ``FBI_PEOPLE_FACTS`` on (the hook is requested apart). This command shows what they would say and, above all,
the COVERAGE: of the matches of the window, how many have a coach on a sheet, a usual formation and a referee named by now. The referee line is the baseline of
the plan's test of asking later (the audit found him known before kick-off in 54 % of the matches). ``--dsn`` overrides the database.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai import people_facts as pf

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"
SLOTS = ("coach:home", "coach:away", "formation:home", "formation:away", "referee")


def report(reads: Sequence[pf.Read], *, sheet: int) -> dict[str, Any]:
    n = len(reads)
    lacking = {slot: sum(1 for r in reads if slot in r.missing) for slot in SLOTS}
    having = [r for r in reads if r.facts]
    return {"version": pf.VERSION, "matches": n, "facts": sum(len(r.facts) for r in reads), "with_facts": len(having),
            "coverage": {slot: {"with": n - lacking[slot], "of": n, "share": None if n == 0 else round((n - lacking[slot]) / n, 3)} for slot in SLOTS},
            "sheet": [{"fixture_id": r.match.fixture_id, "competition": r.competition, "kickoff": r.match.kickoff.isoformat(), "home": r.home, "away": r.away,
                       "facts": [{"kind": f.kind, "side": f.side, "claim": f.claim} for f in r.facts], "missing": r.missing} for r in having[:sheet]]}


def lines(doc: dict[str, Any]) -> list[str]:
    out = [f"Entrenador, formación y árbitro ({doc['version']}): {doc['with_facts']} de {doc['matches']} partidos con algún hecho, {doc['facts']} hechos"]
    names = {"coach:home": "entrenador local", "coach:away": "entrenador visitante", "formation:home": "formación local",
             "formation:away": "formación visitante", "referee": "árbitro nombrado"}
    for slot in SLOTS:
        c = doc["coverage"][slot]
        share = "—" if c["share"] is None else f"{c['share'] * 100:.0f} %"
        out.append(f"  {names[slot]}: {c['with']} de {c['of']} ({share})")
    for row in doc["sheet"]:
        out.append(f"{row['kickoff'][:16]} · {row['competition']} · {row['home']} - {row['away']}" + (f" (sin: {', '.join(row['missing'])})" if row["missing"] else ""))
        out += [f"    {f['kind']} {f['side']}: {f['claim']}" for f in row["facts"]]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_people_facts", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--sheet", type=int, default=0, help="list this many matches with their sentences")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    if args.days < 1 or args.sheet < 0:
        ap.error("--days must be at least 1 and --sheet cannot be negative")
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        doc = report(pf.collect(conn, at=datetime.now(UTC), ahead=timedelta(days=args.days)), sheet=args.sheet)
    sys.stdout.write((json.dumps(doc, indent=1, ensure_ascii=False) if args.as_json else "\n".join(lines(doc))) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
