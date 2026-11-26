"""What each team of the coming matches plays for, as calculated facts (RP-4.2, ``stakes-facts-v1``). Reading only: it writes nothing.

    python -m scripts.ia_stakes_facts                       # the next 3 days: how many matches have facts and why the others do not
    python -m scripts.ia_stakes_facts --days 7 --sheet 30   # plus the sheet of 30 matches to check against the official table, in Spanish
    python -m scripts.ia_stakes_facts --json

The facts are written by the worker only with ``FBI_STAKES_FACTS`` on. This command shows what they would say and which matches have none (a regulation
not coded, no reading, a team the reading does not place in a table). ``--sheet N`` lists, for N matches with a fact, the competition, the sides, the
reading's date and the sentence, so each one can be set against the official table by a person. ``--dsn`` overrides the database.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai import stakes_facts as sf

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"


def report(reads: Sequence[sf.Read], *, sheet: int) -> dict[str, Any]:
    having = [r for r in reads if r.facts]
    why: dict[str, int] = {}
    for r in reads:
        if r.why:
            why[r.why] = why.get(r.why, 0) + 1
    return {"version": sf.VERSION, "matches": len(reads), "with_facts": len(having), "facts": sum(len(r.facts) for r in reads), "without": why,
            "sheet": [{"fixture_id": r.match.fixture_id, "competition": r.competition, "kickoff": r.match.kickoff.isoformat(),
                       "home": r.home, "away": r.away, "reading_at": r.facts[0].calculation["reading_at"],
                       "facts": [{"side": f.side, "claim": f.claim} for f in r.facts]} for r in having[:sheet]]}


def lines(doc: dict[str, Any]) -> list[str]:
    out = [f"Qué se juega cada equipo ({doc['version']}): {doc['with_facts']} de {doc['matches']} partidos con hecho, {doc['facts']} hechos"]
    names = {sf.NOT_CODED: "reglamento no codificado", "no_reading": "sin lectura reciente", "no_table": "equipo sin tabla en la lectura"}
    out += [f"  sin hecho · {names.get(k, k)}: {n}" for k, n in sorted(doc["without"].items())]
    for row in doc["sheet"]:
        out.append(f"{row['kickoff'][:16]} · {row['competition']} · {row['home']} - {row['away']} (lectura {row['reading_at'][:16]})")
        out += [f"    {f['side']}: {f['claim']}" for f in row["facts"]]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_stakes_facts", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--sheet", type=int, default=0, help="list this many matches with their sentences")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    if args.days < 1 or args.sheet < 0:
        ap.error("--days must be at least 1 and --sheet cannot be negative")
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        doc = report(sf.collect(conn, at=datetime.now(UTC), ahead=timedelta(days=args.days)), sheet=args.sheet)
    sys.stdout.write((json.dumps(doc, indent=1, ensure_ascii=False) if args.as_json else "\n".join(lines(doc))) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
