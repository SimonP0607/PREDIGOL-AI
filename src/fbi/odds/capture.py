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

from fbi.core.clock import now
from fbi.core.errors import CircuitOpenError, ProviderError, QuotaExhaustedError
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.market.consensus import recompute_from_snapshots
from fbi.odds.repository import OddsRepository
from fbi.odds.schedule import CapturePlanner, CaptureTask, ScheduledFixture
from fbi.providers.base import (
    FootballDataProvider,
    OddsParseLog,
    OddsQuote,
    OddsSource,
    RawResponse,
)
from fbi.quality.provider_signals import record_parse_log

log = structlog.get_logger(__name__)


@dataclass
class CaptureReport:
    run_id: int
    planned: int = 0
    executed: int = 0
    quotes_seen: int = 0
    snapshots_written: int = 0
    duplicates_skipped: int = 0
    near_close_written: int = 0
    consensus_written: int = 0
    api_calls: int = 0
    payloads_stored: int = 0
    quality_issues_opened: int = 0
    quality_issues_seen_again: int = 0
    provider_bets_newly_observed: int = 0
    """Bets that appeared in a payload and were not in the catalogue: a provider
    change, recorded rather than skipped."""
    errors: list[str] = field(default_factory=list)
    stopped_early: str | None = None

    @property
    def status(self) -> str:
        if self.stopped_early:
            return "aborted"
        return "failed" if self.errors and not self.executed else "completed"

    @property
    def counters(self) -> RunCounters:
        return RunCounters(
            api_calls=self.api_calls,
            payloads_stored=self.payloads_stored,
            rows_normalized=self.quotes_seen,
            rows_inserted=self.snapshots_written,
            rows_updated=self.near_close_written,
            errors=list(self.errors),
            stopped_early=self.stopped_early,
        )


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
        self._ledger = RunLedger(conn)
        self._raw_root = raw_root
        self._lookback = timedelta(hours=lookback_hours)

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

        run_id = self._ledger.open(
            "odds_capture",
            params={
                "planned": len(tasks),
                "fixtures": len(fixtures),
                "skipped_already_captured": len(already_done),
            },
            scheduled_for=moment,
        )
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

        self._ledger.close(run_id, report.counters, notes=report.stopped_early)
        log.info(
            "capture.finished",
            executed=report.executed,
            written=report.snapshots_written,
            near_close=report.near_close_written,
            consensus=report.consensus_written,
            api_calls=report.api_calls,
            errors=len(report.errors),
            quality_issues=report.quality_issues_opened,
            new_provider_bets=report.provider_bets_newly_observed,
            status=report.status,
        )
        return report

    async def _capture_one(self, task: CaptureTask, report: CaptureReport) -> None:
        quotes: list[OddsQuote]
        raws: list[RawResponse]
        parse_log = OddsParseLog()
        source: OddsSource = "prematch"

        if task.kind == "near_close":
            # This service writes market.odds_snapshots, which the model and the
            # backtest read as PRE-MATCH prices. It used to serve a near_close
            # task from /odds/live - and /odds/live was then measured to return
            # only matches already in play, so those rows would have been in-play
            # prices filed as pre-match. The planner no longer emits this kind;
            # if one ever arrives, it fails here rather than mixing the series.
            raise ValueError(
                "near_close tasks are not served by the pre-match capture: "
                "/odds/live returns in-play prices and they belong in "
                "market.live_odds_snapshots. See LiveCaptureService."
            )

        quotes, raws = await self._provider.fetch_prematch_odds(
            provider_fixture_id=task.provider_fixture_id, kickoff_at=task.kickoff_at,
            parse_log=parse_log,
        )

        report.executed += 1
        report.api_calls += len(raws)
        report.quotes_seen += len(quotes)

        report.payloads_stored += self._ledger.record_payloads(report.run_id, raws)
        written = self._repo.write_snapshots(quotes)
        report.snapshots_written += written.written
        report.duplicates_skipped += written.skipped_existing


        # What the boundary refused is part of this capture, not a footnote: the
        # unmapped bets, the renames and the unreadable values go in with the
        # prices, in the same transaction.
        signals = record_parse_log(self._conn, parse_log, source=source,
                                   payload_hash=raws[-1].payload_hash if raws else None,
                                   run_id=report.run_id)
        report.quality_issues_opened += signals.issues_opened
        report.quality_issues_seen_again += signals.issues_seen_again
        report.provider_bets_newly_observed += signals.bets_newly_observed
        self._conn.commit()

        # The consensus is derived data: if computing it fails, the prices are
        # already committed and the failure is recorded, not hidden.
        try:
            for fixture_id in self._repo.fixture_ids_of(quotes):
                report.consensus_written += recompute_from_snapshots(self._conn, fixture_ids=[fixture_id])[1]
            self._conn.commit()
        except Exception as exc:  # derived data must never cost the capture
            self._conn.rollback()
            report.errors.append(f"{task.window_key}: consensus not computed: {type(exc).__name__}: {exc}")
            log.error("capture.consensus_failed", window=task.window_key, error=str(exc))

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
