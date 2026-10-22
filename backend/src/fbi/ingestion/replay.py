"""Re-normalise stored /fixtures payloads. Zero provider requests.

The raw store exists for exactly this. A response was fetched, hashed and
kept; later the normaliser learned to read something it used to throw away -
the score, the round, the venue - and the bytes are still on disk. Replaying
them recovers what was OBSERVED at the time, stamped with the time it was
observed. Nothing is fetched and nothing is inferred.

It is not a way to invent history:

  * every file is verified against the hash it was indexed under before it is
    read; a file that does not match is refused, not "repaired";
  * writes carry the payload's hash and fetch time, and are monotonic on the
    latter, so a replayed response from the 12th cannot overwrite what a
    response from the 14th established;
  * a fixture of a competition we do not track is skipped, exactly as it is in
    the live sync.

By default the replay runs inside a transaction that is rolled back, and only
reports what it would change. ``apply=True`` commits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.ingestion.apply import apply_fixtures_payload
from fbi.ingestion.fixtures import tracked_season_ids
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.base import FootballDataProvider
from fbi.storage.payload_store import PayloadStore, body_hash

log = structlog.get_logger(__name__)

FIXTURE_ENDPOINTS = ("/fixtures", "fixtures")


@dataclass
class ReplayReport:
    payloads_considered: int = 0
    payloads_applied: int = 0
    payloads_refused: list[str] = field(default_factory=list)
    fixtures_inserted: int = 0
    fixtures_updated: int = 0
    results_written: int = 0
    committed: bool = False
    run_id: int | None = None


def replay_fixture_payloads(
    conn: psycopg.Connection,
    provider: FootballDataProvider,
    store: PayloadStore,
    *,
    apply: bool = False,
    since: datetime | None = None,
) -> ReplayReport:
    """Replay every indexed /fixtures payload, oldest first."""
    report = ReplayReport()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT hash, file_path, fetched_at FROM raw.ingestion_payloads "
            "WHERE endpoint = ANY(%s) AND http_status = 200 AND (%s::timestamptz IS NULL OR fetched_at >= %s) "
            "ORDER BY fetched_at, hash",
            (list(FIXTURE_ENDPOINTS), since, since),
        )
        rows = [(str(h), str(p), at) for h, p, at in cur.fetchall()]

    ledger = RunLedger(conn) if apply else None
    run_id = ledger.open("raw_replay", params={"endpoints": list(FIXTURE_ENDPOINTS)}) if ledger else None
    report.run_id = run_id
    counters = RunCounters()
    season_ids = tracked_season_ids(conn)
    try:
        for payload_hash, file_path, fetched_at in rows:
            report.payloads_considered += 1
            try:
                envelope = store.load(file_path)
            except (OSError, ValueError) as exc:
                report.payloads_refused.append(f"{payload_hash[:12]}: unreadable ({exc.__class__.__name__})")
                continue
            body = envelope.get("body")
            if not isinstance(body, dict) or body_hash(body) != payload_hash:
                # The file on disk is not the response that was indexed. Never
                # apply bytes whose provenance we cannot prove.
                report.payloads_refused.append(f"{payload_hash[:12]}: hash mismatch")
                continue
            outcome = apply_fixtures_payload(
                conn, provider, body,
                payload_hash=payload_hash, fetched_at=fetched_at, season_ids=season_ids,
            )
            report.payloads_applied += 1
            report.fixtures_inserted += outcome.fixtures_inserted
            report.fixtures_updated += outcome.fixtures_updated
            report.results_written += outcome.results_written
        counters.rows_inserted = report.fixtures_inserted
        counters.rows_updated = report.fixtures_updated + report.results_written
        counters.rows_normalized = report.payloads_applied
        counters.errors = list(report.payloads_refused)
        if apply:
            conn.commit()
            report.committed = True
        else:
            conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        if ledger is not None and run_id is not None:
            ledger.close(run_id, counters, notes=f"replayed {report.payloads_applied} payload(s), 0 requests")
    log.info(
        "replay.done", applied=report.payloads_applied, refused=len(report.payloads_refused),
        inserted=report.fixtures_inserted, updated=report.fixtures_updated,
        results=report.results_written, committed=report.committed,
    )
    return report
