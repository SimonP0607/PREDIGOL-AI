"""completed / partial / failed - and why 'partial' had to exist.

The fixtures sync that unblocked the pilot issued 9 requests, had 7 refused
and still imported 9 real fixtures. The ledger recorded it as 'completed',
because the old rule was "failed only if errors AND nothing written". An
operator scanning statuses would never have looked at it, and the 7 refusals -
the single most important thing learned that day - were invisible.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion.fixtures import SyncStrategy, sync_fixtures
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from fbi.storage.payload_store import PayloadStore
from tests.integration.conftest import Seed
from tests.integration.helpers import must_be_rejected, row, scalar

NOW = datetime(2026, 9, 12, 21, 54, tzinfo=UTC)
SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


def _backfill_sql() -> str:
    """0013's UPGRADE, read from the migration itself.

    A copy of the SQL in the test would pass forever while the migration
    drifted away from it, so the file is the source. Its module name starts
    with a digit and cannot be imported, hence the load by path.
    """
    import importlib.util

    path = Path(__file__).parents[2] / "migrations" / "versions" / "0013_reclassify_mislabelled_runs.py"
    spec = importlib.util.spec_from_file_location("migration_0013", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.UPGRADE)


BACKFILL_SQL = _backfill_sql()


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------

def test_no_errors_is_completed() -> None:
    assert RunCounters(api_calls=2, rows_inserted=9).status == "completed"
    assert RunCounters().status == "completed", "a run with nothing to do did not fail"


def test_errors_plus_rows_is_partial() -> None:
    c = RunCounters(api_calls=9, payloads_stored=2, rows_inserted=9, errors=["r"] * 7)
    assert c.did_useful_work is True
    assert c.status == "partial"


def test_errors_plus_a_stored_payload_alone_is_still_partial() -> None:
    """The bytes are on disk and indexed; a price can be normalised out of them
    later. That is durable progress even though nothing was parsed yet."""
    c = RunCounters(api_calls=1, payloads_stored=1, errors=["could not parse"])
    assert c.status == "partial"


def test_errors_and_nothing_durable_is_failed() -> None:
    c = RunCounters(api_calls=3, errors=["boom", "boom again"])
    assert c.did_useful_work is False
    assert c.status == "failed"


def test_spending_quota_is_not_useful_work() -> None:
    """Otherwise every run that reached the provider would count as partial,
    and 'failed' would become unreachable."""
    assert RunCounters(api_calls=50, errors=["all refused"]).status == "failed"


def test_a_deliberate_stop_is_aborted_not_failed() -> None:
    """Orthogonal to the other three: a cap stopped the run on purpose. It
    outranks them, because "we chose to stop" explains the errors."""
    c = RunCounters(api_calls=5, rows_inserted=3, errors=["quota"], stopped_early="run cap of 5 reached")
    assert c.status == "aborted"


# ---------------------------------------------------------------------------
# Persisted, and constrained
# ---------------------------------------------------------------------------

@pytest.fixture()
def clean(db: psycopg.Connection) -> Iterator[psycopg.Connection]:
    yield db
    db.rollback()


def test_each_state_round_trips_through_the_database(clean: psycopg.Connection) -> None:
    ledger = RunLedger(clean)
    cases = {
        "completed": RunCounters(api_calls=1, rows_inserted=1),
        "partial": RunCounters(api_calls=9, payloads_stored=2, rows_inserted=9, errors=["a"] * 7),
        "failed": RunCounters(api_calls=1, errors=["nope"]),
        "aborted": RunCounters(api_calls=5, stopped_early="cap"),
    }
    for expected, counters in cases.items():
        run_id = ledger.open("odds_capture")
        ledger.close(run_id, counters)
        with clean.cursor() as cur:
            cur.execute("SELECT status, errors, last_error FROM raw.ingestion_runs WHERE id = %s", (run_id,))
            status, errors, last_error = row(cur)
        assert status == expected, f"{counters!r} should be {expected}"
        if expected == "partial":
            assert errors == 7 and last_error is not None, (
                "a partial run must still carry its errors: the point is that they "
                "are visible, not that they are forgiven"
            )
    with clean.cursor() as cur:
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'odds_capture'")


@pytest.fixture()
def runs(clean: psycopg.Connection) -> Iterator[list[int]]:
    """Ids of the runs a test opens; open() commits, so they are deleted afterwards."""
    ids: list[int] = []
    yield ids
    clean.rollback()
    clean.execute("DELETE FROM raw.ingestion_runs WHERE id = ANY(%s)", (ids,))
    clean.commit()


def _closed(conn: psycopg.Connection, run_id: int) -> tuple[str, int, str | None]:
    with conn.cursor() as cur:
        cur.execute("SELECT status, errors, last_error FROM raw.ingestion_runs WHERE id = %s", (run_id,))
        status, errors, last_error = row(cur)
    return str(status), int(errors), last_error


def test_a_run_that_crashes_is_failed_not_completed(clean: psycopg.Connection, runs: list[int]) -> None:
    """25 Sep 2026: a Football-Data import whose download was reset closed as
    'completed' with nothing done - the exception left through a finally."""
    ledger = RunLedger(clean)
    run_id = ledger.open("historical_odds_import")
    runs.append(run_id)
    counters = RunCounters()
    with pytest.raises(ConnectionResetError):
        try:
            raise ConnectionResetError("[Errno 104] Connection reset by peer")
        finally:
            ledger.close(run_id, counters)
    status, errors, last_error = _closed(clean, run_id)
    assert (status, errors) == ("failed", 1)
    assert last_error is not None and "Connection reset by peer" in last_error


def test_an_error_the_caller_recorded_is_not_recorded_twice(clean: psycopg.Connection, runs: list[int]) -> None:
    ledger = RunLedger(clean)
    run_id = ledger.open("backtest")
    runs.append(run_id)
    counters = RunCounters()
    with pytest.raises(ValueError):
        try:
            raise ValueError("no fixtures")
        except ValueError as exc:
            counters.errors.append(f"{type(exc).__name__}: {exc}")
            ledger.close(run_id, counters)
            raise
    assert _closed(clean, run_id)[:2] == ("failed", 1)


def test_an_interrupt_is_interrupted_not_aborted(clean: psycopg.Connection, runs: list[int]) -> None:
    """'aborted' means a cap stopped the run on purpose; a run its process could not finish (Ctrl-C, a shutdown,
    a job deadline) is 'interrupted' (5 Oct 2026: shutdown cancellations were counted with the capped runs)."""
    ledger = RunLedger(clean)
    run_id = ledger.open("odds_capture")
    runs.append(run_id)
    counters = RunCounters(api_calls=1, rows_inserted=1)
    with pytest.raises(KeyboardInterrupt):
        try:
            raise KeyboardInterrupt
        finally:
            ledger.close(run_id, counters)
    status, _, last_error = _closed(clean, run_id)
    assert status == "interrupted" and last_error == "interrupted (KeyboardInterrupt)"


def test_a_failed_transaction_does_not_hide_the_run(clean: psycopg.Connection, runs: list[int]) -> None:
    """A database error leaves the transaction aborted; the close must still land."""
    ledger = RunLedger(clean)
    run_id = ledger.open("feature_build")
    runs.append(run_id)
    counters = RunCounters()
    with pytest.raises(psycopg.errors.DivisionByZero):
        try:
            clean.execute("SELECT 1 / 0")
        finally:
            ledger.close(run_id, counters)
    status, errors, last_error = _closed(clean, run_id)
    assert (status, errors) == ("failed", 1) and last_error is not None and "division by zero" in last_error


def test_a_clean_close_is_untouched(clean: psycopg.Connection, runs: list[int]) -> None:
    ledger = RunLedger(clean)
    run_id = ledger.open("results_sync")
    runs.append(run_id)
    try:
        pass
    finally:
        ledger.close(run_id, RunCounters(api_calls=2, rows_updated=1))
    assert _closed(clean, run_id) == ("completed", 0, None)


def test_the_database_refuses_a_status_it_does_not_know(clean: psycopg.Connection) -> None:
    """The CHECK constraint and RunCounters.status have to agree. If someone
    invents a fifth state in Python, this is what catches it."""
    with must_be_rejected(clean, "ingestion_runs_status_check") as cur:
        cur.execute(
            "INSERT INTO raw.ingestion_runs (job_name, job_type, status) VALUES ('t','t','mostly_fine')"
        )


# ---------------------------------------------------------------------------
# The real scenario, end to end
# ---------------------------------------------------------------------------

def fixtures_for(date: str) -> dict:
    return {
        "response": [
            {
                "fixture": {"id": 7001, "date": f"{date}T13:00:00+00:00", "status": {"short": "NS"}},
                "league": {"id": 39, "season": 2025},
                "teams": {"home": {"id": 971, "name": "Alpha FC"}, "away": {"id": 972, "name": "Beta FC"}},
            }
        ],
        "errors": [],
        "paging": {"current": 1, "total": 1},
    }


BEYOND_THE_PLAN = {
    "response": [],
    "errors": {"plan": "Free plans do not have access to this date, try from 2026-09-11 to 2026-09-13."},
}


@pytest.fixture()
def active(db: psycopg.Connection, seed: Seed) -> Iterator[psycopg.Connection]:
    with db.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
        cur.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
    db.commit()
    yield db
    with db.cursor() as cur:
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id = 7001")
        cur.execute("DELETE FROM core.teams WHERE provider_team_id IN (971, 972)")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE run_id IN (SELECT id FROM raw.ingestion_runs WHERE job_type = 'fixtures_sync')")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'fixtures_sync'")
        cur.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))
    db.commit()


async def test_the_sync_that_was_wrongly_called_completed_is_now_partial(
    active: psycopg.Connection, tmp_path: Path
) -> None:
    """Nine requests, two answered, seven refused past the plan's date horizon,
    one fixture imported. Before revision 0012 the ledger said 'completed'."""
    set_clock(FrozenClock(NOW))
    try:
        def handler(request: httpx.Request) -> httpx.Response:
            on = request.url.params.get("date", "")
            served = {"2026-09-12", "2026-09-13"}
            return httpx.Response(200, json=fixtures_for(on) if on in served else BEYOND_THE_PLAN)

        async def _no_sleep(_s: float) -> None:
            return None

        client = ApiFootballClient(
            ApiFootballSettings(key=SECRET, plan="free", daily_budget=60, max_retries=0),
            PayloadStore(tmp_path),
            transport=httpx.MockTransport(handler),
            rate_limiter=TokenBucket(300, sleep=_no_sleep),
            quota=DailyQuota(budget=60),
        )
        counters = await sync_fixtures(
            active, ApiFootballProvider(client), horizon_days=8, strategy=SyncStrategy.DATE
        )
    finally:
        set_clock(SystemClock())

    assert counters.api_calls == 9
    assert len(counters.errors) == 7
    assert counters.rows_inserted == 1, "the two served days describe the same fixture"
    assert counters.status == "partial"

    with active.cursor() as cur:
        cur.execute(
            "SELECT status, api_calls, errors, payloads_stored, rows_written, last_error "
            "FROM raw.ingestion_runs WHERE job_type = 'fixtures_sync' ORDER BY id DESC LIMIT 1"
        )
        status, calls, errors, payloads, written, last_error = row(cur)
    assert status == "partial", "the honest answer: it worked, and it also did not"
    assert (calls, errors, payloads, written) == (9, 7, 2, 1)
    assert "do not have access to this date" in last_error


# ---------------------------------------------------------------------------
# The backfill: rows the two-state rule labelled wrongly
# ---------------------------------------------------------------------------

def test_the_backfill_relabels_only_rows_whose_own_numbers_contradict_them(
    clean: psycopg.Connection,
) -> None:
    """Migration 0013's UPGRADE, run against rows in the shapes it has to judge.

    The decision uses only columns already in the row, so nothing is invented.
    The risk to guard against is the opposite one: relabelling a row whose
    status was right all along.
    """
    cases = {
        # (status, errors, rows_written, rows_updated, payloads) -> expected
        ("completed", 7, 9, 0, 2): "partial",   # the real fixtures_sync
        ("completed", 1, 0, 4, 0): "partial",   # updates count as durable
        ("completed", 1, 0, 0, 1): "partial",   # a stored payload counts too
        ("completed", 2, 0, 0, 0): "failed",    # errors and nothing to show
        ("failed", 3, 5, 0, 1): "partial",      # was too harsh, not too kind
        ("completed", 0, 9, 0, 2): "completed",  # nothing wrong with it
        ("failed", 4, 0, 0, 0): "failed",        # already right
        ("aborted", 2, 3, 0, 1): "aborted",      # never touched: a cap, not a fault
    }
    ids: dict[int, tuple[str, str]] = {}
    with clean.cursor() as cur:
        for (status, errors, written, updated, payloads), expected in cases.items():
            cur.execute(
                "INSERT INTO raw.ingestion_runs "
                "(job_name, job_type, status, errors, rows_written, rows_updated, payloads_stored, finished_at) "
                "VALUES ('backfill','backfill_test',%s,%s,%s,%s,%s, now()) RETURNING id",
                (status, errors, written, updated, payloads),
            )
            ids[int(scalar(cur))] = (status, expected)

        cur.execute(BACKFILL_SQL)

        for run_id, (was, expected) in ids.items():
            cur.execute("SELECT status, notes FROM raw.ingestion_runs WHERE id = %s", (run_id,))
            status, notes = row(cur)
            assert status == expected, f"run {run_id} was {was} and should now be {expected}, got {status}"
            if was == expected:
                assert notes is None, (
                    f"run {run_id} was already {was}; touching its notes would imply a "
                    "change that did not happen"
                )
            else:
                assert notes is not None and f"reclassified by migration 0013 from {was}" in notes, (
                    "a relabelled row has to say what it was, or the change is invisible"
                )
