"""What the new order of the research (RP-5.4, ``research-order-v1``) would do with the matches already kept, from the command line. Reading only.

    python -m scripts.ia_research_order                 # the next 3 days of the Bogotá calendar: levels, what was searched, what the order would search
    python -m scripts.ia_research_order --slots 40 --json

Per level A to D: how many matches, how many have a web search kept (``ai.fixture_passes``) and, with ``--slots`` (the matches the allowance gives
a day), how many the new order would search, plus the level A matches it would leave out (the plan wants none). It changes no order, no cap and no
budget: the cycle keeps its own until the owner turns the switch on. ``--dsn`` overrides the database. Exit status: 0 done, 3 a level A match is left
out, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai import research_order as ro
from fbi.ai.calendar import local_day
from fbi.ai.day import universe

OPTIONS = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=90000"
SEARCHED_SQL = """
SELECT DISTINCT fixture_id FROM ai.fixture_passes
 WHERE fixture_id = ANY(%(ids)s) AND COALESCE((counts->>'web_searches')::int, 0) > 0
"""


def build(conn: psycopg.Connection[Any], *, now: datetime, days: int, slots: int | None) -> dict[str, Any]:
    """The coverage of the matches of the next ``days`` days. The connection is the caller's and is only read."""
    first = local_day(now)
    fixtures = [f for d in range(days) for f in universe(conn, day=first + timedelta(days=d), at=now)]
    ranked = ro.ranked(fixtures)
    with conn.cursor() as cur:
        cur.execute(SEARCHED_SQL, {"ids": [r.fixture.fixture_id for r in ranked]})
        searched = {int(row[0]) for row in cur.fetchall()}
    chosen = None if slots is None else {r.fixture.fixture_id for r in ro.choose(ranked, slots * days)}
    left_out = [] if chosen is None else ro.level_a_unsearched(ranked, chosen)
    return {"version": ro.VERSION, "at": now.isoformat(), "days": days, "slots_per_day": slots, "matches": len(ranked),
            "levels": ro.coverage(ranked, searched, chosen=chosen), "level_a_left_out": left_out,
            "level_a_searched_before_match_day": sum(1 for r in ranked if r.level == "A" and r.fixture.fixture_id in searched)}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ia_research_order", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--slots", type=int, help="matches the allowance gives a day (to see what the new order would search)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn")
    args = ap.parse_args(argv)
    if args.days < 1 or (args.slots is not None and args.slots < 0):
        ap.error("--days must be at least 1 and --slots not negative")
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=OPTIONS) as conn:
        doc = build(conn, now=datetime.now(UTC), days=args.days, slots=args.slots)
        conn.rollback()
    if args.as_json:
        sys.stdout.write(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    else:
        lines = [f"Orden de investigación ({doc['version']}): {doc['matches']} partidos en {doc['days']} días"]
        for lv, c in doc["levels"].items():
            extra = f", la regla buscaría {c['would_search']}" if "would_search" in c else ""
            lines.append(f"  nivel {lv}: {c['matches']} partidos, {c['searched']} con búsqueda{extra}")
        lines.append(f"  nivel A con búsqueda: {doc['level_a_searched_before_match_day']}; nivel A que la regla deja fuera: {len(doc['level_a_left_out'])}")
        sys.stdout.write("\n".join(lines) + "\n")
    return 3 if doc["level_a_left_out"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
