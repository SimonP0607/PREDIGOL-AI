"""The in-play book is the present, never a history (revision 0068), against a real database.

What is proved here:

* a tick brings the book up to date - new keys inserted, changed keys updated in place with the price they
  replaced, withdrawn keys deleted - and an unchanged tick writes nothing;
* the book is BOUNDED: a hundred ticks of a moving market leave one row per key, not one per change;
* a fixture that leaves the live book is purged with all its prices, and nothing of a finished match remains;
* the capture service keeps no /odds/live body in the RAW store and indexes none, unless the body is NEW
  evidence of an anomaly - and then exactly once, however often the provider repeats the quirk;
* nothing reaches a pre-match table, and the old in-play history tables receive nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion.payload_store import PayloadStore
from fbi.odds.live_capture import LiveCaptureService
from fbi.odds.live_repository import STALE_AFTER, LiveOddsRepository
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.live import LiveFixtureState, LiveOddsQuote
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from tests.integration.conftest import Seed

AT = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)
PROVIDER_FIXTURE = 1001
TICK = timedelta(seconds=30)
SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
PREMATCH = ("market.odds_snapshots", "market.final_prematch_odds", "market.near_close_snapshots",
            "market.market_consensus", "market.historical_odds")


def state(n: int = 0, **kw: object) -> LiveFixtureState:
    base: dict[str, object] = {
        "provider_fixture_id": PROVIDER_FIXTURE, "captured_at": AT + n * TICK, "payload_hash": f"h-{n}",
        "elapsed_minute": 10 + n, "elapsed_seconds": f"{10 + n}:00", "score_home": 0, "score_away": 0,
        "status_long": "First Half", "is_stopped": False, "is_blocked": False, "is_finished": False,
        "markets_offered": 1, "values_offered": 1, "values_suspended": 0, "provider_updated_at": AT + n * TICK,
    }
    base.update(kw)
    return LiveFixtureState(**base)  # type: ignore[arg-type]


def quote(n: int, odds: str, *, selection: str = "Home", bet: int = 59, suspended: bool = False,
          line: str = "0", score: tuple[int, int] = (0, 0)) -> LiveOddsQuote:
    return LiveOddsQuote(
        provider_fixture_id=PROVIDER_FIXTURE, provider_bet_id=bet, market_key="1X2" if bet == 59 else None,
        selection=selection, line=Decimal(line), odds_decimal=Decimal(odds), is_suspended=suspended,
        is_main_line=None, elapsed_minute=10 + n, elapsed_seconds=f"{10 + n}:00", score_home=score[0],
        score_away=score[1], status_long="First Half", is_stopped=False, is_blocked=False,
        provider_updated_at=AT + n * TICK, captured_at=AT + n * TICK, payload_hash=f"h-{n}",
    )


def book(conn: psycopg.Connection) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute("SELECT selection, odds_decimal, is_suspended, previous_odds, change_kind, changed_minute "
                    "FROM market.live_odds_current ORDER BY provider_bet_id, selection")
        return list(cur.fetchall())


def count(conn: psycopg.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        row = cur.fetchone()
        return int(row[0]) if row else 0


def old_history_rows(conn: psycopg.Connection) -> int:
    """Rows in the pre-0068 history tables, while they still exist (0069 drops them)."""
    total = 0
    with conn.cursor() as cur:
        for table in ("market.live_odds_snapshots", "market.live_fixture_states"):
            cur.execute("SELECT to_regclass(%s)", (table,))
            row = cur.fetchone()
            if row and row[0]:
                cur.execute(f"SELECT count(*) FROM {table}")
                total += int((cur.fetchone() or (0,))[0])
    return total


# --- the book is brought up to date, not appended to -------------------------------------------------------


def test_a_first_quote_is_offered_and_an_unchanged_tick_writes_nothing(db: psycopg.Connection, seed: Seed) -> None:
    repo = LiveOddsRepository(db)
    first = repo.write([state(0)], [quote(0, "2.50")])
    second = repo.write([state(1)], [quote(1, "2.50")])
    assert (first.quotes_inserted, first.quotes_updated) == (1, 0)
    assert (second.quotes_written, second.quotes_unchanged) == (0, 1)
    assert book(db) == [("Home", Decimal("2.500"), False, None, "offered", 10)]


def test_a_moved_price_replaces_the_row_and_keeps_the_one_it_replaced(db: psycopg.Connection, seed: Seed) -> None:
    repo = LiveOddsRepository(db)
    repo.write([state(0)], [quote(0, "2.50")])
    moved = repo.write([state(1)], [quote(1, "2.10", score=(1, 0))])
    assert (moved.quotes_updated, moved.quotes_inserted) == (1, 0)
    assert book(db) == [("Home", Decimal("2.100"), False, Decimal("2.500"), "moved", 11)]
    with db.cursor() as cur:
        cur.execute("SELECT changed_score_home, changed_score_away FROM market.live_odds_current")
        assert cur.fetchone() == (1, 0)
    assert count(db, "market.live_odds_current") == 1


def test_a_suspension_at_the_same_price_is_a_change_and_so_is_the_reopening(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    repo.write([state(0)], [quote(0, "2.50")])
    repo.write([state(1)], [quote(1, "2.50", suspended=True)])
    assert book(db)[0][2:5] == (True, Decimal("2.500"), "suspended")
    repo.write([state(2)], [quote(2, "2.50")])
    assert book(db)[0][2:5] == (False, Decimal("2.500"), "available")


def test_a_key_the_fixture_stops_quoting_is_deleted_and_comes_back_as_offered(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    repo.write([state(0)], [quote(0, "2.50"), quote(0, "3.40", selection="Draw")])
    gone = repo.write([state(1)], [quote(1, "2.50")])
    assert gone.withdrawals_written == 1
    assert [r[0] for r in book(db)] == ["Home"]
    back = repo.write([state(2)], [quote(2, "2.50"), quote(2, "3.60", selection="Draw")])
    assert back.quotes_inserted == 1
    assert sorted((r[0], r[4], r[3]) for r in book(db)) == [("Draw", "offered", None), ("Home", "offered", None)]


def test_a_fixture_absent_from_the_payload_keeps_its_prices_until_the_purge(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Absent is not withdrawn: it may be a provider hiccup. After STALE_AFTER it has left the live book."""
    repo = LiveOddsRepository(db)
    repo.write([state(0)], [quote(0, "2.50")])
    other = repo.write([], [])
    assert other.withdrawals_written == 0 and count(db, "market.live_odds_current") == 1
    assert repo.purge_stale(at=AT + STALE_AFTER - TICK).fixtures == 0
    purged = repo.purge_stale(at=AT + STALE_AFTER + TICK)
    assert (purged.fixtures, purged.quotes) == (1, 1)
    assert count(db, "market.live_odds_current") == 0
    assert count(db, "market.live_fixture_current") == 0


def test_a_hundred_ticks_of_a_moving_market_leave_one_row_per_key(db: psycopg.Connection, seed: Seed) -> None:
    """The bound that makes this a book and not a series: rows = keys quoted now, whatever happened before."""
    repo = LiveOddsRepository(db)
    for n in range(100):
        home = f"{2.0 + (n % 7) / 10:.2f}"
        draw = f"{3.0 + (n % 5) / 10:.2f}"
        quotes = [quote(n, home), quote(n, draw, selection="Draw"), quote(n, "4.20", selection="Away")]
        quotes += [quote(n, f"{1.5 + (n % 3) / 10:.2f}", bet=20, selection=f"Over {k}", line=f"{k}.5")
                   for k in range(8, 12)]
        repo.write([state(n, elapsed_minute=min(90, 10 + n))], quotes)
    assert count(db, "market.live_odds_current") == 7
    assert count(db, "market.live_fixture_current") == 1
    assert old_history_rows(db) == 0


def test_the_fixture_row_keeps_when_it_was_first_seen_and_never_goes_back_in_time(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    repo.write([state(2)], [])
    repo.write([state(1, elapsed_minute=99)], [])  # an older tick replayed
    with db.cursor() as cur:
        cur.execute("SELECT first_seen_at, captured_at, elapsed_minute FROM market.live_fixture_current")
        assert cur.fetchone() == (AT + 2 * TICK, AT + 2 * TICK, 12)


def test_an_untracked_fixture_and_a_duplicate_quote_are_counted_never_silently_dropped(
    db: psycopg.Connection, seed: Seed
) -> None:
    repo = LiveOddsRepository(db)
    stranger = replace(quote(0, "2.00"), provider_fixture_id=999_999)
    result = repo.write([state(0)], [quote(0, "2.50"), quote(0, "2.55"), stranger])
    assert (result.quotes_duplicate, result.quotes_untracked, result.quotes_inserted) == (1, 1, 1)
    assert result.quotes_offered == result.quotes_written + result.quotes_unchanged + result.quotes_duplicate \
        + result.quotes_untracked


def test_the_book_writes_nothing_prematch(db: psycopg.Connection, seed: Seed) -> None:
    before = {t: count(db, t) for t in PREMATCH}
    repo = LiveOddsRepository(db)
    for n in range(5):
        repo.write([state(n)], [quote(n, f"2.{n}0"), quote(n, "3.30", selection="Draw")])
    assert {t: count(db, t) for t in PREMATCH} == before
    assert old_history_rows(db) == 0


def test_the_book_tables_are_unlogged_and_have_no_raw_foreign_key(db: psycopg.Connection) -> None:
    with db.cursor() as cur:
        cur.execute("SELECT relname, relpersistence FROM pg_class WHERE relname IN "
                    "('live_odds_current', 'live_fixture_current') ORDER BY 1")
        assert cur.fetchall() == [("live_fixture_current", "u"), ("live_odds_current", "u")]
        cur.execute("SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND confrelid = "
                    "'raw.ingestion_payloads'::regclass AND conrelid IN ('market.live_odds_current'::regclass, "
                    "'market.live_fixture_current'::regclass)")
        assert cur.fetchone() == (0,)


# --- the capture service: nothing kept, unless it is new evidence ------------------------------------------


def live_body(odds: list[tuple[str, str, bool]], *, extra_values: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    values: list[dict[str, Any]] = [{"value": v, "odd": o, "handicap": None, "main": None, "suspended": s}
                                    for v, o, s in odds]
    values += extra_values or []
    return {
        "response": [{
            "fixture": {"id": PROVIDER_FIXTURE, "status": {"long": "Second Half", "elapsed": 77, "seconds": "77:00"}},
            "league": {"id": 39, "season": 2025},
            "teams": {"home": {"id": 33, "goals": 0}, "away": {"id": 40, "goals": 1}},
            "status": {"stopped": False, "blocked": False, "finished": False},
            "update": AT.isoformat(),
            "odds": [{"id": 59, "name": "Fulltime Result", "values": values}],
        }],
        "errors": [], "results": 1,
    }


@pytest.fixture()
def live_conn(db: psycopg.Connection, seed: Seed) -> Iterator[psycopg.Connection]:
    """The service commits, so this cleans up after itself. The fixture plays now."""
    with db.cursor() as cur:
        cur.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (AT - timedelta(minutes=50),
                                                                              seed.fixture_id))
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    db.commit()
    set_clock(FrozenClock(AT))
    yield db
    set_clock(SystemClock())
    with db.cursor() as cur:
        cur.execute("DELETE FROM market.live_odds_current")
        cur.execute("DELETE FROM market.live_fixture_current")
        cur.execute("DELETE FROM audit.data_quality_issues")
        cur.execute("DELETE FROM market.provider_markets WHERE source = 'observed'")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE hash <> 'h1'")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'live_odds_capture'")
        cur.execute("UPDATE core.fixtures SET kickoff_at = '2026-09-15 19:00Z' WHERE id = %s", (seed.fixture_id,))
        cur.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))
    db.commit()


def make_service(conn: psycopg.Connection, raw_root: Path, bodies: list[dict[str, Any]]) -> LiveCaptureService:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = bodies[min(calls["n"], len(bodies) - 1)]
        calls["n"] += 1
        return httpx.Response(200, json=body)

    async def _no_sleep(_s: float) -> None:
        return None

    settings = ApiFootballSettings(key=SECRET, plan="pro", daily_budget=500, max_retries=0)
    client = ApiFootballClient(settings, PayloadStore(raw_root), transport=httpx.MockTransport(handler),
                               rate_limiter=TokenBucket(settings.per_minute_limit, sleep=_no_sleep),
                               quota=DailyQuota(budget=500))
    return LiveCaptureService(conn, ApiFootballProvider(client), floor_seconds=1, raw_store=PayloadStore(raw_root))


def raw_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


async def test_a_tick_keeps_the_book_and_writes_no_raw_file_and_no_index_row(
    live_conn: psycopg.Connection, tmp_path: Path
) -> None:
    payloads = count(live_conn, "raw.ingestion_payloads")
    service = make_service(live_conn, tmp_path, [live_body([("Home", "2.50", False), ("Draw", "3.30", False),
                                                            ("Away", "2.90", False)])])
    report = await service.capture(at=AT, remaining_quota=10_000)
    assert report.captured and report.accounting_holds
    assert (report.book_fixtures, report.book_quotes, report.quotes_inserted) == (1, 3, 3)
    assert report.payloads_stored == 0 and not report.raw_kept
    assert raw_files(tmp_path) == []
    assert count(live_conn, "raw.ingestion_payloads") == payloads
    assert old_history_rows(live_conn) == 0
    with live_conn.cursor() as cur:
        cur.execute("SELECT api_calls, payloads_stored FROM raw.ingestion_runs WHERE id = %s", (report.run_id,))
        assert cur.fetchone() == (1, 0), "the request is still accounted for in the ledger"


async def test_many_ticks_keep_the_book_bounded_and_the_raw_store_empty(
    live_conn: psycopg.Connection, tmp_path: Path
) -> None:
    bodies = [live_body([("Home", f"{2.0 + n / 100:.2f}", False), ("Draw", "3.30", n % 4 == 0),
                         ("Away", "2.90", False)]) for n in range(12)]
    service = make_service(live_conn, tmp_path, bodies)
    for n in range(12):
        report = await service.capture(at=AT + n * TICK, remaining_quota=10_000)
        assert report.captured and report.accounting_holds, n
    assert count(live_conn, "market.live_odds_current") == 3
    assert count(live_conn, "market.live_fixture_current") == 1
    assert raw_files(tmp_path) == []
    for table in PREMATCH:
        assert count(live_conn, table) == 0, table


async def test_new_evidence_of_an_anomaly_is_kept_once_however_often_it_repeats(
    live_conn: psycopg.Connection, tmp_path: Path
) -> None:
    """A price out of range is a real anomaly (not a normal suspension): the first body showing it is written and
    indexed so the incident points to its bytes; the same quirk on the next ticks needs no new bytes."""
    odd = {"value": "Draw", "odd": "1.00", "handicap": None, "main": None, "suspended": False}
    bodies = [live_body([("Home", f"2.{n}0", False)], extra_values=[odd]) for n in range(3)]
    service = make_service(live_conn, tmp_path, bodies)
    reports = [await service.capture(at=AT + n * TICK, remaining_quota=10_000) for n in range(3)]
    assert [r.raw_kept for r in reports] == [True, False, False]
    assert len(raw_files(tmp_path)) == 1
    with live_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw.ingestion_payloads WHERE endpoint = '/odds/live'")
        assert cur.fetchone() == (1,)
        cur.execute("SELECT occurrences, payload_hash IS NOT NULL FROM audit.data_quality_issues "
                    "WHERE code = 'NORMALIZATION_REJECTED'")
        assert cur.fetchall() == [(3, True)]


async def test_an_idle_wake_up_purges_what_left_the_live_book(live_conn: psycopg.Connection, tmp_path: Path) -> None:
    service = make_service(live_conn, tmp_path, [live_body([("Home", "2.50", False)])])
    await service.capture(at=AT, remaining_quota=10_000)
    assert count(live_conn, "market.live_odds_current") == 1
    purged = service.purge_stale(at=AT + STALE_AFTER + TICK)
    assert (purged.fixtures, purged.quotes) == (1, 1)
    assert count(live_conn, "market.live_odds_current") == 0
