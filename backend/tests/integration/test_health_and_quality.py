"""/health and the data-quality snapshot read the ledger and the store; they never call out."""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta

import psycopg

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.domain.market import MarketType
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.picks.rules import CURRENT_RULE
from fbi.quality.health import health
from fbi.quality.metrics import data_quality_snapshot

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def head_revision() -> str:
    """The newest migration on disk, read rather than remembered."""
    versions = pathlib.Path(__file__).parents[2] / "migrations" / "versions"
    return max(f.name.split("_", 1)[0] for f in versions.glob("[0-9]*.py"))


def test_health_with_an_empty_ledger_is_honest_not_green(db: psycopg.Connection) -> None:
    set_clock(FrozenClock(NOW))
    try:
        h = health(db, version="t", daily_budget=60)
    finally:
        set_clock(SystemClock())
    assert h.database.status == "ok"
    assert h.database.data["revision"] == head_revision(), (
        "/health must report the revision the test database was actually migrated to; "
        "a hard-coded number here just breaks on every new migration"
    )
    assert h.worker.status == "unknown", "no run yet is 'unknown', never 'ok'"
    assert h.football_provider.status == "ok" and h.football_provider.data["requests_today"] == 0
    # Every reason carries a stable code and its values, so a page can say it in its reader's language.
    assert (h.database.code, h.database.vars) == ("database_ok", {"revision": head_revision()})
    assert h.worker.code == "worker_never_seen"
    assert (h.football_provider.code, h.football_provider.vars) == ("provider_ok", {"spent": 0, "budget": 60})
    assert h.app.code == "app_running"
    assert h.status == "degraded"
    payload = h.as_dict()
    assert "password" not in str(payload) and "@" not in str(payload.get("database"))


def test_health_reports_the_last_run_and_goes_stale_after_three_ticks(db: psycopg.Connection) -> None:
    clock = FrozenClock(NOW)
    set_clock(clock)
    try:
        ledger = RunLedger(db)
        run_id = ledger.open("odds_capture", scheduled_for=NOW)
        ledger.close(run_id, RunCounters(api_calls=2, rows_inserted=6))
        fresh = health(db, version="t", daily_budget=60)
        assert fresh.worker.status == "ok" and fresh.worker.data["last_job"] == "odds_capture"
        assert fresh.football_provider.data["requests_today"] == 2
        clock.advance(minutes=50)
        stale = health(db, version="t", daily_budget=60)
        assert stale.worker.status == "degraded" and "min ago" in stale.worker.detail
        assert (stale.worker.code, stale.worker.vars) == ("ledger_quiet", {"minutes": 50})
    finally:
        set_clock(SystemClock())
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (run_id,))
        db.commit()


def test_a_failed_run_degrades_the_worker_and_the_provider(db: psycopg.Connection) -> None:
    set_clock(FrozenClock(NOW))
    try:
        ledger = RunLedger(db)
        run_id = ledger.open("fixtures_sync")
        ledger.close(run_id, RunCounters(api_calls=1, errors=["HTTP 429"]))
        h = health(db, version="t", daily_budget=60)
        assert h.worker.status == "degraded" and h.worker.data["last_error"] == "HTTP 429"
        assert h.football_provider.status == "degraded"
    finally:
        set_clock(SystemClock())
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (run_id,))
        db.commit()


def test_a_database_error_in_a_run_that_called_the_provider_is_not_a_provider_error(db: psycopg.Connection) -> None:
    """5 Oct 2026: a truth audit's statement timeout (370 provider requests in that run) set the provider to
    'degraded' for an hour."""
    set_clock(FrozenClock(NOW))
    try:
        ledger = RunLedger(db)
        run_id = ledger.open("truth_audit")
        ledger.close(run_id, RunCounters(api_calls=370, errors=["QueryCanceled: canceling statement due to "
                                                                "statement timeout"]))
        h = health(db, version="t", daily_budget=100_000)
        assert h.football_provider.status == "ok", h.football_provider.detail
        assert data_quality_snapshot(db, daily_budget=100_000).provider_errors_24h == 0
    finally:
        set_clock(SystemClock())
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (run_id,))
        db.commit()


def test_the_health_endpoint_never_spends_quota(db: psycopg.Connection) -> None:
    """The provider check is derived from the ledger. If it ever called
    /status, requests_today would move on its own."""
    before = health(db, version="t", daily_budget=60).football_provider.data["requests_today"]
    for _ in range(5):
        health(db, version="t", daily_budget=60)
    after = health(db, version="t", daily_budget=60).football_provider.data["requests_today"]
    assert before == after


def test_quality_snapshot_uses_null_ratios_when_nothing_is_expected(db: psycopg.Connection) -> None:
    set_clock(FrozenClock(NOW))
    try:
        snap = data_quality_snapshot(db)
    finally:
        set_clock(SystemClock())
    d = snap.as_dict()
    assert d["fixtures_expected"] == 0
    assert d["fixture_odds_coverage"] is None, "nothing expected -> null, never 0 or 1"
    assert d["markets_tracked"] == len(MarketType), "every market the schema knows is tracked"
    assert d["markets_model_enabled"] == len(CURRENT_RULE.markets), (
        "the snapshot counts what the current decision rule covers, not a "
        "number written down beside it"
    )
    assert any("null, not zero" in n for n in snap.notes)


def test_quality_snapshot_counts_a_captured_fixture(db: psycopg.Connection) -> None:
    from tests.integration.conftest import Seed  # noqa: F401 - fixture types

    set_clock(FrozenClock(NOW))
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE core.competitions SET is_tracked = true WHERE provider_league_id = 39")
            cur.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE provider_fixture_id = 1001", (NOW + timedelta(hours=30),))
            cur.execute(
                "INSERT INTO market.odds_snapshots "
                "SELECT f.id, b.id, '1X2', 'Home', 0, 2.10, %s, 1800, 'prematch', 'h1' "
                "FROM core.fixtures f, market.bookmakers b WHERE f.provider_fixture_id = 1001 AND b.provider_bookmaker_id = 8 "
                "ON CONFLICT DO NOTHING",
                (NOW - timedelta(hours=1),),
            )
        snap = data_quality_snapshot(db)
        assert snap.fixtures_expected == 1 and snap.fixtures_with_odds == 1
        assert snap.as_dict()["fixture_odds_coverage"] == 1.0
        assert snap.stale_fixtures == 0
        assert snap.bookmakers_seen_24h == 1 and snap.markets_seen_24h == 1
    finally:
        set_clock(SystemClock())
        db.rollback()


def test_quality_snapshot_judges_odds_by_capture_window_and_tells_the_providers_gaps(db: psycopg.Connection) -> None:
    """5 Oct 2026: a fixed 4-hour rule called 40 of 73 priced fixtures stale while every due window had been captured,
    and "0 near-close" hid the 344 last pre-match prices the provider gave after the matches."""
    set_clock(FrozenClock(NOW))
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE core.competitions SET is_tracked = true WHERE provider_league_id = 39")
            cur.execute("UPDATE core.fixtures SET kickoff_at = %s, status_short = 'NS', status_group = 'scheduled' "
                        "WHERE provider_fixture_id = 1001", (NOW + timedelta(hours=20),))
            cur.execute("INSERT INTO market.odds_mapping_seen (provider_fixture_id, first_seen_at, payload_hash, "
                        "normalizer_version) VALUES (1001, %s, 'h1', 't')", (NOW - timedelta(days=2),))
            cur.execute(
                "INSERT INTO market.odds_snapshots "
                "SELECT f.id, b.id, '1X2', 'Home', 0, 2.10, %s, 3000, 'prematch', 'h1' "
                "FROM core.fixtures f, market.bookmakers b WHERE f.provider_fixture_id = 1001 "
                "AND b.provider_bookmaker_id = 8 ON CONFLICT DO NOTHING", (NOW - timedelta(hours=30),))
        snap = data_quality_snapshot(db)
        assert (snap.fixtures_provider_prices, snap.stale_fixtures, snap.missed_fixtures) == (1, 1, 0), \
            "T-24 h closed; the newest price is from T-50 h and /odds was not asked since"
        assert snap.as_dict()["fixture_odds_coverage_priced"] == 1.0
        with db.cursor() as cur:
            cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
                        "file_path, bytes) SELECT 'odds-asked', run_id, '/odds', '{\"fixture\": \"1001\"}', %s, 200, "
                        "'x', 1 FROM raw.ingestion_payloads WHERE hash = 'h1'", (NOW - timedelta(hours=1),))
        asked = data_quality_snapshot(db)
        assert (asked.stale_fixtures, asked.unpriced_fixtures) == (0, 1), "asked, nothing came back: the provider's"
        with db.cursor() as cur:
            cur.execute("UPDATE core.fixtures SET kickoff_at = %s, status_short = 'FT', status_group = 'finished' "
                        "WHERE provider_fixture_id = 1001", (NOW - timedelta(days=2),))
            cur.execute("INSERT INTO market.final_prematch_checks (fixture_id, checked_at, outcome, quotes) "
                        "SELECT id, %s, 'empty', 0 FROM core.fixtures WHERE provider_fixture_id = 1001", (NOW,))
        after = data_quality_snapshot(db)
        assert (after.final_prematch_finished_7d, after.final_prematch_asked, after.final_prematch_empty) == (1, 1, 1)
        assert after.as_dict()["final_prematch_coverage"] == 0.0
    finally:
        set_clock(SystemClock())
        db.rollback()


def test_requests_today_uses_the_application_clock_not_the_database_clock(
    db: psycopg.Connection,
) -> None:
    """A run recorded "today" by the frozen clock must count as today.

    This failed the first time the suite ran on a different calendar day from
    the one the test was written on: the query said
    `started_at >= date_trunc('day', now())` and `now()` was the database's,
    not the clock the capturer bills its quota against.
    """
    clock = FrozenClock(datetime(2026, 3, 4, 9, 30, tzinfo=UTC))
    set_clock(clock)
    try:
        ledger = RunLedger(db)
        today_run = ledger.open("odds_capture")
        ledger.close(today_run, RunCounters(api_calls=7))
        clock.advance(hours=30)  # next day by the same clock
        yesterday_only = health(db, version="t", daily_budget=60)
        assert yesterday_only.football_provider.data["requests_today"] == 0

        clock.advance(hours=-30)
        same_day = health(db, version="t", daily_budget=60)
        assert same_day.football_provider.data["requests_today"] == 7
    finally:
        set_clock(SystemClock())
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (today_run,))
        db.commit()


# ---------------------------------------------------------------------------
# The two guards from BLOQUE 2.5, as /health and /health/quality see them
# ---------------------------------------------------------------------------

def test_a_partial_run_degrades_the_worker_instead_of_reading_as_healthy(db: psycopg.Connection) -> None:
    """The regression that mattered: before 'partial' existed this exact run
    was stored as 'completed' and /health reported the worker as ok."""
    set_clock(FrozenClock(NOW))
    try:
        ledger = RunLedger(db)
        run_id = ledger.open("fixtures_sync", scheduled_for=NOW)
        ledger.close(
            run_id,
            RunCounters(api_calls=9, payloads_stored=2, rows_inserted=9, errors=["refused"] * 7),
        )
        h = health(db, version="t", daily_budget=60)
        assert h.worker.status == "degraded"
        assert "partly succeeded" in h.worker.detail
        assert (h.worker.code, h.worker.vars) == ("ledger_last_partial", {"job": "fixtures_sync"})
        assert h.worker.data["last_status"] == "partial"
        assert h.worker.data["partial_runs_24h"] == 1
        assert h.worker.data["last_successful_run"] != h.worker.data["last_started_at"], (
            "a partial run is not a successful run; if 'last successful' pointed at "
            "it, that would hide exactly what 'partial' was added to reveal"
        )
        assert h.status == "degraded"
    finally:
        set_clock(SystemClock())
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (run_id,))
        db.commit()


def test_health_reports_the_persistent_counter_not_a_sum_over_closed_runs(db: psycopg.Connection) -> None:
    """A run still in flight has spent requests the ledger has not recorded yet.
    /health must show the number the budget actually bills against, because
    that is the one that will refuse the next call."""
    set_clock(FrozenClock(NOW))
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO raw.provider_quota (provider, quota_date, spent, budget) "
                "VALUES ('api_football', %s, 40, 60)",
                (NOW.date(),),
            )
        h = health(db, version="t", daily_budget=60)
        data = h.football_provider.data
        assert data["requests_today"] == 40, "from raw.provider_quota"
        assert data["ledger_api_calls_today"] == 0, "no run has closed"
        assert data["remaining"] == 20
        assert data["unattributed_requests"] == 40
        assert h.football_provider.status == "ok", (
            "unattributed requests are reported, not alarmed about: a plain "
            "`capture_odds status` opens no run and would otherwise degrade the "
            "health of a perfectly healthy system"
        )
    finally:
        set_clock(SystemClock())
        db.rollback()


def test_an_exhausted_budget_degrades_the_provider_check(db: psycopg.Connection) -> None:
    set_clock(FrozenClock(NOW))
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO raw.provider_quota (provider, quota_date, spent, budget) "
                "VALUES ('api_football', %s, 60, 60)",
                (NOW.date(),),
            )
        h = health(db, version="t", daily_budget=60)
        assert h.football_provider.status == "degraded"
        assert h.football_provider.detail == "daily budget exhausted"
        assert (h.football_provider.code, h.football_provider.vars) == ("provider_budget_exhausted",
                                                                        {"spent": 60, "budget": 60})
        assert h.football_provider.data["remaining"] == 0
    finally:
        set_clock(SystemClock())
        db.rollback()


def test_the_quality_snapshot_separates_partial_runs_from_failed_ones(db: psycopg.Connection) -> None:
    set_clock(FrozenClock(NOW))
    ids = []
    try:
        ledger = RunLedger(db)
        for counters in (
            RunCounters(api_calls=9, payloads_stored=2, rows_inserted=9, errors=["HTTP 503"] * 7),
            RunCounters(api_calls=1, errors=["ConnectError: [Errno 104] Connection reset by peer"]),
            RunCounters(api_calls=2, rows_inserted=3),
        ):
            run_id = ledger.open("odds_capture", scheduled_for=NOW)
            ledger.close(run_id, counters)
            ids.append(run_id)
        snap = data_quality_snapshot(db, daily_budget=60)
        assert snap.partial_jobs_24h == 1
        assert snap.failed_jobs_24h == 1, "the partial one is not counted as failed"
        assert snap.provider_errors_24h == 8
        d = snap.as_dict()
        assert d["partial_jobs_24h"] == 1 and d["failed_jobs_24h"] == 1
    finally:
        set_clock(SystemClock())
        with db.cursor() as cur:
            cur.execute("DELETE FROM raw.ingestion_runs WHERE id = ANY(%s)", (ids,))
        db.commit()


def test_the_quality_snapshot_reports_the_budget_without_crying_wolf(db: psycopg.Connection) -> None:
    set_clock(FrozenClock(NOW))
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO raw.provider_quota (provider, quota_date, spent, budget) "
                "VALUES ('api_football', %s, 13, 60)",
                (NOW.date(),),
            )
        snap = data_quality_snapshot(db, daily_budget=60)
        d = snap.as_dict()
        assert (d["requests_today"], d["daily_budget"], d["requests_remaining_today"]) == (13, 60, 47)
        assert d["ledger_api_calls_today"] == 0
        assert d["unattributed_requests_today"] == 13
        assert not any("likely a crash" in n for n in snap.notes), (
            "no run is stuck, so unattributed requests are just ad-hoc calls"
        )
    finally:
        set_clock(SystemClock())
        db.rollback()


def test_unattributed_requests_plus_a_stuck_run_is_worth_a_note(db: psycopg.Connection) -> None:
    """Together they mean what neither means alone: a run took the budget and
    died. Apart, each is ordinary."""
    set_clock(FrozenClock(NOW))
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO raw.provider_quota (provider, quota_date, spent, budget) "
                "VALUES ('api_football', %s, 9, 60)",
                (NOW.date(),),
            )
            cur.execute(
                "INSERT INTO raw.ingestion_runs (job_name, job_type, status, started_at) "
                "VALUES ('odds_capture','odds_capture','running', %s)",
                (NOW - timedelta(hours=3),),
            )
        snap = data_quality_snapshot(db, daily_budget=60)
        assert snap.stale_running_jobs == 1
        assert snap.unattributed_requests_today == 9
        assert any("likely a crash" in n for n in snap.notes)
    finally:
        set_clock(SystemClock())
        db.rollback()


def test_the_snapshot_counts_fixtures_that_kicked_off_without_a_result(
    db: psycopg.Connection,
) -> None:
    """The defect the result sync exists for, made visible. A fixture past
    kick-off and still 'scheduled' is a row asserting something false, and the
    free plan stops serving its date about a day later - so the count is also
    a countdown."""
    set_clock(FrozenClock(NOW))
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE core.competitions SET is_tracked = true WHERE provider_league_id = 39")
            cur.execute(
                "UPDATE core.fixtures SET kickoff_at = %s, status_group = 'scheduled', status_short = 'NS' "
                "WHERE provider_fixture_id = 1001",
                (NOW - timedelta(hours=6),),
            )
        snap = data_quality_snapshot(db, daily_budget=60)
        assert snap.fixtures_awaiting_result == 1
        assert snap.fixtures_with_result == 0
        assert any("still recorded as not started" in n for n in snap.notes)

        cur = db.cursor()
        cur.execute(
            "UPDATE core.fixtures SET status_group = 'finished', status_short = 'FT' "
            "WHERE provider_fixture_id = 1001"
        )
        cur.execute(
            "INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) "
            "SELECT id, 2, 1 FROM core.fixtures WHERE provider_fixture_id = 1001"
        )
        settled = data_quality_snapshot(db, daily_budget=60)
        assert settled.fixtures_awaiting_result == 0
        assert settled.fixtures_with_result == 1
        assert not any("still recorded as not started" in n for n in settled.notes)
    finally:
        set_clock(SystemClock())
        db.rollback()
