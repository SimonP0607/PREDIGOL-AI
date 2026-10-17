"""Run the reference feeds by hand, or show what is due (fbi.ingestion.reference).

    python -m scripts.reference_refresh --plan                         # due targets per feed, no request
    python -m scripts.reference_refresh --feed predictions --feed rounds --max-requests 50
    python -m scripts.reference_refresh --max-requests 300             # what the worker does every 30 min
    python -m scripts.reference_refresh --feed profiles_players --per-feed 2000 --max-requests 2000   # a catch-up

Same budget rules as the worker: never into the live reserve, never past ``--max-requests``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import replace

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.ingestion.reference import FEEDS, due_targets, refresh_reference


async def run(args: argparse.Namespace) -> int:
    feeds = [f for f in FEEDS if not args.feed or f.name in args.feed]
    if args.per_feed:
        feeds = [replace(f, max_per_run=args.per_feed) for f in feeds]
    unknown = set(args.feed or []) - {f.name for f in FEEDS}
    if unknown:
        print(f"unknown feed(s): {', '.join(sorted(unknown))}; known: {', '.join(f.name for f in FEEDS)}")
        return 2
    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.plan:
            at = now()
            plan = {}
            for f in feeds:
                due = due_targets(conn, f, at)
                plan[f.name] = {"due": len(due), "requests_if_all": -(-len(due) // f.batch),
                                "first": [t.key for t in due[:3]]}
            print(json.dumps(plan, indent=1))
            return 0
        from fbi.providers.api_football import ApiFootballProvider
        from scripts.capture_odds import _client

        provider = ApiFootballProvider(_client(max_requests=args.max_requests))
        try:
            report = await refresh_reference(conn, provider, daily_budget=settings.provider_plan.effective_budget,
                                             max_requests=args.max_requests, feeds=feeds,
                                             prematch_windows=settings.odds.prematch_windows)
        finally:
            await provider.aclose()
    print(json.dumps(report.__dict__, indent=1, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="show the due targets per feed and stop")
    ap.add_argument("--feed", action="append", help="only this feed (repeatable)")
    ap.add_argument("--max-requests", type=int, default=100)
    ap.add_argument("--per-feed", type=int, default=0,
                    help="raise each feed's per-run request cap for a catch-up (still inside --max-requests, the "
                         "daily budget and the live reserve)")
    return asyncio.run(run(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
