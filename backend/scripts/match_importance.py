"""PM-05-08: the facts of a match's «importance» (``fbi.competitions.importance``) - the owner's read-only command.

    python -m scripts.match_importance show --fixture 1557464 [--at 2026-11-20T12:00:00Z]
    python -m scripts.match_importance round --league 239 --season 2026 [--days 7]   # every match of the next days of a season

Inside the worker's container (``docker exec predigol-worker python -m scripts.match_importance ...``). Reads only (a read-only
transaction), 0 provider requests, whatever ``FBI_MATCH_IMPORTANCE_FACTS`` says: the switch decides who may see the facts, and nothing a
reader sees reads them while it is off.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime, timedelta


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("--fixture", type=int, required=True, help="core.fixtures.id")
    s.add_argument("--at", type=datetime.fromisoformat, help="the moment asked (default: now, or the kick-off if earlier)")
    r = sub.add_parser("round")
    r.add_argument("--league", type=int, required=True, help="the provider's league id")
    r.add_argument("--season", type=int, required=True)
    r.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)

    import psycopg

    from fbi.competitions import importance
    from fbi.core.clock import now
    from fbi.core.config import settings

    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name="match_importance") as conn:
        conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET statement_timeout = '60s'")
        moment = now()
        if args.cmd == "show":
            facts = importance.facts_of(conn, args.fixture, at=args.at or moment)
            print(json.dumps(None if facts is None else facts.as_json(), ensure_ascii=False, indent=1))
            return 0 if facts is not None else 1
        rows = conn.execute(
            "SELECT f.id FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
            "JOIN core.competitions c ON c.id = cs.competition_id WHERE c.provider_league_id = %s AND cs.season = %s "
            "AND f.kickoff_at >= %s AND f.kickoff_at < %s ORDER BY f.kickoff_at, f.id",
            (args.league, args.season, moment, moment + timedelta(days=args.days))).fetchall()
        for (fid,) in rows:
            facts = importance.facts_of(conn, int(fid), at=moment)
            if facts is not None:
                print(json.dumps(facts.as_json(), ensure_ascii=False))
        print({"partidos": len(rows)})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
