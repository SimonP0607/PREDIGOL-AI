"""The job ledger. One row per run, opened before work and closed after.

Answers "what did the system do at 03:00?" without reading logs: the
scheduled instant, the actual start, the attempt number, the provider calls
spent, the payloads stored, the rows normalised/inserted/updated, the last
error, and how long it took.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

import psycopg
import structlog
from psycopg.pq import TransactionStatus
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
    def did_useful_work(self) -> bool:
        """Did anything durable come out of this run?

        Rows are the obvious answer, but a stored raw payload counts too: it is
        on disk, indexed in raw.ingestion_payloads, and a price can be
        normalised out of it later. A run that fetched and kept the bytes has
        made progress even if nothing was parsed from them yet.

        api_calls deliberately does NOT count. Spending quota is not work.
        """
        return bool(self.rows_inserted or self.rows_updated or self.payloads_stored)

    @property
    def status(self) -> str:
        """One of completed/partial/failed/aborted/interrupted - see the comment on
        raw.ingestion_runs.status, which this must agree with.

            its process stopped it (signal, shutdown, deadline)  -> interrupted
            a cap stopped it on purpose                          -> aborted
            no errors                                            -> completed
            errors + something durable                           -> partial
            errors + nothing durable                             -> failed

        ``partial`` exists because the old two-state rule called a fixtures
        sync with 7 refusals out of 9 requests 'completed', which reads as if
        nothing had gone wrong. An operator scanning statuses would never look
        at it. 'aborted' stays separate and orthogonal: it means a cap stopped
        the run on purpose, not that the run broke. 'interrupted' (since 5 Oct
        2026; 'aborted' before) is a run its process could not finish - a
        shutdown, Ctrl-C, a job deadline - which is neither a cap nor an error.
        """
        if self.stopped_early and self.stopped_early.startswith("interrupted"):
            return "interrupted"
        if self.stopped_early:
            return "aborted"
        if not self.errors:
            return "completed"
        return "partial" if self.did_useful_work else "failed"


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
        from fbi.ops.run_watchdog import process_identity, timeout_for

        owner = process_identity()
        started = now()
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO raw.ingestion_runs (job_name, job_type, params, scheduled_for, attempt, started_at, "
                "owner_host, owner_pid, owner_started, heartbeat_at, deadline_at) "
                "VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                # started_at from the application clock, not the database default:
                # one source of time, and the ledger stays testable under FrozenClock.
                (job_type, job_type, Json(params or {}), scheduled_for, attempt, started, owner.host, owner.pid,
                 owner.started, started, started + timeout_for(job_type)),
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
        from: market.odds_snapshots.payload_hash references this table.

        An ephemeral response (``RawResponse.persisted`` False: hashed, never written) has no file, and an index row
        for it would be a reference to nothing - the RAW integrity audit would call it missing. It is refused."""
        if not raws:
            return 0
        ephemeral = [r.endpoint for r in raws if not getattr(r, "persisted", True)]
        if ephemeral:
            raise ValueError(f"cannot index payloads that were never written to the RAW store: {ephemeral}")
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
            cur.execute("UPDATE raw.ingestion_runs SET heartbeat_at = %s WHERE id = %s", (now(), run_id))
        return len(raws)

    def beat(self, run_id: int) -> None:
        """A sign of life from a long loop that indexes no payload (fbi.ops.run_watchdog)."""
        with self._conn.cursor() as cur:
            cur.execute("UPDATE raw.ingestion_runs SET heartbeat_at = %s WHERE id = %s", (now(), run_id))
        self._conn.commit()

    def indexed_at(self, payload_hash: str) -> datetime | None:
        """The ``fetched_at`` the INDEX holds for a payload, which is not always the
        one the caller has.

        ``PayloadStore`` deduplicates identical bodies and the index keeps the first
        fetch, so a payload fetched twice leaves the caller holding the second time.
        Writing that later time onto the derived rows makes a row newer than its own
        payload - and made 1,809 fixtures' detail look absent, because replaying the
        indexed payload then reads as stale and the monotonic writers refuse it,
        correctly. Writers should use this instead of the response's own time.
        """
        with self._conn.cursor() as cur:
            cur.execute("SELECT fetched_at FROM raw.ingestion_payloads WHERE hash = %s", (payload_hash,))
            row = cur.fetchone()
        return row[0] if row and isinstance(row[0], datetime) else None

    def close(self, run_id: int, counters: RunCounters, *, notes: str | None = None) -> None:
        """Write the outcome. Called while an exception is propagating - the usual
        ``finally:`` close - the run records that exception, so a crash is never
        'completed' (on 25 Sep 2026 a Football-Data import whose download was reset
        closed as 'completed' with nothing done). An interrupt (KeyboardInterrupt,
        SystemExit, cancellation, a job deadline) is 'interrupted'. A run the watchdog
        had already closed as stale or interrupted gets its real outcome, with a note.
        An error the caller already recorded
        is not recorded twice. A transaction the failure left aborted is rolled back
        first, so the ledger row is still written instead of a second error hiding
        the first."""
        in_flight = sys.exc_info()[1]
        if in_flight is not None:
            _record_in_flight(counters, in_flight)
        if self._conn.info.transaction_status == TransactionStatus.INERROR:
            self._conn.rollback()
        last_error = counters.errors[-1] if counters.errors else counters.stopped_early
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE raw.ingestion_runs SET finished_at = %s, status = %s, api_calls = %s, "
                "payloads_stored = %s, rows_normalized = %s, rows_written = %s, rows_updated = %s, "
                "errors = %s, notes = %s, heartbeat_at = %s, "
                "last_error = CASE WHEN status IN ('stale', 'interrupted') "
                "  THEN concat_ws(' | ', last_error, %s::text, "
                "                 'closed by its job after the watchdog had marked it ' || status) "
                "  ELSE %s::text END "
                "WHERE id = %s",
                (
                    now(), counters.status, counters.api_calls, counters.payloads_stored,
                    counters.rows_normalized, counters.rows_inserted, counters.rows_updated,
                    len(counters.errors), notes, now(), last_error, last_error, run_id,
                ),
            )
        self._conn.commit()
        log.info(
            "run.closed", status=counters.status, api_calls=counters.api_calls,
            payloads=counters.payloads_stored, normalized=counters.rows_normalized,
            inserted=counters.rows_inserted, updated=counters.rows_updated, errors=len(counters.errors),
        )


def _record_in_flight(counters: RunCounters, exc: BaseException) -> None:
    """Fold an exception that is escaping the run into its counters."""
    if not isinstance(exc, Exception):
        from fbi.core.deadline import cancel_reason

        why = cancel_reason()
        counters.stopped_early = counters.stopped_early or (
            f"interrupted: {why}" if why else f"interrupted ({type(exc).__name__})")
        return
    key = str(exc)[:200] or type(exc).__name__
    if not any(key in e for e in counters.errors):
        counters.errors.append(f"{type(exc).__name__}: {exc}"[:500])
