"""P3: track an expansion batch of config/expansion.yaml (0 provider requests).

    python -m scripts.expand_leagues --batch 1            # what tracking the batch would change; nothing written
    python -m scripts.expand_leagues --batch 1 --apply    # track it

The competitions and every season the provider lists come from raw.league_coverage - the /leagues answer already on
disk - through the same catalogue builder as the selection (fbi.catalog.from_raw.build_catalogue): it sets
``is_tracked`` for the batch's leagues and touches no other competition's tracking. From then on the worker follows
them like any tracked league (fixtures, pre-match and live odds, tables, injuries, reference feeds); their history is
migrated as the batch's own tier (``python -m scripts.migration plan|seed|run --tiers <tier>``).

Before anything is written the batch must match the provider: every league must be in raw.league_coverage, and its
name and country there (newest season) must be the ones config/expansion.yaml gives it. A wrong id is refused, not
tracked as some other competition.

One run in the ledger (``league_expansion``) records what was tracked and when.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.catalog.from_raw import build_catalogue
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.migration.config import EXPANSION_FILE, expansion_batches

STATE_SQL = """
SELECT l.league AS provider_league_id,
       (SELECT count(*) FROM raw.league_coverage lc WHERE lc.provider_league_id = l.league) AS seasons_listed,
       (SELECT max(lc.season) FILTER (WHERE lc.is_current) FROM raw.league_coverage lc
         WHERE lc.provider_league_id = l.league) AS current_season,
       (SELECT lc.league_name FROM raw.league_coverage lc WHERE lc.provider_league_id = l.league
         ORDER BY lc.season DESC LIMIT 1) AS provider_name,
       (SELECT lc.country FROM raw.league_coverage lc WHERE lc.provider_league_id = l.league
         ORDER BY lc.season DESC LIMIT 1) AS provider_country,
       c.id IS NOT NULL AS known, COALESCE(c.is_tracked, false) AS tracked, c.tier
  FROM unnest(%(ids)s::int[]) AS l(league)
  LEFT JOIN core.competitions c ON c.provider_league_id = l.league
 ORDER BY 1
"""


def batch_of(number: int) -> dict[str, Any]:
    for b in expansion_batches(EXPANSION_FILE):
        if int(b["batch"]) == number:
            return b
    raise SystemExit(f"batch {number} is not in {EXPANSION_FILE}")


def _same(a: object, b: object) -> bool:
    return " ".join(str(a or "").split()).casefold() == " ".join(str(b or "").split()).casefold()


def identity_mismatches(batch: dict[str, Any], state: list[dict[str, Any]]) -> list[str]:
    """Leagues whose name or country in raw.league_coverage is not what config/expansion.yaml says they are.

    Only what the config states is checked: a league that is not a candidate has its id as name and no country."""
    names: dict[int, str] = batch.get("names") or {}
    countries: dict[int, str] = batch.get("countries") or {}
    out: list[str] = []
    for r in state:
        lid = int(r["provider_league_id"])
        if not r["seasons_listed"]:
            continue  # reported as missing
        want_name, want_country = names.get(lid), countries.get(lid)
        if want_name is not None and want_name != str(lid) and not _same(want_name, r["provider_name"]):
            out.append(f"{lid}: provider calls it {r['provider_name']!r}, config says {want_name!r}")
        if want_country is not None and not _same(want_country, r["provider_country"]):
            out.append(f"{lid}: provider country {r['provider_country']!r}, config says {want_country!r}")
    return out


def expand(conn: psycopg.Connection[Any], batch: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    leagues = [int(x) for x in batch["leagues"]]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(STATE_SQL, {"ids": leagues})
        state = cur.fetchall()
    missing = [r["provider_league_id"] for r in state if not r["seasons_listed"]]
    out: dict[str, Any] = {"batch": batch["batch"], "tier": batch["tier"], "leagues": state, "missing": missing}
    if missing:
        out["refused"] = f"not in raw.league_coverage: {missing}; read /leagues first"
        return out
    wrong = identity_mismatches(batch, state)
    if wrong:
        out["mismatched"] = wrong
        out["refused"] = "the provider's name or country differs from config/expansion.yaml: " + "; ".join(wrong)
        return out
    if not apply:
        return out
    ledger = RunLedger(conn)
    run_id = ledger.open("league_expansion", params={"batch": batch["batch"], "tier": batch["tier"],
                                                      "leagues": leagues}, scheduled_for=now())
    counters = RunCounters()
    try:
        report = build_catalogue(conn, tiers={lid: int(batch["tier"]) for lid in leagues})
        counters.rows_inserted = report.competitions_inserted + report.seasons_inserted
        counters.rows_updated = report.competitions_updated + report.seasons_updated
        out["catalogue"] = report.as_dict()
    finally:
        ledger.close(run_id, counters, notes=f"expansion batch {batch['batch']}: {len(leagues)} league(s) tracked")
        conn.commit()
    out["run_id"] = run_id
    return out


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.runtime.log_level)
    ap = argparse.ArgumentParser(prog="expand_leagues", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    batch = batch_of(args.batch)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        out = expand(conn, batch, apply=args.apply)
    print(f"batch {out['batch']} (tier {out['tier']}):")
    for r in out["leagues"]:
        print(f"  {r['provider_league_id']:>5}  name {batch['names'].get(r['provider_league_id'], '?')[:34]:34} "
              f"provider {str(r['provider_name'] or '-')[:34]:34} "
              f"seasons listed {r['seasons_listed']:>3}  current {r['current_season']}  known {r['known']!s:5} "
              f"tracked {r['tracked']!s:5} tier {r['tier']}")
    if out.get("refused"):
        print("REFUSED: " + out["refused"])
        return 1
    if "catalogue" in out:
        print(f"tracked in run {out['run_id']}: {out['catalogue']}")
    else:
        print("dry run: re-run with --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
