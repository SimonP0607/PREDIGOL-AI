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
from fbi.odds.capture import CaptureReport, OddsCaptureService
from fbi.odds.repository import OddsRepository
from fbi.odds.schedule import CapturePlanner, CaptureTask, ScheduledFixture
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.normalize import INPLAY_BETS, PREMATCH_BETS
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.base import OddsParseLog
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
    # near-close planning on: these tests drive the live-odds path itself.
    planner = CapturePlanner((4320, 1440, 720, 360, 180), 12, 45, plan_near_close=True)
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
        # near-close first: it holds a foreign key onto the series it projects.
        cur.execute("DELETE FROM market.near_close_snapshots")
        cur.execute("DELETE FROM market.odds_snapshots")
        # Quality issues reference the payloads that produced them, and that is
        # the point of them: they go first.
        cur.execute("DELETE FROM audit.data_quality_issues")
        cur.execute("DELETE FROM market.provider_markets WHERE source = 'observed'")
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


async def test_the_prematch_capture_refuses_a_near_close_task(
    prepared: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    """It used to serve this task from /odds/live.

    /odds/live was then measured to return ONLY matches already in play: one
    unfiltered call gave 11 fixtures, every one between the 6th and 93rd minute,
    and two fixtures probed at T-14 and T-9 returned results: 0 with no errors.
    So every row this path would have written was an in-play price filed in
    market.odds_snapshots, which the model and the backtest read as pre-match.

    The planner no longer emits the kind. If one ever arrives, the capture fails
    here rather than mixing the two series, and the in-play pipeline
    (odds.live_capture) is where those prices belong.
    """
    clock.advance(minutes=1427)  # T-12: what used to be the /odds/live band
    service, calls = make_service(
        prepared, tmp_path, lambda _n: odds_body("1.90", "3.70", "4.20", scope="inplay")
    )
    task = CaptureTask(
        provider_fixture_id=1001, kickoff_at=KICKOFF, kind="near_close",
        window_minutes=12, minutes_to_ko=12,
    )
    report = CaptureReport(run_id=1)
    with pytest.raises(ValueError, match="not served by the pre-match capture"):
        await service._capture_one(task, report)

    assert calls["n"] == 0, "it must fail before spending a request"
    with prepared.cursor() as cur:
        cur.execute("SELECT count(*) FROM market.near_close_snapshots")
        assert scalar(cur) == 0
        cur.execute("SELECT count(*) FROM market.odds_snapshots WHERE source = 'live'")
        assert scalar(cur) == 0


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

    # Every projection must have a series row behind it - that is the point of
    # the composite foreign key - so the series is written first, as capture does.
    for q in (quote("2.10", 30), quote("1.95", 12), quote("9.99", 240)):
        repo.write_snapshots([q])
        repo.upsert_near_close([q])
    prepared.commit()  # the last one is further away and must be ignored

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


async def test_a_live_body_numbered_like_a_prematch_one_yields_no_mapped_price(
    prepared: psycopg.Connection, tmp_path: Path
) -> None:
    """The latent bug, now exercised where live odds actually arrive.

    With one shared id map, in-play bet 1 - "Over/Under Extra Time" - would have
    been read as a 1X2 price. The in-play boundary must not map it to any market
    of ours. It still STORES it, with market_key NULL and the provider's own
    words, because /odds/live keeps no history and a dropped row is gone: that
    is the difference between the two pipelines, not an inconsistency.
    """
    from fbi.providers.api_football.live import iter_live_odds

    body = {
        "response": [
            {
                "fixture": {"id": 1001, "status": {"long": "Second Half",
                                                   "elapsed": 60, "seconds": "60:00"}},
                "teams": {"home": {"id": 33, "goals": 1}, "away": {"id": 40, "goals": 0}},
                "status": {"stopped": False, "blocked": False, "finished": False},
                "update": "2026-10-01T01:14:30+00:00",
                "odds": [
                    {
                        # The PRE-MATCH 1X2 id, on a live payload.
                        "id": PREMATCH_BETS["1X2"].bet_id,
                        "name": PREMATCH_BETS["1X2"].name,
                        "values": [{"value": "Home", "odd": "1.90"}],
                    }
                ],
            }
        ]
    }
    parse_log = OddsParseLog()
    states, quotes, markets = iter_live_odds(
        body, captured_at=KICKOFF, payload_hash="h1", parse_log=parse_log
    )
    assert len(states) == 1
    assert [q.market_key for q in quotes] == [None], "not mapped to any market of ours"
    assert quotes[0].provider_bet_id == PREMATCH_BETS["1X2"].bet_id
    assert parse_log.unmapped_bets[(1, "Match Winner")] == 1
    assert [m.provider_bet_id for m in markets] == [1]


async def test_a_bet_we_do_not_model_is_registered_rather_than_skipped(
    prepared: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    """Refusing to store an unmapped bet is right; refusing silently is not.

    The bet lands in the provider catalogue as 'observed' and in the quality
    registry, so "we do not model this" stops looking like "we lost this".
    """
    body = odds_body("1.90", "3.70", "4.20")
    # Bet 17 is a real pre-match bet we do not model. On the pre-match endpoint,
    # in the pre-match namespace - no cross-endpoint trickery needed to make the
    # point any more.
    body["response"][0]["bookmakers"][0]["bets"][0]["id"] = 17
    body["response"][0]["bookmakers"][0]["bets"][0]["name"] = "Home Team Score a Goal"
    service, _ = make_service(prepared, tmp_path, lambda _n: body)
    report = await service.capture([ScheduledFixture(1001, KICKOFF)])

    assert (report.snapshots_written, report.quality_issues_opened) == (0, 1)
    assert report.provider_bets_newly_observed == 1
    with prepared.cursor() as cur:
        cur.execute("SELECT code, entity_type, provider_entity_id, observed, "
                    "       payload_hash IS NOT NULL "
                    "FROM audit.data_quality_issues")
        assert cur.fetchall() == [
            ("UNKNOWN_PROVIDER_ENTITY", "provider_market", 17,
             "Home Team Score a Goal", True)
        ]
        cur.execute("SELECT scope, name, market_key, source "
                    "FROM market.provider_markets WHERE source = 'observed'")
        assert cur.fetchall() == [
            ("prematch", "Home Team Score a Goal", None, "observed")
        ]


async def test_an_unreadable_price_is_recorded_with_the_provider_s_own_words(
    prepared: psycopg.Connection, tmp_path: Path, clock: FrozenClock
) -> None:
    body = odds_body("1.90", "3.70", "4.20")
    body["response"][0]["bookmakers"][0]["bets"][0]["values"].append(
        {"value": "Sideways", "odd": "2.00"}
    )
    service, _ = make_service(prepared, tmp_path, lambda _n: body)
    report = await service.capture([ScheduledFixture(1001, KICKOFF)])

    assert report.snapshots_written == 3, "the three readable prices are kept"
    assert report.quality_issues_opened == 1
    with prepared.cursor() as cur:
        cur.execute("SELECT code, field, observed, expected FROM audit.data_quality_issues")
        assert cur.fetchall() == [
            ("NORMALIZATION_REJECTED", "1X2", "Sideways", "not a selection of this market")
        ]
