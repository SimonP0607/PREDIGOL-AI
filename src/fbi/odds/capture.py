"""The odds capture use case.

fetch -> store raw -> normalise -> persist, with a run row wrapped around it so
every price in the database can be traced to the run, the call and the exact
bytes that produced it.

Nothing here decides anything about betting. It records what the market said,
and when, as faithfully as the provider allows.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import psycopg
import structlog
from psycopg.types.json import Json

from fbi.core.clock import now
from fbi.core.errors import CircuitOpenError, ProviderError, QuotaExhaustedError
from fbi.core.logging import bind_run_id
from fbi.odds.repository import OddsRepository
from fbi.odds.schedule import CapturePlanner, CaptureTask, ScheduledFixture
from fbi.providers.base import FootballDataProvider, OddsQuote, RawResponse

log = structlog.get_logger(__name__)


@dataclass
class CaptureReport:
    run_id: int
    planned: int = 0
    executed: int = 0
    quotes_seen: int = 0
    snapshots_written: int = 0
    near_close_written: int = 0
    api_calls: int = 0
    errors: list[str] = field(default_factory=list)
    stopped_early: str | None = None

    @property
    def status(self) -> str:
        if self.stopped_early:
            return "aborted"
        return "failed" if self.errors and not self.executed else "completed"


class OddsCaptureService:
    def __init__(
        self,
        conn: psycopg.Connection,
        provider: FootballDataProvider,
        planner: CapturePlanner,
        *,
        raw_root: str = "data/raw",
        lookback_hours: int = 24,
    ) -> None:
        self._conn = conn
        self._provider = provider
        self._planner = planner
        self._repo = OddsRepository(conn)
        self._raw_root = raw_root
        self._lookback = timedelta(hours=lookback_hours)

    # ── run bookkeeping ──────────────────────────────────────────────────────
    def _open_run(self, job_name: str, params: dict[str, object]) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO raw.ingestion_runs (job_name, params) VALUES (%s, %s::jsonb) RETURNING id",
                (job_name, Json(params)),
            )
            row = cur.fetchone()
            assert row is not None
            run_id: int = row[0]
        self._conn.commit()
        return run_id

    def _close_run(self, report: CaptureReport) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE raw.ingestion_runs SET finished_at = %s, status = %s, api_calls = %s, "
                "rows_written = %s, errors = %s, notes = %s WHERE id = %s",
                (
                    now(),
                    report.status,
                    report.api_calls,
                    report.snapshots_written,
                    len(report.errors),
                    report.stopped_early,
                    report.run_id,
                ),
            )
        self._conn.commit()

    def _record_payloads(self, run_id: int, raws: Sequence[RawResponse]) -> None:
        """Index the raw files. The FK from odds_snapshots.payload_hash means a
        price cannot exist without the bytes it came from."""
        if not raws:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO raw.ingestion_payloads "
                "(hash,run_id,provider,endpoint,params,fetched_at,http_status,results_count,file_path,bytes) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s) ON CONFLICT (hash) DO NOTHING",
                [
                    (
                        r.payload_hash,
                        run_id,
                        "api_football",
                        r.endpoint,
                        Json(r.params),  # already sanitized
                        r.fetched_at,
                        r.http_status,
                        r.results_count,
                        r.file_path,
                        r.bytes_written,
                    )
                    for r in raws
                ],
                returning=False,
            )

    # ── the capture itself ───────────────────────────────────────────────────
    async def capture(
        self, fixtures: Sequence[ScheduledFixture], *, at: datetime | None = None
    ) -> CaptureReport:
        moment = at or now()
        observations = self._repo.observations_since(
            since=moment - self._lookback,
            provider_fixture_ids=[f.provider_fixture_id for f in fixtures],
        )
        already_done = self._planner.covered_keys(observations)
        tasks = self._planner.plan(fixtures, at=moment, already_done=already_done)

        run_id = self._open_run(
            "odds_capture",
            {
                "planned": len(tasks),
                "fixtures": len(fixtures),
                "skipped_already_captured": len(already_done),
            },
        )
        bind_run_id(str(run_id))
        report = CaptureReport(run_id=run_id, planned=len(tasks))
        log.info(
            "capture.planned",
            tasks=len(tasks),
            fixtures=len(fixtures),
            already_captured=len(already_done),
        )

        for task in tasks:
            try:
                await self._capture_one(task, report)
            except QuotaExhaustedError as exc:
                report.stopped_early = str(exc)
                log.warning("capture.quota_exhausted", detail=str(exc))
                break
            except CircuitOpenError as exc:
                report.stopped_early = str(exc)
                log.warning("capture.circuit_open", detail=str(exc))
                break
            except ProviderError as exc:
                report.errors.append(f"{task.window_key}: {exc}")
                log.warning("capture.task_failed", window=task.window_key, error=str(exc))

        self._close_run(report)
        log.info(
            "capture.finished",
            executed=report.executed,
            written=report.snapshots_written,
            near_close=report.near_close_written,
            api_calls=report.api_calls,
            errors=len(report.errors),
            status=report.status,
        )
        return report

    async def _capture_one(self, task: CaptureTask, report: CaptureReport) -> None:
        quotes: list[OddsQuote]
        raws: list[RawResponse]

        if task.kind == "near_close":
            quotes, raw = await self._provider.fetch_live_odds(
                provider_fixture_id=task.provider_fixture_id, kickoff_at=task.kickoff_at
            )
            raws = [raw]
        else:
            quotes, raws = await self._provider.fetch_prematch_odds(
                provider_fixture_id=task.provider_fixture_id, kickoff_at=task.kickoff_at
            )

        report.executed += 1
        report.api_calls += len(raws)
        report.quotes_seen += len(quotes)

        self._record_payloads(report.run_id, raws)
        written = self._repo.write_snapshots(quotes)
        report.snapshots_written += written.written

        if task.kind == "near_close":
            report.near_close_written += self._repo.upsert_near_close(quotes)
        self._conn.commit()

        log.info(
            "capture.task_done",
            window=task.window_key,
            minutes_to_ko=task.minutes_to_ko,
            quotes=len(quotes),
            written=written.written,
            duplicates=written.skipped_existing,
        )


async def gather_bounded(coros: Sequence[object], limit: int) -> list[object]:
    """Run coroutines with a hard concurrency ceiling."""
    semaphore = asyncio.Semaphore(limit)

    async def _run(coro: object) -> object:
        async with semaphore:
            return await coro  # type: ignore[misc]

    return await asyncio.gather(*(_run(c) for c in coros))
