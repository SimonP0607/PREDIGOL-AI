"""Fill new tables from stored RAW payloads - no provider request, nothing existing changed.

    python -m scripts.backfill_from_raw --fixture-facts            # core.fixture_facts + core.fixture_player_extras
    python -m scripts.backfill_from_raw --fixture-facts --dry-run  # count what would be added, write nothing
    python -m scripts.backfill_from_raw --fixture-facts --since 2026-09-01

Every stored /fixtures payload is read in the order it was fetched (``raw.ingestion_payloads.fetched_at``,
the time the provider said it) and written through the same change-only writers the live ingestion uses:
a row is added only when a payload says something new and is newer than the newest row, so the result
is the history the live writers would have kept, and running it twice adds nothing. Payload files are
read, never modified. The run is recorded in raw.ingestion_runs (job raw_backfill_fixture_facts).
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.ingestion.fixture_facts import NORMALIZER_VERSION, apply_fixture_facts, apply_player_extras
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.api_football.details import iter_fixture_details, iter_fixture_facts

REPO = Path(__file__).resolve().parents[1]

PAYLOADS_SQL = """
SELECT hash, file_path, fetched_at, params ? 'ids' OR params ? 'id' AS detail
  FROM raw.ingestion_payloads
 WHERE endpoint = '/fixtures' AND http_status = 200 AND (%(since)s::date IS NULL OR fetched_at >= %(since)s::date)
 ORDER BY fetched_at, hash
"""

FIXTURES_SQL = """
SELECT f.provider_fixture_id, f.id, th.provider_team_id, ta.provider_team_id FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.provider_fixture_id = ANY(%s)
"""


def _body(raw_root: Path, file_path: str) -> dict[str, Any] | None:
    f = Path(file_path) if Path(file_path).is_absolute() else raw_root / file_path
    try:
        data = f.read_bytes()
    except OSError:
        return None
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    doc = json.loads(data)
    body = doc.get("body", doc) if isinstance(doc, dict) else None
    return body if isinstance(body, dict) else None


def fixture_facts(conn: psycopg.Connection[Any], *, since: date | None, dry_run: bool) -> dict[str, int]:
    raw_root = Path(settings.runtime.raw_store_dir)
    raw_root = raw_root if raw_root.is_absolute() else REPO / raw_root
    out = {"payloads": 0, "unreadable": 0, "facts_added": 0, "extras_added": 0, "detail_payloads": 0}
    with conn.cursor() as cur:
        cur.execute(PAYLOADS_SQL, {"since": since})
        payloads = cur.fetchall()
    for i, (h, path, fetched_at, detail) in enumerate(payloads, 1):
        body = _body(raw_root, str(path))
        if body is None:
            out["unreadable"] += 1
            continue
        out["payloads"] += 1
        out["facts_added"] += apply_fixture_facts(conn, iter_fixture_facts(body), payload_hash=str(h),
                                                  observed_at=fetched_at)
        if detail:
            out["detail_payloads"] += 1
            details = list(iter_fixture_details(body))
            with conn.cursor() as cur:
                cur.execute(FIXTURES_SQL, ([d.provider_fixture_id for d in details],))
                known = {int(a): (int(b), int(c), int(d)) for a, b, c, d in cur.fetchall()}
                for d in details:
                    if d.provider_fixture_id not in known or "players" not in d.blocks_present:
                        continue
                    fid, home, away = known[d.provider_fixture_id]
                    out["extras_added"] += apply_player_extras(cur, fid, {home: "home", away: "away"}, d.players,
                                                               payload_hash=str(h), observed_at=fetched_at)
        if i % 500 == 0:
            conn.rollback() if dry_run else conn.commit()
            print(json.dumps({"progress": i, "of": len(payloads), **out}), flush=True)
    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture-facts", action="store_true", help="core.fixture_facts and core.fixture_player_extras")
    ap.add_argument("--since", type=date.fromisoformat, help="only payloads fetched on or after this date")
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    args = ap.parse_args(argv)
    if not args.fixture_facts:
        ap.error("nothing to do: give --fixture-facts")
    with psycopg.connect(settings.database.psycopg_url) as conn:
        ledger = RunLedger(conn)
        run_id = None if args.dry_run else ledger.open(
            "raw_backfill_fixture_facts", params={"since": str(args.since) if args.since else None,
                                                  "normalizer_version": NORMALIZER_VERSION})
        counters = RunCounters()
        try:
            result = fixture_facts(conn, since=args.since, dry_run=args.dry_run)
            counters.rows_normalized = result["payloads"]
            counters.rows_inserted = result["facts_added"] + result["extras_added"]
        finally:
            if run_id is not None:
                ledger.close(run_id, counters, notes="RAW -> core.fixture_facts / core.fixture_player_extras, "
                                                     "change-only, 0 requests")
    print(json.dumps({"dry_run": args.dry_run, "normalizer_version": NORMALIZER_VERSION, **result}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
