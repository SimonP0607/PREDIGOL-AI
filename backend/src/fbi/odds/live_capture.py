"""The in-play capture use case. A pipeline of its own, start to finish.

    LIVE FIXTURE -> LIVE ODDS -> NORMALISATION -> THE BOOK AS IT STANDS NOW
                    (market.live_fixture_current, market.live_odds_current)

It shares the client and the quota ledger with the pre-match pipeline - those are infrastructure - and shares
nothing else. It reads no pre-match table and writes none. In particular it never touches market.odds_snapshots,
market.final_prematch_odds, market.near_close_snapshots or market.market_consensus, so no in-play price can reach
a model, a pick or the backtest from here.

EPHEMERAL SINCE REVISION 0068 (owner's decision, 6 Oct 2026)
------------------------------------------------------------
Only the present of the in-play book is kept: the price each key is quoted at now, with the one it replaced. A
withdrawn key is deleted, a fixture that left the live book is purged (``live_repository.STALE_AFTER``), and the
/odds/live body is hashed but not written to the RAW store - it is evidence of nothing that is stored. It IS
written, and indexed, when the parse found an anomaly worth an incident (a renamed bet, a price refused for a
reason other than a normal suspension): the quality issue then points to the bytes that raised it.

Nothing in this module decides a bet. It shows what the in-play market says now, and that is all it is allowed
to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Protocol

import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.core.errors import CircuitOpenError, ProviderError, QuotaExhaustedError
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.odds.live_cadence import (
    DEFAULT_LIVE_DAILY_BUDGET,
    MAX_MATCH_MINUTES,
    POLL_FLOOR_SECONDS,
    CadenceDecision,
    decide,
)
from fbi.odds.live_repository import LiveOddsRepository, PurgeResult
from fbi.providers.api_football.live import (
    LiveFixtureState,
    LiveMarketSeen,
    LiveOddsQuote,
)
from fbi.providers.base import OddsParseLog, RawResponse
from fbi.quality.issues import IssueRegistry
from fbi.quality.provider_signals import issues_from_parse_log
from fbi.storage.payload_store import PayloadStore

log = structlog.get_logger(__name__)


class LiveOddsSource(Protocol):
    """All this service needs from a provider: one unfiltered in-play call.

    Narrow on purpose. A provider handed to this service cannot be asked for a
    pre-match price through this interface, so the two pipelines cannot be
    crossed by accident here either.
    """

    async def fetch_live_odds_all(
        self, *, parse_log: OddsParseLog | None = None, persist_raw: bool = False
    ) -> tuple[
        list[LiveFixtureState], list[LiveOddsQuote], list[LiveMarketSeen], RawResponse
    ]: ...


EXPECTED_LIVE_REFUSALS = frozenset({"suspended with no price"})
"""Reasons that describe the in-play market working normally. 56 of the 57
values refused on the probe payload were ``"odd": "0"`` on a suspended value -
the provider declining to quote, already counted in the fixture state's
values_suspended. Recording those as quality issues would open tens of
thousands of rows a day that mean nothing, and bury the ones that do."""


def _anomalies_only(parse_log: OddsParseLog) -> OddsParseLog:
    """The parse log with expected in-play behaviour removed.

    Keeps renames (a provider catalogue change) and refusals that signal a real
    problem - a price out of range, a selection a mapped market does not have.
    Drops the unmapped bets, which go to the catalogue instead, and the
    suspended-with-no-price refusals, which are the market's normal state.
    """
    trimmed = OddsParseLog()
    trimmed.renamed_bets = list(parse_log.renamed_bets)
    kept = [r for r in parse_log.rejected if r[2] not in EXPECTED_LIVE_REFUSALS]
    trimmed.rejected = kept
    # rejected_total counts what this log reports on, so it matches what was kept.
    trimmed.rejected_total = len(kept)
    return trimmed


@dataclass
class LiveCaptureReport:
    run_id: int | None = None
    captured: bool = False
    skipped_reason: str | None = None
    next_in_seconds: int = POLL_FLOOR_SECONDS
    fixtures_possibly_live: int = 0
    fixtures_priced: int = 0
    api_calls: int = 0
    payloads_stored: int = 0
    quotes_seen: int = 0
    quotes_written: int = 0
    quotes_duplicate: int = 0
    states_written: int = 0
    unknown_fixtures: int = 0
    quotes_untracked: int = 0
    quotes_unchanged: int = 0
    """Read, compared against what the book holds for their key, and found identical: nothing written.
    About three quarters of what arrives."""
    withdrawals_written: int = 0
    """Keys a fixture of this tick stopped quoting: deleted from the book."""
    quotes_inserted: int = 0
    quotes_updated: int = 0
    book_fixtures: int = 0
    """Fixtures in the in-play book after this tick - bounded by what is in play, never a history."""
    book_quotes: int = 0
    """Prices in the in-play book after this tick."""
    purged_fixtures: int = 0
    purged_quotes: int = 0
    raw_kept: bool = False
    """Whether this tick's /odds/live body was written to the RAW store: only as evidence of an anomaly."""
    unmapped_rows: int = 0
    markets_observed: int = 0
    markets_newly_catalogued: int = 0
    values_suspended: int = 0
    refused: int = 0
    quality_issues_opened: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def accounting_holds(self) -> bool:
        """Every quote read is accounted for, in one of four ways.

        It changed the book (written: inserted or updated), it matched what the book held (unchanged), this
        payload had already quoted its key (duplicate), or its fixture is not one we track (untracked). Nothing
        else can happen to a quote, which is what makes silent loss impossible to hide.

        The withdrawals are not in this sum on purpose: they are keys that were NOT in this payload.
        """
        return (
            self.quotes_seen
            == self.quotes_written + self.quotes_unchanged + self.quotes_duplicate
            + self.quotes_untracked
        )

    @property
    def status(self) -> str:
        if self.errors:
            return "errors"
        if not self.captured:
            return "skipped"
        return "ok"


class LiveCaptureService:
    """One tick of in-play capture.

    The tick is deliberately cheap to decide and cheap to skip: the cadence is
    settled from the database before any request is made, so a quiet night costs
    nothing at all.
    """

    def __init__(
        self,
        conn: psycopg.Connection,
        provider: LiveOddsSource,
        *,
        live_daily_budget: int = DEFAULT_LIVE_DAILY_BUDGET,
        floor_seconds: int = POLL_FLOOR_SECONDS,
        max_match_minutes: int = MAX_MATCH_MINUTES,
        raw_store: PayloadStore | None = None,
    ) -> None:
        self._conn = conn
        self._provider = provider
        self._repo = LiveOddsRepository(conn)
        self._ledger = RunLedger(conn)
        self._budget = live_daily_budget
        self._floor = floor_seconds
        self._max_match_minutes = max_match_minutes
        self._raw_store = raw_store

    def purge_stale(self, *, at: datetime | None = None) -> PurgeResult:
        """Drop what left the live book, and commit. No request: safe on every wake-up, played or not."""
        result = self._repo.purge_stale(at=at)
        self._conn.commit()
        return result

    def _record_anomalies(self, anomalies: OddsParseLog, raw: RawResponse, run_id: int,
                          report: LiveCaptureReport) -> None:
        """Record what the parse refused for a real reason - keeping the body only when it is new evidence.

        An issue's fingerprint does not include its payload, so the same anomaly on the next tick is the same issue
        seen again: it needs no new bytes, and its row keeps pointing to the payload that first showed it. A body
        is written to the RAW store, and indexed, only when this tick opens an issue nobody has recorded yet - so a
        quirk the provider repeats every 30 s costs one payload, not one per tick.
        """
        issues = issues_from_parse_log(anomalies, source="live", run_id=run_id)
        if not issues:
            return
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT fingerprint, payload_hash FROM audit.data_quality_issues WHERE fingerprint = ANY(%s)",
                        ([i.fingerprint for i in issues],))
            known: dict[str, str | None] = {str(f): (None if h is None else str(h)) for f, h in cur.fetchall()}
        kept_hash: str | None = None
        if any(i.fingerprint not in known for i in issues):
            kept = self._keep(raw)
            report.payloads_stored = self._ledger.record_payloads(run_id, [kept])
            report.raw_kept = True
            kept_hash = kept.payload_hash
        # Each issue names the evidence it already has, or the body kept now: a seen-again issue is not re-pointed
        # at bytes that were never written.
        final = [replace(i, payload_hash=known.get(i.fingerprint) or kept_hash) for i in issues]
        result = IssueRegistry(self._conn).record_many(final)
        report.quality_issues_opened = result.opened

    def _keep(self, raw: RawResponse) -> RawResponse:
        """Write an in-play body to the RAW store after all - it is evidence of an anomaly - and return it as a
        persisted response the ledger can index. Same body, so the same hash and the same path."""
        if raw.persisted:
            return raw
        if self._raw_store is None:
            from fbi.core.config import settings

            self._raw_store = PayloadStore(settings.runtime.raw_store_dir)
        stored = self._raw_store.store(endpoint=raw.endpoint, params=raw.params, fetched_at=raw.fetched_at,
                                       http_status=raw.http_status, body=raw.body)
        return replace(raw, file_path=stored.file_path, bytes_written=stored.bytes_written, persisted=True)

    # -- cadence -------------------------------------------------------------

    def plan(self, *, at: datetime | None = None, remaining_quota: int) -> CadenceDecision:
        moment = at or now()
        return decide(
            kickoffs=self._kickoffs(at=moment),
            at=moment,
            live_calls_today=self._live_calls_today(),
            live_daily_budget=self._budget,
            remaining_quota=remaining_quota,
            last_capture_at=self._last_capture_at(),
            floor_seconds=self._floor,
            max_match_minutes=self._max_match_minutes,
        )

    def _kickoffs(self, *, at: datetime) -> list[datetime]:
        """Kick-off times that could bear on today's live capture.

        Every tracked fixture from one match-length ago to the end of the day,
        whatever its stored status: a fixture still marked 'scheduled' while it
        is actually being played is exactly the case that must not be missed.
        """
        start = at - timedelta(minutes=self._max_match_minutes)
        end = at + timedelta(hours=24)
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT f.kickoff_at FROM core.fixtures f "
                "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
                "JOIN core.competitions c ON c.id = cs.competition_id "
                "WHERE c.is_tracked AND f.kickoff_at BETWEEN %s AND %s "
                "  AND f.status_group <> 'finished'",
                (start, end),
            )
            return [r[0] for r in cur.fetchall()]

    def _last_capture_at(self) -> datetime | None:
        """When /odds/live was last asked, from the payload ledger.

        Not an in-memory timestamp: a worker restart would reset that and the
        cadence would double-spend for one cycle. ``indexed_at`` is the FIRST
        time a body was fetched, and the live book changes every cycle, so a
        repeated payload still records its own fetch - except when the bytes
        are identical, which is exactly the call that should not have happened.
        ``raw.ingestion_runs`` is the reliable record of attempts.
        """
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT max(started_at) FROM raw.ingestion_runs "
                "WHERE job_type = 'live_odds_capture'"
            )
            row = cur.fetchone()
            return row[0] if row and row[0] else None

    def _live_calls_today(self) -> int:
        # Counted from the runs, not the payloads: an identical body is deduped
        # in raw.ingestion_payloads but the REQUEST was still spent, and it is
        # requests the budget protects.
        with self._conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT count(*) FROM raw.ingestion_runs "
                "WHERE job_type = 'live_odds_capture' "
                "  AND started_at >= date_trunc('day', now())"
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    # -- the tick ------------------------------------------------------------

    async def capture(
        self, *, at: datetime | None = None, remaining_quota: int
    ) -> LiveCaptureReport:
        decision = self.plan(at=at, remaining_quota=remaining_quota)
        report = LiveCaptureReport(
            next_in_seconds=decision.next_in_seconds,
            fixtures_possibly_live=decision.fixtures_possibly_live,
        )
        if not decision.should_capture:
            report.skipped_reason = decision.reason
            purged = self.purge_stale(at=at)
            report.purged_fixtures, report.purged_quotes = purged.fixtures, purged.quotes
            log.info(
                "live_capture.skipped",
                reason=decision.reason,
                next_in_seconds=decision.next_in_seconds,
            )
            return report

        run_id = self._ledger.open(
            "live_odds_capture",
            params={
                "interval_seconds": decision.next_in_seconds,
                "fixtures_possibly_live": decision.fixtures_possibly_live,
            },
        )
        report.run_id = run_id
        parse_log = OddsParseLog()

        try:
            states, quotes, markets, raw = await self._provider.fetch_live_odds_all(
                parse_log=parse_log
            )
        except (QuotaExhaustedError, CircuitOpenError, ProviderError) as exc:
            report.errors.append(str(exc))
            self._ledger.close(run_id, self._counters(report), notes=str(exc))
            log.warning("live_capture.fetch_failed", error=str(exc))
            return report

        report.captured = True
        report.api_calls = 1
        report.fixtures_priced = len(states)
        report.quotes_seen = len(quotes)
        report.markets_observed = len(markets)
        report.values_suspended = sum(s.values_suspended for s in states)
        report.refused = parse_log.rejected_total

        written = self._repo.write(states, quotes)
        report.quotes_written = written.quotes_written
        report.quotes_inserted = written.quotes_inserted
        report.quotes_updated = written.quotes_updated
        report.quotes_duplicate = written.quotes_duplicate
        report.states_written = written.states_written
        report.unknown_fixtures = written.unknown_fixtures
        report.quotes_untracked = written.quotes_untracked
        report.quotes_unchanged = written.quotes_unchanged
        report.withdrawals_written = written.withdrawals_written
        report.unmapped_rows = written.unmapped_markets_written
        report.markets_newly_catalogued = self._repo.record_live_markets(markets)
        purged = self._repo.purge_stale(at=at)
        report.purged_fixtures, report.purged_quotes = purged.fixtures, purged.quotes
        report.book_fixtures, report.book_quotes = self._repo.book_size()

        # An unmapped in-play bet is information, not a defect: 140 of the 145 in-play markets seen have no market
        # of ours, by design. What is left after _anomalies_only is genuinely anomalous. source='live' keeps these
        # signals apart from pre-match ones so a live-only quirk never reads as a pre-match regression.
        self._record_anomalies(_anomalies_only(parse_log), raw, run_id, report)
        self._conn.commit()

        self._ledger.close(run_id, self._counters(report))
        log.info(
            "live_capture.finished",
            fixtures=report.fixtures_priced,
            quotes=report.quotes_seen,
            written=report.quotes_written,
            inserted=report.quotes_inserted,
            updated=report.quotes_updated,
            duplicate=report.quotes_duplicate,
            suspended=report.values_suspended,
            refused=report.refused,
            unmapped=report.unmapped_rows,
            untracked=report.quotes_untracked,
            unchanged=report.quotes_unchanged,
            withdrawn=report.withdrawals_written,
            book_fixtures=report.book_fixtures,
            book_quotes=report.book_quotes,
            purged_fixtures=report.purged_fixtures,
            raw_kept=report.raw_kept,
            accounting_holds=report.accounting_holds,
            next_in_seconds=report.next_in_seconds,
        )
        if not report.accounting_holds:
            log.error(
                "live_capture.accounting_broken",
                seen=report.quotes_seen,
                written=report.quotes_written,
                unchanged=report.quotes_unchanged,
                withdrawn=report.withdrawals_written,
                duplicate=report.quotes_duplicate,
                untracked=report.quotes_untracked,
                detail="quotes seen do not add up; a price may have been lost",
            )
        return report

    def _counters(self, report: LiveCaptureReport) -> RunCounters:
        return RunCounters(
            api_calls=report.api_calls,
            payloads_stored=report.payloads_stored,
            rows_normalized=report.quotes_seen,
            rows_inserted=report.quotes_inserted,
            rows_updated=report.quotes_updated + report.states_written,
            errors=list(report.errors),
        )
