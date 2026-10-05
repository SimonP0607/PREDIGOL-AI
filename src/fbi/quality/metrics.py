"""Data quality foundation: the numbers behind the P0 Data Quality screen.

Every metric is computed from what is actually stored - the fixtures table,
the odds series, the ledger - never from a counter somebody increments. A
metric that cannot be computed says so with a null, the same rule the schema
applies to ROI.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.core.clock import now
from fbi.providers.quota import read_usage

STALE_CAPTURE_AFTER = timedelta(hours=4)
"""Kept for the per-competition coverage table. The snapshot's stale count is window-aware since 5 Oct 2026: a
fixture three days out is captured at T-72 h and next at T-48 h, so a 20-hour-old price is on schedule, not stale
- the old 4-hour rule called 40 of 73 priced fixtures stale while every due window had been captured."""

DEFAULT_WINDOWS = (4320, 2880, 1440, 720, 360, 180)
"""Minutes before kick-off (``settings.odds.prematch_windows``); the callers pass the configured ones."""

FINAL_PREMATCH_DAYS = 7
"""The provider keeps pre-match odds this long after a match (``fbi.odds.final_prematch``)."""

CAPTURE_STATES = ("not_due", "current", "stale", "missed", "provider_unpriced")


def capture_state(kickoff: datetime, last_capture: datetime | None, last_asked: datetime | None, mapped: bool, *,
                  at: datetime, windows: Sequence[int], tolerance_minutes: int) -> str:
    """Where an upcoming fixture stands against its capture windows.

    A window W is due while ``W - tolerance <= minutes to kick-off <= W`` (``fbi.odds.schedule``); once its band has
    closed, the fixture must hold a price taken at or after ``kickoff - W`` (in the band, or by the catch-up):

    * ``not_due``           - no window has closed yet;
    * ``current``           - a price at or after the opening of the most recent closed window;
    * ``provider_unpriced`` - asked since that window opened and nothing came back, or never listed as priced and
                              never priced: the provider has no price, not a capture we skipped;
    * ``stale``             - an older price, and /odds not asked since: ours;
    * ``missed``            - no price at all, listed as priced, not asked since: ours.
    """
    minutes = (kickoff - at).total_seconds() / 60.0
    closed = [w for w in windows if minutes < w - tolerance_minutes]
    if not closed:
        return "not_due"
    opened = kickoff - timedelta(minutes=min(closed))
    if last_capture is not None and last_capture >= opened:
        return "current"
    if (last_asked is not None and last_asked >= opened) or (not mapped and last_capture is None):
        return "provider_unpriced"
    return "stale" if last_capture is not None else "missed"


@dataclass(frozen=True, slots=True)
class CoverageMetric:
    expected: int
    available: int

    @property
    def ratio(self) -> float | None:
        return None if self.expected == 0 else round(self.available / self.expected, 4)


PROVIDER_ERROR_PATTERN = (r"provider|http|rate ?limit|connect|timed? ?out|read ?error|\y429\y|\y5[0-9]{2}\y|quota|"
                          r"circuit|ssl|dns|remote ?protocol")
"""A run's last error that came from talking to the provider (a Postgres regex, case-insensitive; ``y`` escapes are
word bounds there)."""
NOT_PROVIDER_ERROR_PATTERN = (r"QueryCanceled|statement timeout|Violation|psycopg|IntegrityError|OperationalError|"
                              r"run cap|request cap|allowance|job deadline|watchdog")
"""...unless it is a database error, a planned cap or a deadline: 5 Oct 2026, a truth audit's statement timeout
(a run that had also made 370 provider requests) put the provider at "degraded" for an hour."""
PROVIDER_ERROR_SQL = "(last_error ~* %(provider_error)s AND last_error !~* %(not_provider_error)s)"
PROVIDER_ERROR_PARAMS = {"provider_error": PROVIDER_ERROR_PATTERN, "not_provider_error": NOT_PROVIDER_ERROR_PATTERN}


def is_provider_error(text: str | None) -> bool:
    """The same judgement as PROVIDER_ERROR_SQL, in Python (Postgres word bounds become Python ones)."""
    import re

    if not text:
        return False
    provider = PROVIDER_ERROR_PATTERN.replace(r"\y", r"\b")
    return bool(re.search(provider, text, re.IGNORECASE)) and not re.search(NOT_PROVIDER_ERROR_PATTERN, text,
                                                                          re.IGNORECASE)


STUCK_RUNS_SQL = """
SELECT count(*) FROM raw.ingestion_runs
 WHERE status = 'running' AND (deadline_at < %s OR (deadline_at IS NULL AND started_at < %s))
"""
"""Open past their deadline (fbi.ops.run_watchdog), or, for a run opened before 0062, for over two hours. A
long backfill inside its deadline is working, not stuck."""


CAPTURE_STATE_SQL = """
SELECT f.kickoff_at,
       (SELECT max(o.captured_at) FROM market.odds_snapshots o WHERE o.fixture_id = f.id AND o.source = 'prematch')
           AS last_capture,
       (SELECT max(p.fetched_at) FROM raw.ingestion_payloads p
         WHERE p.endpoint = '/odds' AND p.params ? 'fixture' AND p.params->>'fixture' = f.provider_fixture_id::text
           AND p.fetched_at > f.kickoff_at - interval '8 days') AS last_asked,
       EXISTS (SELECT 1 FROM market.odds_mapping_seen m WHERE m.provider_fixture_id = f.provider_fixture_id) AS mapped
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %s AND %s
"""

FINAL_PREMATCH_SQL = """
WITH fin AS (
    SELECT f.id FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
     WHERE c.is_tracked AND f.status_group = 'finished' AND f.kickoff_at BETWEEN %(since)s AND %(at)s
)
SELECT count(*),
       count(k.fixture_id),
       count(*) FILTER (WHERE k.outcome = 'priced'),
       count(*) FILTER (WHERE k.outcome = 'empty'),
       count(*) FILTER (WHERE k.outcome = 'after_kickoff'),
       (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY o.minutes_to_ko)
          FROM market.final_prematch_odds o WHERE o.fixture_id IN (SELECT id FROM fin))
  FROM fin LEFT JOIN market.final_prematch_checks k ON k.fixture_id = fin.id
"""
"""The provider's last pre-match price, read after the match (``fbi.odds.final_prematch``): the near-closing line
this provider can give. /odds/live serves fixtures in play only (measured 1 Oct 2026), so the T-12 near-close
capture is off and market.near_close_snapshots stays empty by design."""


@dataclass(frozen=True, slots=True)
class QualitySnapshot:
    computed_at: datetime
    horizon_hours: int
    fixtures_expected: int
    """Scheduled fixtures of active competitions inside the horizon."""
    fixtures_with_odds: int
    """Of those, how many have at least one odds snapshot."""
    fixtures_with_near_close: int
    bookmakers_active: int
    bookmakers_seen_24h: int
    markets_tracked: int
    """Markets we store prices for. Not the same as the markets our models may
    use: that is markets_model_enabled, and it is deliberately smaller."""
    markets_model_enabled: int
    markets_seen_24h: int
    snapshots_24h: int
    stale_fixtures: int
    """Upcoming fixtures whose newest snapshot is older than STALE_CAPTURE_AFTER."""
    failed_jobs_24h: int
    """Runs that finished with errors and nothing durable to show. Since 5 Oct 2026 NOT the capped ones:
    a run stopped at its planned request cap did what it was told (capped_jobs_24h)."""
    partial_jobs_24h: int
    """Runs that wrote something AND hit errors. Invisible before revision 0012,
    when they were recorded as 'completed'."""
    provider_errors_24h: int
    """Errors of runs that spoke to the provider (api_calls > 0). A database error in a pipeline is not
    the provider's: it is in failed_jobs_24h."""
    requests_today: int
    """From raw.provider_quota - requests ISSUED, the number the budget bills
    against. ledger_api_calls_today is the same figure summed over closed runs;
    they differ when a run died without closing."""
    ledger_api_calls_today: int
    daily_budget: int
    requests_remaining_today: int
    unattributed_requests_today: int
    """Billed here but claimed by no closed run: ad-hoc calls like /status, runs
    still in flight, and - the one that matters - runs that died."""
    stale_running_jobs: int
    fixtures_awaiting_result: int
    """Kicked off, still recorded as scheduled or live. Every one of these is a
    row asserting something false, and on a plan that stops serving a date a
    day after it passes, each is close to becoming permanent."""
    fixtures_with_result: int
    """Of the tracked fixtures that have kicked off, how many have a score."""
    last_successful_capture: datetime | None
    windows_expected_24h: int
    windows_captured_24h: int
    capped_jobs_24h: int = 0
    """Runs stopped at their request cap on purpose ('aborted'): the rest is due next run."""
    interrupted_jobs_24h: int = 0
    """Runs whose process ended before they did (a restart, a deadline) - recovered by the watchdog."""
    stale_jobs_24h: int = 0
    """Runs the watchdog found open past their deadline."""
    fixtures_provider_prices: int = 0
    """Of fixtures_expected: the ones the provider lists as priced (/odds/mapping) or that we hold a price for."""
    missed_fixtures: int = 0
    """Listed as priced, a capture window has closed, no price and /odds not asked since it opened: ours."""
    unpriced_fixtures: int = 0
    """Asked since the last window opened and nothing came back, or never listed as priced: the provider's."""
    not_due_fixtures: int = 0
    """No capture window has closed yet for these: nothing is late."""
    awaiting_result_provider: int = 0
    """Of fixtures_awaiting_result: asked again after the match should have ended, and the provider still has no
    outcome - its lag (up to 48 h for some competitions), not ours."""
    final_prematch_finished_7d: int = 0
    """Tracked fixtures finished in the last 7 days: the provider's last pre-match price can still be read."""
    final_prematch_asked: int = 0
    final_prematch_priced: int = 0
    final_prematch_empty: int = 0
    """Asked after the match; the provider had no pre-match price for it."""
    final_prematch_after_kickoff: int = 0
    """Refused whole: the provider's stamp was at or after kick-off, so the price may be an in-play one."""
    final_prematch_median_minutes: float | None = None
    """Median distance from kick-off of the provider's last pre-match update, for the priced ones."""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["computed_at"] = self.computed_at.isoformat()
        d["last_successful_capture"] = self.last_successful_capture.isoformat() if self.last_successful_capture else None
        d["fixture_odds_coverage"] = CoverageMetric(self.fixtures_expected, self.fixtures_with_odds).ratio
        d["bookmaker_coverage"] = CoverageMetric(self.bookmakers_active, self.bookmakers_seen_24h).ratio
        d["market_coverage"] = CoverageMetric(self.markets_tracked, self.markets_seen_24h).ratio
        d["window_coverage_24h"] = CoverageMetric(self.windows_expected_24h, self.windows_captured_24h).ratio
        d["fixture_odds_coverage_priced"] = CoverageMetric(self.fixtures_provider_prices, self.fixtures_with_odds).ratio
        d["final_prematch_coverage"] = CoverageMetric(self.final_prematch_finished_7d, self.final_prematch_priced).ratio
        return d


def _scalar(cur: psycopg.Cursor, sql: str, params: tuple[Any, ...] = ()) -> Any:
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def data_quality_snapshot(
    conn: psycopg.Connection,
    *,
    horizon_hours: int = 96,
    prematch_windows: int = 6,
    daily_budget: int = 60,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    tolerance_minutes: int = 45,
) -> QualitySnapshot:
    moment = now()
    since = moment - timedelta(hours=24)
    until = moment + timedelta(hours=horizon_hours)
    notes: list[str] = []
    with conn.cursor(row_factory=tuple_row) as cur:
        fixtures_expected = int(_scalar(cur, """
            SELECT count(*) FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %s AND %s
        """, (moment, until)))
        fixtures_with_odds = int(_scalar(cur, """
            SELECT count(DISTINCT f.id) FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            JOIN market.odds_snapshots o ON o.fixture_id = f.id
            WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %s AND %s
        """, (moment, until)))
        fixtures_with_near_close = int(_scalar(cur, """
            SELECT count(DISTINCT n.fixture_id) FROM market.near_close_snapshots n
            JOIN core.fixtures f ON f.id = n.fixture_id WHERE f.kickoff_at BETWEEN %s AND %s
        """, (since, until)))
        bookmakers_active = int(_scalar(cur, "SELECT count(*) FROM market.bookmakers WHERE is_active"))
        bookmakers_seen = int(_scalar(cur, "SELECT count(DISTINCT bookmaker_id) FROM market.odds_snapshots WHERE captured_at >= %s", (since,)))
        markets_tracked = int(_scalar(cur, "SELECT count(*) FROM market.markets WHERE is_tracked"))
        markets_model_enabled = int(_scalar(cur, "SELECT count(*) FROM market.markets WHERE is_model_enabled"))
        markets_seen = int(_scalar(cur, "SELECT count(DISTINCT market_key) FROM market.odds_snapshots WHERE captured_at >= %s", (since,)))
        snapshots_24h = int(_scalar(cur, "SELECT count(*) FROM market.odds_snapshots WHERE captured_at >= %s", (since,)))
        cur.execute(CAPTURE_STATE_SQL, (moment, until))
        states = dict.fromkeys(CAPTURE_STATES, 0)
        provider_prices = 0
        for kickoff, last_capture, last_asked, mapped in cur.fetchall():
            provider_prices += int(bool(mapped) or last_capture is not None)
            states[capture_state(kickoff, last_capture, last_asked, bool(mapped), at=moment, windows=windows,
                                 tolerance_minutes=tolerance_minutes)] += 1
        stale = states["stale"]
        cur.execute("SELECT status, count(*) FROM raw.ingestion_runs WHERE started_at >= %s GROUP BY 1", (since,))
        by_status = {str(k): int(v) for k, v in cur.fetchall()}
        failed_jobs = by_status.get("failed", 0)
        partial_jobs = by_status.get("partial", 0)
        stale_runs = int(_scalar(cur, STUCK_RUNS_SQL, (moment, moment - timedelta(hours=2))))
        awaiting_result = int(_scalar(cur, """
            SELECT count(*) FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND ((f.status_group = 'scheduled' AND f.kickoff_at < %s - interval '15 minutes') OR (f.status_group = 'live' AND f.kickoff_at < %s - interval '210 minutes'))
        """, (moment, moment)))
        with_result = int(_scalar(cur, """
            SELECT count(*) FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            JOIN core.fixture_results r ON r.fixture_id = f.id
            WHERE c.is_tracked AND f.kickoff_at < %s
        """, (moment,)))
        awaiting_provider = int(_scalar(cur, """
            SELECT count(*) FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND ((f.status_group = 'scheduled' AND f.kickoff_at < %s - interval '15 minutes')
                                    OR (f.status_group = 'live' AND f.kickoff_at < %s - interval '210 minutes'))
              AND f.source_fetched_at >= f.kickoff_at + interval '3 hours'
        """, (moment, moment)))
        cur.execute(FINAL_PREMATCH_SQL, {"since": moment - timedelta(days=FINAL_PREMATCH_DAYS), "at": moment})
        fp = cur.fetchone() or (0, 0, 0, 0, 0, None)
        cur.execute("SELECT coalesce(sum(errors), 0) FROM raw.ingestion_runs WHERE started_at >= %(since)s "
                    f"AND api_calls > 0 AND {PROVIDER_ERROR_SQL}", {"since": since, **PROVIDER_ERROR_PARAMS})
        provider_errors = int((cur.fetchone() or (0,))[0])
        last_ok = _scalar(cur, "SELECT max(finished_at) FROM raw.ingestion_runs WHERE job_type = 'odds_capture' AND status = 'completed'")
        # Windows: for fixtures that kicked off in the last 24 h, how many
        # distinct prematch windows did we actually record vs the configured cadence.
        kicked = int(_scalar(cur, """
            SELECT count(*) FROM core.fixtures f
            JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
            JOIN core.competitions c ON c.id = cs.competition_id
            WHERE c.is_tracked AND f.kickoff_at BETWEEN %s AND %s
              AND (EXISTS (SELECT 1 FROM market.odds_mapping_seen m WHERE m.provider_fixture_id = f.provider_fixture_id)
                   OR EXISTS (SELECT 1 FROM market.odds_snapshots o WHERE o.fixture_id = f.id))
        """, (since, moment)))
        windows_captured = int(_scalar(cur, """
            SELECT coalesce(sum(n), 0) FROM (
              SELECT count(DISTINCT date_trunc('hour', o.captured_at)) AS n
              FROM market.odds_snapshots o JOIN core.fixtures f ON f.id = o.fixture_id
              WHERE f.kickoff_at BETWEEN %s AND %s AND o.source = 'prematch'
              GROUP BY f.id
            ) t
        """, (since, moment)))
    # Day boundary from the application clock, not the database's now().
    usage = read_usage(conn, budget=daily_budget)
    if usage.unattributed < 0:
        # Impossible unless something reached the provider without being
        # billed, which would mean the budget is not actually a budget.
        notes.append(
            f"{-usage.unattributed} request(s) recorded by runs were never billed to "
            "the daily counter: something is reaching the provider outside the quota"
        )
    elif usage.unattributed > 0 and stale_runs:
        notes.append(
            f"{usage.unattributed} request(s) today belong to no closed run, and "
            f"{stale_runs} run(s) are open past their deadline: likely a crash (the run watchdog closes them)"
        )
    if awaiting_result:
        notes.append(
            f"{awaiting_result} fixture(s) kicked off but are still recorded as not started; "
            f"{awaiting_provider} of them were asked again after the match should have ended and the provider "
            "still has no outcome (its lag, up to 48 h for some competitions)"
        )
    if states["missed"] or states["stale"]:
        notes.append(
            f"{states['missed']} priced fixture(s) passed a capture window without a price and "
            f"{states['stale']} hold a price older than their last window, with /odds not asked since: ours to catch up"
        )
    if fixtures_expected == 0:
        notes.append("no scheduled fixtures for active competitions in the horizon: coverage ratios are null, not zero")
    if snapshots_24h == 0:
        notes.append("no snapshots in the last 24 h")
    return QualitySnapshot(
        computed_at=moment,
        horizon_hours=horizon_hours,
        fixtures_expected=fixtures_expected,
        fixtures_with_odds=fixtures_with_odds,
        fixtures_with_near_close=fixtures_with_near_close,
        bookmakers_active=bookmakers_active,
        bookmakers_seen_24h=bookmakers_seen,
        markets_tracked=markets_tracked,
        markets_model_enabled=markets_model_enabled,
        markets_seen_24h=markets_seen,
        snapshots_24h=snapshots_24h,
        stale_fixtures=stale,
        failed_jobs_24h=failed_jobs,
        partial_jobs_24h=partial_jobs,
        provider_errors_24h=provider_errors,
        capped_jobs_24h=by_status.get("aborted", 0),
        interrupted_jobs_24h=by_status.get("interrupted", 0),
        stale_jobs_24h=by_status.get("stale", 0),
        requests_today=usage.spent,
        ledger_api_calls_today=usage.ledger_api_calls,
        daily_budget=usage.budget,
        requests_remaining_today=usage.remaining,
        unattributed_requests_today=usage.unattributed,
        stale_running_jobs=stale_runs,
        fixtures_awaiting_result=awaiting_result,
        fixtures_with_result=with_result,
        last_successful_capture=last_ok,
        windows_expected_24h=kicked * prematch_windows,
        windows_captured_24h=min(windows_captured, kicked * prematch_windows),
        fixtures_provider_prices=provider_prices,
        missed_fixtures=states["missed"],
        unpriced_fixtures=states["provider_unpriced"],
        not_due_fixtures=states["not_due"],
        awaiting_result_provider=awaiting_provider,
        final_prematch_finished_7d=int(fp[0]),
        final_prematch_asked=int(fp[1]),
        final_prematch_priced=int(fp[2]),
        final_prematch_empty=int(fp[3]),
        final_prematch_after_kickoff=int(fp[4]),
        final_prematch_median_minutes=None if fp[5] is None else round(float(fp[5]), 1),
        notes=notes,
    )
