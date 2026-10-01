"""The in-play capture use case. A pipeline of its own, start to finish.

    LIVE FIXTURE -> LIVE ODDS -> RAW PAYLOAD -> NORMALISATION
                 -> LIVE MARKET SNAPSHOT -> (LIVE MARKET MOVEMENT)

It shares the client, the quota ledger and the raw store with the pre-match
pipeline - those are infrastructure - and shares nothing else. It reads no
pre-match table and writes none. In particular it never touches
market.odds_snapshots, market.near_close_snapshots or market.market_consensus,
so no in-play price can reach the model or the backtest from here.

Nothing in this module decides a bet. It records what the in-play market said
and when, and that is all it is allowed to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
from fbi.odds.live_repository import LiveOddsRepository
from fbi.providers.api_football.live import (
    LiveFixtureState,
    LiveMarketSeen,
    LiveOddsQuote,
)
from fbi.providers.base import OddsParseLog, RawResponse
from fbi.quality.provider_signals import record_parse_log

log = structlog.get_logger(__name__)


class LiveOddsSource(Protocol):
    """All this service needs from a provider: one unfiltered in-play call.

    Narrow on purpose. A provider handed to this service cannot be asked for a
    pre-match price through this interface, so the two pipelines cannot be
    crossed by accident here either.
    """

    async def fetch_live_odds_all(
        self, *, parse_log: OddsParseLog | None = None
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
    """Read, compared against the last row for their key, and found identical.
    No row written, nothing lost: market.live_fixture_states records that the
    instant was observed, so the price is still answerable for it. Expected to
    be about three quarters of what arrives."""
    withdrawals_written: int = 0
    """Keys that stopped being quoted, recorded with a NULL price."""
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

        It changed a price (written), it matched the last one (unchanged), the
        row was already there (duplicate), or its fixture is not one we track
        (untracked). Nothing else can happen to a quote, which is what makes
        silent loss impossible to hide.

        The withdrawals are not in this sum on purpose: they are rows written
        for keys that were NOT in this payload, so they are not quotes that were
        read. quotes_written counts both, hence the subtraction.
        """
        priced = self.quotes_written - self.withdrawals_written
        return (
            self.quotes_seen
            == priced + self.quotes_unchanged + self.quotes_duplicate
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
    ) -> None:
        self._conn = conn
        self._provider = provider
        self._repo = LiveOddsRepository(conn)
        self._ledger = RunLedger(conn)
        self._budget = live_daily_budget
        self._floor = floor_seconds
        self._max_match_minutes = max_match_minutes

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

        report.payloads_stored = self._ledger.record_payloads(run_id, [raw])
        written = self._repo.write(states, quotes)
        report.quotes_written = written.quotes_written
        report.quotes_duplicate = written.quotes_duplicate
        report.states_written = written.states_written
        report.unknown_fixtures = written.unknown_fixtures
        report.quotes_untracked = written.quotes_untracked
        report.quotes_unchanged = written.quotes_unchanged
        report.withdrawals_written = written.withdrawals_written
        report.unmapped_rows = written.unmapped_markets_written
        report.markets_newly_catalogued = self._repo.record_live_markets(markets)

        # The catalogue was updated by the repository, with every bet observed -
        # not only the unmapped ones. What does NOT happen here is the other
        # half: an unmapped in-play bet is information, not a defect. 67 of the
        # 72 live bets have no market of ours, that is the documented design,
        # and unlike pre-match their prices ARE stored (market_key NULL), so the
        # pre-match wording "the prices are not stored" would be false.

        # What is left is genuinely anomalous, and goes in with the prices in the
        # same transaction. source='live' keeps these signals apart from
        # pre-match ones so a live-only quirk never reads as a pre-match
        # regression.
        signals = record_parse_log(
            self._conn,
            _anomalies_only(parse_log),
            source="live",
            payload_hash=raw.payload_hash,
            run_id=run_id,
        )
        report.quality_issues_opened = signals.issues_opened
        self._conn.commit()

        self._ledger.close(run_id, self._counters(report))
        log.info(
            "live_capture.finished",
            fixtures=report.fixtures_priced,
            quotes=report.quotes_seen,
            written=report.quotes_written,
            duplicate=report.quotes_duplicate,
            suspended=report.values_suspended,
            refused=report.refused,
            unmapped=report.unmapped_rows,
            untracked=report.quotes_untracked,
            unchanged=report.quotes_unchanged,
            withdrawn=report.withdrawals_written,
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
            rows_inserted=report.quotes_written + report.states_written,
            rows_updated=0,
            errors=list(report.errors),
        )
