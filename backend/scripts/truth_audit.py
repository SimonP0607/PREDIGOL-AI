"""Data truth audit: the provider's current answers against the database, field by field.

    python -m scripts.truth_audit                      # full audit (about 500 requests)
    python -m scripts.truth_audit --max-requests 200   # cap this run
    python -m scripts.truth_audit --seed 0.42          # repeat a sample
    python -m scripts.truth_audit --skip fixtures      # leave out a step (competitions, fixtures,
                                                       # details, standings, identities, upcoming)
    python -m scripts.truth_audit --internal-only      # zero requests: database checks, freshness, gate

Writes audit.truth_runs / audit.truth_findings and data/truth/<stamp>-truth-<id>/
(REPORT.md, summary.json, findings.json, sample.json). Nothing in core, market or
features is changed.

Exit status: 0 completed, 1 partial (requests failed or the cap stopped it), 2 usage.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from pathlib import Path

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.providers.api_football.build import build_client
from fbi.truth.audit import run_audit
from fbi.truth.sample import SampleSize

STEPS = ("competitions", "fixtures", "details", "standings", "identities", "upcoming")


async def _main(args: argparse.Namespace) -> int:
    seed = args.seed if args.seed is not None else round(random.random(), 6)
    skip = frozenset(STEPS) if args.internal_only else frozenset(args.skip or [])
    client = build_client(max_requests=args.max_requests)
    try:
        with psycopg.connect(settings.database.psycopg_url, autocommit=True) as conn:
            conn.execute("SET statement_timeout = '300s'")
            result = await run_audit(conn, client, at=now(), seed=seed, size=SampleSize(), out_root=args.out,
                                     skip=skip)
    finally:
        await client.aclose()
    worst = {name: t.summary()["by_severity"] for name, t in result.tallies.items() if t.total_findings}
    print(json.dumps({"run_id": result.run_id, "requests": result.requests, "stopped": result.stopped,
                      "failures": len(result.failures), "folder": str(result.folder), "seed": seed,
                      "findings": worst,
                      "freshness": {f.dataset: f.label() for f in result.freshness},
                      "gate": result.gate.by_model}, indent=1, default=str))
    return 1 if (result.stopped or result.failures) else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="truth_audit", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-requests", type=int, default=900)
    parser.add_argument("--seed", type=float, default=None)
    parser.add_argument("--skip", action="append", choices=STEPS)
    parser.add_argument("--internal-only", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("data/truth"))
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
