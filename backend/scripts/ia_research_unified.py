"""The unified research in shadow (IA-087/088/089): the owner's measures, READ ONLY (``fbi.ai.unified_readers``).

    python -m scripts.ia_research_unified report  --days 7     the xu_* counts of the passes, the pages remembered, the calls (LAB)
    python -m scripts.ia_research_unified linking --days 7     AD-C06: unidentified players with the whole squad vs research v2's thirty
    python -m scripts.ia_research_unified windows --days 7     AD-C05: is the player of each v1 fact in the windows the road would send?
    python -m scripts.ia_research_unified replay  --days 30    AD-C07: ladder-v1 vs ladder-v2 on the stored web evidence

No model, no search, no write: the connection is read-only with a statement timeout. Run it inside the worker's image after the deploy.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai import source_policy, unified_readers
from fbi.core.config import settings

READ_ONLY = "-c default_transaction_read_only=on -c statement_timeout=90000 -c TimeZone=UTC"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ia_research_unified", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("measure", choices=("report", "linking", "windows", "replay"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args(argv)
    until = datetime.now(UTC)
    since = until - timedelta(days=max(1, min(60, args.days)))
    with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY) as conn:
        conn.read_only = True
        out: dict[str, Any]
        if args.measure == "report":
            out = unified_readers.report(conn, since=since, until=until)
        elif args.measure == "linking":
            out = unified_readers.linking(conn, since=since, until=until, at=until, limit=args.limit)
        elif args.measure == "windows":
            out = unified_readers.windows(conn, since=since, until=until, at=until, limit=args.limit)
        else:
            out = unified_readers.replay(conn, since=since, until=until, policy=source_policy.load(conn), limit=args.limit)
    print(json.dumps({"measure": args.measure, "since": since.isoformat(), "until": until.isoformat(), **out}, ensure_ascii=False, indent=2,
                     default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
