"""End-to-end capture against the real database.

Proves the property the legacy system did not have: running the same capture
twice adds history, never overwrites it, and never duplicates it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion.payload_store import PayloadStore
from fbi.odds.capture import OddsCaptureService
from fbi.odds.repository import OddsRepository
from fbi.odds.schedule import CapturePlanner, ScheduledFixture
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.normalize import INPLAY_BETS, PREMATCH_BETS
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

KICKOFF = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)
SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"


def odds_body(home: str, draw: str, away: str, *, scope: str = "prematch") -> dict:
    """A 1X2 price list, in the bet namespace of the endpoint that serves it.

    /odds and /odds/live number their bets DIFFERENTLY: the full-match winner is
    pre-match bet 1 "Match Winner" and in-play bet 59 "Fulltime Result". A live
    body built with the pre-match id is not a 1X2 body at all, and the boundary
    is expected to yield nothing from it.
    """
    bet = PREMATCH_BETS["1X2"] if scope == "prematch" else INPLAY_BETS["1X2"]
    return {
        "response": [
            {
                "fixture": {"id": 1001},
                "bookmakers": [
                    {
                        "id": 8,
                        "name": "Bet365",
                        "bets": [
                            {
                                "id": bet.bet_id,
                                "name": bet.name,
                                "values": [
                                    {"value": "Home", "odd": home},
                                    {"value": "Draw", "odd": draw},
                                    {"value": "Away", "odd": away},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "errors": [],
        "paging": {"current": 1, "total": 1},
    }


@pytest.fixture()
def clock() -> Iterator[FrozenClock]:
    frozen = FrozenClock(KICKOFF - timedelta(minutes=1439))  # inside the 1440 window: T-1440..T-1395
    set_clock(frozen)
    yield frozen
    set_clock(SystemClock())


def make_service(
    conn: psycopg.Connection, tmp_path: Path, body_for: object
) -> tuple[OddsCaptureService, dict]:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=body_for(calls["n"]))  # type: ignore[operator]

    async def _no_sleep(_s: float) -> None:
        return None

    settings = ApiFootballSettings(key=SECRET, plan="pro", daily_budget=50, max_retries=0)
    client = ApiFootballClient(
        settings,
        PayloadStore(tmp_path),
        transport=httpx.MockTransport(handler),
        rate_limiter=TokenBucket(settings.per_minute_limit, sleep=_no_sleep),
        quota=DailyQuota(budget=50),
    )
    provider = ApiFootballProvider(client)
    planner = CapturePlanner((4320, 1440, 720, 360, 180), 12, 45)
    return OddsCaptureService(conn, provider, planner), calls


@pytest.fixture()
def prepared(db: psycopg.Connection, seed: Seed) -> Iterator[psycopg.Connection]:
    """Align the seeded fixture and bookmaker with the mocked payload ids."""
    with db.cursor() as cur:
        cur.execute(
            "UPDATE core.fixtures SET provider_fixture_id = 1001, kickoff_at = %s WHERE id = %s",
            (KICKOFF, seed.fixture_id),
        )
    db.commit()
    yield db
    with db.cursor() as cur:
        cur.execute("DELETE FROM market.market_consensus")
        cur.execute("DELETE FROM market.odds_snapshots")
        cur.execute("DELETE FROM market.near_close_snapshots")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE hash <> 'h1'")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_name = 'odds_capture'")
    db.commit()


async def test_a_capture_writes_prices_payloads_and_a_run(
    prepared: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    service, calls = make_service(prepared, tmp_path, lambda _n: odds_body("2.10", "3.40", "3.60"))
    report = await service.capture([ScheduledFixture(1001, KICKOFF)])

    assert report.planned == 1
    assert report.executed == 1
    assert report.snapshots_written == 3
    assert report.status == "completed"
    assert calls["n"] == 1

    with prepared.cursor() as cur:
        cur.execute(
            "SELECT selection, odds_decimal, minutes_to_ko, source FROM market.odds_snapshots "
            "ORDER BY selection"
        )
        assert cur.fetchall() == [
            ("Away", Decimal("3.600"), 1439, "prematch"),
            ("Draw", Decimal("3.400"), 1439, "prematch"),
            ("Home", Decimal("2.100"), 1439, "prematch"),
        ]
        cur.execute("SELECT status, api_calls, rows_written FROM raw.ingestion_runs WHERE id = %s", (report.run_id,))
        assert cur.fetchone() == ("completed", 1, 3)
        cur.execute("SELECT count(*) FROM raw.ingestion_payloads WHERE run_id = %s", (report.run_id,))
        assert scalar(cur) == 1


async def test_running_the_same_window_twice_makes_no_second_call(
    prepared: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    """Idempotency, and the reason quota is not wasted on reruns."""
    service, calls = make_service(prepared, tmp_path, lambda _n: odds_body("2.10", "3.40", "3.60"))
    fixtures = [ScheduledFixture(1001, KICKOFF)]

    first = await service.capture(fixtures)
    second = await service.capture(fixtures)

    assert first.snapshots_written == 3
    assert second.planned == 0, "the window was already covered"
    assert second.executed == 0
    assert calls["n"] == 1, "the provider was called once, not twice"

    with prepared.cursor() as cur:
        cur.execute("SELECT count(*) FROM market.odds_snapshots")
        assert scalar(cur) == 3


async def test_a_later_window_appends_history_instead_of_overwriting_it(
    prepared: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    """The exact failure of the legacy schema: its UNIQUE had no temporal
    component, so the second capture replaced the first and the price history
    was permanently lost."""
    prices = [("2.10", "3.40", "3.60"), ("1.95", "3.60", "4.00")]
    service, _ = make_service(prepared, tmp_path, lambda n: odds_body(*prices[min(n, 2) - 1]))
    fixtures = [ScheduledFixture(1001, KICKOFF)]

    await service.capture(fixtures)
    clock.advance(minutes=1079)  # now at T-360, the 360-minute window
    await service.capture(fixtures)

    with prepared.cursor() as cur:
        cur.execute(
            "SELECT odds_decimal, minutes_to_ko FROM market.odds_snapshots "
            "WHERE selection = 'Home' ORDER BY captured_at"
        )
        assert cur.fetchall() == [(Decimal("2.100"), 1439), (Decimal("1.950"), 360)]


async def test_the_near_close_snapshot_is_recorded_without_claiming_to_be_a_close(
    prepared: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    clock.advance(minutes=1427)  # T-12: the /odds/live band
    service, _ = make_service(
        prepared, tmp_path, lambda _n: odds_body("1.90", "3.70", "4.20", scope="inplay")
    )
    report = await service.capture([ScheduledFixture(1001, KICKOFF)])

    assert report.near_close_written == 3
    with prepared.cursor() as cur:
        cur.execute(
            "SELECT selection, odds_decimal, minutes_to_ko, source, is_validated_close, "
            "       close_validation_method "
            "FROM market.near_close_snapshots WHERE selection = 'Home'"
        )
        assert cur.fetchone() == (
            "Home",
            Decimal("1.900"),
            12,
            "live",
            False,
            None,
        ), "a captured snapshot is near-close and unvalidated until proven otherwise"


async def test_a_closer_snapshot_replaces_a_more_distant_one_but_never_the_reverse(
    prepared: psycopg.Connection, tmp_path: Path
) -> None:
    repo = OddsRepository(prepared)
    from fbi.providers.base import OddsQuote

    def quote(odds: str, minutes: int) -> OddsQuote:
        return OddsQuote(
            provider_fixture_id=1001,
            provider_bookmaker_id=8,
            bookmaker_name="Bet365",
            market_key="1X2",
            selection="Home",
            line=Decimal("0"),
            odds_decimal=Decimal(odds),
            captured_at=KICKOFF - timedelta(minutes=minutes),
            minutes_to_ko=minutes,
            source="live",
            payload_hash="h1",
        )

    repo.upsert_near_close([quote("2.10", 30)])
    repo.upsert_near_close([quote("1.95", 12)])
    repo.upsert_near_close([quote("9.99", 240)])  # further away: must be ignored
    prepared.commit()

    with prepared.cursor() as cur:
        cur.execute("SELECT odds_decimal, minutes_to_ko FROM market.near_close_snapshots")
        assert cur.fetchone() == (Decimal("1.950"), 12)


async def test_prices_for_an_unknown_fixture_are_counted_not_silently_dropped(
    prepared: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    from fbi.providers.base import OddsQuote

    repo = OddsRepository(prepared)
    result = repo.write_snapshots(
        [
            OddsQuote(
                provider_fixture_id=999_999,
                provider_bookmaker_id=8,
                bookmaker_name="Bet365",
                market_key="1X2",
                selection="Home",
                line=Decimal("0"),
                odds_decimal=Decimal("2.10"),
                captured_at=KICKOFF - timedelta(minutes=100),
                minutes_to_ko=100,
                source="prematch",
                payload_hash="h1",
            )
        ]
    )
    assert result.written == 0
    assert result.skipped_unknown_fixture == 1


async def test_a_capture_computes_the_consensus_of_the_books_it_saw(
    prepared: psycopg.Connection, tmp_path: Path, clock: FrozenClock, seed: Seed
) -> None:
    from fbi.market.consensus import recompute_from_snapshots

    service, _ = make_service(prepared, tmp_path, lambda _n: odds_body("2.10", "3.40", "3.60"))
    report = await service.capture([ScheduledFixture(1001, KICKOFF)])
    assert report.consensus_written == 9, "three selections, three de-vig methods"
    with prepared.cursor() as cur:
        cur.execute(
            "SELECT devig_method, sum(p_fair), min(n_bookmakers), bool_and(dispersion IS NULL), "
            "count(DISTINCT as_of) FROM market.market_consensus WHERE fixture_id = %s GROUP BY devig_method",
            (seed.fixture_id,))
        for method, total, n_books, no_dispersion, instants in cur.fetchall():
            assert abs(float(total) - 1.0) < 1e-5, method
            assert n_books == 1 and no_dispersion, "one book has no spread to report"
            assert instants == 1
        cur.execute("SELECT as_of FROM market.market_consensus LIMIT 1")
        as_of = scalar(cur)
        cur.execute("SELECT max(captured_at) FROM market.odds_snapshots")
        assert as_of == scalar(cur), "the consensus is as of the capture, not of the computation"
    assert recompute_from_snapshots(prepared, fixture_ids=[seed.fixture_id]) == (1, 0), "idempotent"


async def test_a_live_body_numbered_like_a_prematch_one_yields_nothing(
    prepared: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    """The latent bug, reproduced end to end.

    /odds/live had never run, so nothing had ever exercised the in-play bet
    namespace. With one shared id map, this body - in-play bet 1, which is
    "Over/Under Extra Time" - would have been written into the near-close series
    as a 1X2 price. It must produce no rows at all instead.
    """
    clock.advance(minutes=1427)  # T-12: the /odds/live band
    service, _ = make_service(
        prepared, tmp_path, lambda _n: odds_body("1.90", "3.70", "4.20", scope="prematch")
    )
    report = await service.capture([ScheduledFixture(1001, KICKOFF)])

    assert report.api_calls == 1, "the request was made and the payload was stored"
    assert report.payloads_stored == 1, "the raw answer is kept whatever we could read from it"
    assert (report.quotes_seen, report.snapshots_written, report.near_close_written) == (0, 0, 0)
    with prepared.cursor() as cur:
        cur.execute("SELECT count(*) FROM market.near_close_snapshots")
        assert scalar(cur) == 0
