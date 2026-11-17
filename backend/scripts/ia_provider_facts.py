"""API-Football in the same model of facts (IA-128, AD-C10): its line-ups, absences, suspensions and events as typed assertions, and its
coverage per competition as a fact. READ ONLY: no request to the provider, no model, no write.

    python -m scripts.ia_provider_facts match --fixture 123 [--at 2026-11-17T18:00Z]   the facts of one match as known at a moment
    python -m scripts.ia_provider_facts coverage --days 7                              coverage of the competitions of the window
    python -m scripts.ia_provider_facts replay --days 14                               today's statuses of its evidence vs its assertions

Run it inside the worker's image after the deploy.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai import provider_facts, provider_facts_reads, unified_readers
from fbi.core.config import settings

READ_ONLY = "-c default_transaction_read_only=on -c statement_timeout=90000 -c TimeZone=UTC"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ia_provider_facts", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("command", choices=("match", "coverage", "replay"))
    parser.add_argument("--fixture", type=int)
    parser.add_argument("--at")
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    at = datetime.fromisoformat(args.at.replace("Z", "+00:00")) if args.at else now
    since = now - timedelta(days=max(1, min(30, args.days)))
    out: dict[str, Any]
    with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY) as conn:
        conn.read_only = True
        if args.command == "match":
            if args.fixture is None:
                parser.error("match needs --fixture")
            made, coverage = provider_facts_reads.facts_for(conn, [args.fixture])
            known = provider_facts.as_of(made.facts, at)
            out = {"fixture_id": args.fixture, "at": at.isoformat(), "counts": made.counts(), "known": len(known),
                   "coverage": coverage.get(args.fixture), "facts": [f.as_json() for f in known],
                   "rungs": [{"key": list(f.key), "rung": f.rung, "why": f.why} for f in provider_facts.rungs(made.facts, at=at)]}
        elif args.command == "coverage":
            fixtures = provider_facts_reads.fixtures_between(conn, since, now)
            _, coverage = provider_facts_reads.facts_for(conn, fixtures)
            out = {"since": since.isoformat(), "matches": len(fixtures), "competitions": provider_facts_reads.coverage_by_competition(coverage)}
        else:
            out = {"since": since.isoformat(), **unified_readers.provider_replay(conn, since=since, until=now)}
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
