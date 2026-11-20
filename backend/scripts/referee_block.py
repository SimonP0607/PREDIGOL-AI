"""PM-08-02: the block «Árbitro designado» (``fbi.people.referee_block``) - BUILT, NOT EXPOSED: the owner's read-only command.

    python -m scripts.referee_block show --fixture 1557464 [--at 2026-11-20T12:00:00Z]
    python -m scripts.referee_block next --league 239 [--days 7]       # the matches of the next days with a referee named

Inside the worker's container (``docker exec predigol-worker python -m scripts.referee_block ...``). Reads only, 0 requests. No route,
page or packet reads the block: it waits for the lawyer's answer on Ley 1581 (DM-08) and the owner's switch (``FBI_REFEREE_BLOCK``).
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
    s.add_argument("--at", type=datetime.fromisoformat)
    n = sub.add_parser("next")
    n.add_argument("--league", type=int, required=True, help="the provider's league id")
    n.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)

    import psycopg

    from fbi.api.contracts.referees import RefereeBlockOut
    from fbi.core.clock import now
    from fbi.core.config import settings
    from fbi.people import referee_block

    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name="referee_block") as conn:
        conn.execute("SET default_transaction_read_only = on")
        conn.execute("SET statement_timeout = '90s'")
        moment = now()
        if args.cmd == "show":
            block = referee_block.block_of(conn, args.fixture, at=args.at or moment)
            if block is None:
                print({"error": "partido_desconocido"})
                return 1
            print(json.dumps(RefereeBlockOut.model_validate(block.as_json()).model_dump(mode="json"), ensure_ascii=False, indent=1))
            return 0
        rows = conn.execute(
            "SELECT f.id FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
            "JOIN core.competitions c ON c.id = cs.competition_id WHERE c.provider_league_id = %s AND f.kickoff_at >= %s "
            "AND f.kickoff_at < %s ORDER BY f.kickoff_at, f.id", (args.league, moment, moment + timedelta(days=args.days))).fetchall()
        for (fid,) in rows:
            block = referee_block.block_of(conn, int(fid), at=moment)
            if block is not None:
                j = block.as_json()
                print(json.dumps({"fixture_id": fid, "state": j["state"], "referee": j["referee"], "matches": j["matches"],
                                  "figures": {f["key"]: [f["n"], f["value"], f["interval95"], f["league"]["value"], f["state"]]
                                              for f in j["figures"]}, "visibility": j["visibility"]}, ensure_ascii=False))
        print({"partidos": len(rows)})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
