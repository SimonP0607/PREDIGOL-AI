"""The pre-purchase probe: two requests that settle what the plan choice turns on.

1. ``/fixtures?ids=`` for two stored, finished fixtures: do the detail blocks
   (events, lineups, team statistics, player statistics) come back on this
   account? With them the migration costs ~1 request per 20 fixtures; without
   them, 4 per fixture.
2. ``/leagues``: every league, every season, every coverage flag, and the
   provider's own name for each id - so the plan is priced on verified
   coverage and a wrong id in config/migration.yaml is caught before seeding.

Both payloads are stored and indexed (lineage) and both requests are counted
by whatever quota the provider's client carries.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from typing import Any

import psycopg

from fbi.ingestion.details import apply_coverage, apply_fixture_details
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.migration.facts import DatabaseFacts, name_mismatches

BLOCKS = ("events", "lineups", "statistics", "players")


@dataclass
class ProbeReport:
    fixture_ids: list[int]
    fixtures_returned: int = 0
    blocks_present: dict[str, int] = field(default_factory=dict)
    detail_kb_per_fixture: float | None = None
    detail_rows: int = 0
    coverage_rows: int = 0
    name_mismatches: list[tuple[int, str, str]] = field(default_factory=list)
    requests: int = 0
    run_id: int | None = None

    @property
    def ids_batching_available(self) -> bool:
        return self.fixtures_returned > 0 and all(
            self.blocks_present.get(b, 0) == self.fixtures_returned for b in BLOCKS)


async def run_probe(conn: psycopg.Connection, provider: Any, fixture_ids: list[int], *,
                    configured: dict[int, str]) -> ProbeReport:
    ledger = RunLedger(conn)
    run_id = ledger.open("plan_probe", params={"fixture_ids": fixture_ids, "leagues": "all"})
    report = ProbeReport(list(fixture_ids), run_id=run_id)
    counters = RunCounters()
    try:
        details, raw = await provider.fetch_fixture_details(provider_fixture_ids=fixture_ids)
        counters.api_calls += 1
        counters.payloads_stored += ledger.record_payloads(run_id, [raw])
        rep = apply_fixture_details(conn, details, payload_hash=raw.payload_hash, fetched_at=raw.fetched_at)
        conn.commit()
        report.fixtures_returned = len(details)
        report.blocks_present = {b: sum(1 for d in details if b in d.blocks_present) for b in BLOCKS}
        size = len(gzip.compress(json.dumps(raw.body, separators=(",", ":")).encode()))
        report.detail_kb_per_fixture = size / max(len(details), 1) / 1024
        report.detail_rows = rep.rows
        refs, raw2 = await provider.fetch_coverage(league_id=None)
        counters.api_calls += 1
        counters.payloads_stored += ledger.record_payloads(run_id, [raw2])
        report.coverage_rows = apply_coverage(conn, refs, payload_hash=raw2.payload_hash, fetched_at=raw2.fetched_at)
        conn.commit()
        report.name_mismatches = name_mismatches(DatabaseFacts(conn), configured)
    except Exception as exc:
        conn.rollback()
        counters.errors.append(f"{type(exc).__name__}: {exc}"[:500])
        ledger.close(run_id, counters, notes="probe failed")
        raise
    report.requests = counters.api_calls
    counters.rows_inserted = report.detail_rows + report.coverage_rows
    ledger.close(run_id, counters, notes=f"plan probe: ids batching "
                                         f"{'available' if report.ids_batching_available else 'NOT available'}")
    return report
