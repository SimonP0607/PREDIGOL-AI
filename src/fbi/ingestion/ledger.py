"""The job ledger. One row per run, opened before work and closed after.

Answers "what did the system do at 03:00?" without reading logs: the
scheduled instant, the actual start, the attempt number, the provider calls
spent, the payloads stored, the rows normalised/inserted/updated, the last
error, and how long it took.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

import psycopg
import structlog
from psycopg.types.json import Json

from fbi.core.clock import now
from fbi.core.logging import bind_run_id
from fbi.providers.base import RawResponse

log = structlog.get_logger(__name__)


@dataclass
class RunCounters:
    api_calls: int = 0
    payloads_stored: int = 0
    rows_normalized: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    errors: list[str] = field(default_factory=list)
    stopped_early: str | None = None

    @property
    def status(self) -> str:
        if self.stopped_early:
            return "aborted"
        return "failed" if self.errors and not self.rows_inserted and not self.rows_updated else "completed"


class RunLedger:
    def __init__(self, conn: psycopg.Connection) -> None:
        self._conn = conn

    def open(
        self,
        job_type: str,
        *,
        params: dict[str, object] | None = None,
        scheduled_for: datetime | None = None,
        attempt: int = 1,
    ) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO raw.ingestion_runs (job_name, job_type, params, scheduled_for, attempt) "
                "VALUES (%s, %s, %s::jsonb, %s, %s) RETURNING id",
                (job_type, job_type, Json(params or {}), scheduled_for, attempt),
            )
            row = cur.fetchone()
            assert row is not None
            run_id: int = row[0]
        self._conn.commit()
        bind_run_id(str(run_id))
        log.info("run.opened", job_type=job_type, attempt=attempt, scheduled_for=scheduled_for)
        return run_id

    def record_payloads(self, run_id: int, raws: Sequence[RawResponse], *, provider: str = "api_football") -> int:
        """Index the raw files. A price cannot exist without the bytes it came
        from: market.odds_snapshots.payload_hash references this table."""
        if not raws:
            return 0
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO raw.ingestion_payloads "
                "(hash,run_id,provider,endpoint,params,fetched_at,http_status,results_count,file_path,bytes) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s) ON CONFLICT (hash) DO NOTHING",
                [
                    (r.payload_hash, run_id, provider, r.endpoint, Json(r.params), r.fetched_at,
                     r.http_status, r.results_count, r.file_path, r.bytes_written)
                    for r in raws
                ],
                returning=False,
            )
        return len(raws)

    def close(self, run_id: int, counters: RunCounters, *, notes: str | None = None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE raw.ingestion_runs SET finished_at = %s, status = %s, api_calls = %s, "
                "payloads_stored = %s, rows_normalized = %s, rows_written = %s, rows_updated = %s, "
                "errors = %s, last_error = %s, notes = %s WHERE id = %s",
                (
                    now(), counters.status, counters.api_calls, counters.payloads_stored,
                    counters.rows_normalized, counters.rows_inserted, counters.rows_updated,
                    len(counters.errors), (counters.errors[-1] if counters.errors else counters.stopped_early),
                    notes, run_id,
                ),
            )
        self._conn.commit()
        log.info(
            "run.closed", status=counters.status, api_calls=counters.api_calls,
            payloads=counters.payloads_stored, normalized=counters.rows_normalized,
            inserted=counters.rows_inserted, updated=counters.rows_updated, errors=len(counters.errors),
        )
