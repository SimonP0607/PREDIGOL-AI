"""OPS-006: a long fixtures sync no longer stops the in-play follow or the heartbeat.

From 13 to 15 Nov 2026 the server's check restarted the worker seven times, each inside a fixtures sync: the club
friendlies' season (8,400 fixtures) was one transaction of about 30 minutes, the in-play follow waited on its rows on
the scheduler's loop, and the heartbeat - written on that loop - stopped. These tests hold the four repairs without a
database: equal rows are told apart from changed ones, a payload is applied in blocks, a block that waited too long for
a lock is retried, and the pulse beats on its own thread.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime
from typing import Any

import psycopg
import psycopg.errors
import pytest
from apps.worker import scheduler

from fbi.ingestion import apply as apply_mod
from fbi.ingestion import fixtures as fx
from fbi.ingestion.apply import PayloadOutcome
from fbi.ingestion.fixtures import HeldFixture
from fbi.ingestion.ledger import RunCounters
from fbi.ingestion.results import _same_score
from fbi.ops.heartbeat import LivenessPulse
from fbi.providers.base import FixtureRef, FixtureResultRef, RawResponse

KICKOFF = datetime(2026, 11, 16, 19, 0, tzinfo=UTC)
TEAMS = {101: 11, 102: 12}


def ref(**over: Any) -> FixtureRef:
    base: dict[str, Any] = {
        "provider_fixture_id": 1, "provider_league_id": 667, "season": 2026, "kickoff_at": KICKOFF,
        "provider_home_team_id": 101, "provider_away_team_id": 102, "status_short": "FT",
        "round": "Club Friendlies 3", "provider_venue_id": 55, "venue_name": "Ground", "venue_city": "Town"}
    base.update(over)
    return FixtureRef(**base)


def held(**over: Any) -> HeldFixture:
    base: dict[str, Any] = {
        "id": 7, "home_team_id": 11, "away_team_id": 12, "kickoff_at": KICKOFF, "competition_season_id": 3,
        "status_short": "FT", "status_group": "finished", "round": "Club Friendlies 3", "venue_id": 5,
        "venue_name": "Ground", "venue_city": "Town", "version": "123"}
    base.update(over)
    return HeldFixture(**base)


# ------------------------------------------------------------------ equal rows


def test_a_ref_that_says_what_the_row_holds_is_equal() -> None:
    assert held().same_as(ref(), 3, TEAMS, 5)


def test_what_the_upsert_keeps_from_the_row_counts_as_equal() -> None:
    """An absent round, venue, name or city is kept by the upsert (COALESCE): nothing changes."""
    assert held().same_as(ref(round=None, venue_name=None, venue_city=None, provider_venue_id=None), 3, TEAMS, None)


@pytest.mark.parametrize(("r", "season", "venue"), [
    (ref(kickoff_at=datetime(2026, 11, 16, 20, 0, tzinfo=UTC)), 3, 5),   # moved
    (ref(status_short="AET"), 3, 5),                                     # status
    (ref(round="Club Friendlies 4"), 3, 5),                              # round
    (ref(), 4, 5),                                                       # another competition season
    (ref(provider_home_team_id=102, provider_away_team_id=101), 3, 5),   # the sides
    (ref(), 3, 6),                                                       # another venue (maybe a repaired one)
    (ref(venue_city="Other town"), 3, 5),                                # another city (maybe a repaired one)
    (ref(venue_name="New name"), 3, 5),
])
def test_anything_the_upsert_would_change_is_not_equal(r: FixtureRef, season: int, venue: int) -> None:
    assert not held().same_as(r, season, TEAMS, venue)


def test_a_score_is_equal_only_to_the_same_score_of_an_existing_row() -> None:
    r = FixtureResultRef(provider_fixture_id=1, status_short="FT", goals_home=2, goals_away=1, ht_goals_home=1,
                         ht_goals_away=0, ft_goals_home=2, ft_goals_away=1)
    stored = (7, 2, 1, 1, 0, 2, 1, None, None, None, None, "991")
    assert _same_score(stored, r)
    assert not _same_score((7, 2, 2, 1, 0, 2, 2, None, None, None, None, "991"), r)
    assert not _same_score((None,) * 11 + (None,), r), "no result row yet: an insert"


def test_a_fixture_listed_twice_is_never_taken_as_equal() -> None:
    assert fx._repeated([1, 2, 3, 2, 4, 1]) == {1, 2}


# ------------------------------------------------------------------ blocks and lock waits


class FakeConn:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.commits = 0
        self.rollbacks = 0
        self.executed: list[tuple[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture()
def no_pauses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx, "LOCK_RETRY_PAUSES_S", (0.0, 0.0, 0.0))


async def test_a_block_that_waited_too_long_is_rolled_back_and_tried_again(no_pauses: None) -> None:
    conn = FakeConn()
    calls = 0

    def step() -> str:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise psycopg.errors.LockNotAvailable("canceling statement due to lock timeout")
        return "done"

    counters = RunCounters()
    assert await fx._in_block(conn, "league 667 block 3/34", step, counters) == "done"  # type: ignore[arg-type]
    assert (calls, conn.rollbacks, conn.commits) == (3, 2, 1)
    assert counters.errors == []
    timeouts = [p for sql, p in conn.executed if "lock_timeout" in sql]
    assert timeouts == [(fx.LOCK_TIMEOUT,)] * 3, "every attempt runs with the timeout, local to its transaction"


async def test_a_block_that_never_gets_its_lock_is_given_up_as_an_error_of_the_run(no_pauses: None) -> None:
    conn = FakeConn()

    def step() -> str:
        raise psycopg.errors.DeadlockDetected("deadlock detected")

    counters = RunCounters()
    assert await fx._in_block(conn, "league 667 block 3/34", step, counters) is None  # type: ignore[arg-type]
    assert conn.rollbacks == len(fx.LOCK_RETRY_PAUSES_S) + 1 and conn.commits == 0
    assert counters.errors and "gave up" in counters.errors[0] and "block 3/34" in counters.errors[0]


async def test_any_other_error_is_not_swallowed(no_pauses: None) -> None:
    def step() -> str:
        raise psycopg.errors.CheckViolation("a value the table refuses")

    with pytest.raises(psycopg.errors.CheckViolation):
        await fx._in_block(FakeConn(), "x", step, RunCounters())  # type: ignore[arg-type]


def _raw(n: int) -> RawResponse:
    body = {"get": "fixtures", "parameters": {"league": "667", "season": "2026"}, "errors": [], "results": n,
            "paging": {"current": 1, "total": 1}, "response": [{"fixture": {"id": i}} for i in range(n)]}
    return RawResponse(endpoint="/fixtures", params={}, fetched_at=KICKOFF, http_status=200, results_count=n,
                       payload_hash="h" * 64, file_path="x", bytes_written=1, body=body)


async def test_a_season_is_applied_in_blocks_and_classified_once_every_block_is_in(
        monkeypatch: pytest.MonkeyPatch, no_pauses: None) -> None:
    order: list[str] = []
    seen: list[int] = []

    def fake_apply(_conn: Any, _provider: Any, body: dict[str, Any], **kw: Any) -> PayloadOutcome:
        assert kw["classify"] is False, "the verdicts wait for the whole payload"
        assert {k for k in body if k != "response"} == {"get", "parameters", "errors", "results", "paging"}
        ids = [e["fixture"]["id"] for e in body["response"]]
        seen.extend(ids)
        order.append(f"apply {len(ids)}")
        return PayloadOutcome(seen=len(ids), ours=len(ids), fixtures_inserted=0, fixtures_updated=len(ids),
                              finished_seen=len(ids), results_written=len(ids), fixtures_unchanged=len(ids),
                              ours_ids=tuple(ids))

    def fake_classify(_conn: Any, ids: list[int], **kw: Any) -> int:
        order.append(f"classify {len(ids)}")
        assert kw["ref"] == "REF" and psycopg.errors.LockNotAvailable in kw["reraise"]
        return 1

    loads: list[int] = []

    def fake_reference(_conn: Any, ids: list[int]) -> str:
        loads.append(len(ids))
        return "REF"

    monkeypatch.setattr(apply_mod, "apply_fixtures_payload", fake_apply)
    monkeypatch.setattr(apply_mod, "_classify_venues", fake_classify)
    monkeypatch.setattr("fbi.catalog.neutral_store.reference_for", fake_reference)
    conn = FakeConn()
    counters = RunCounters()
    out = await fx._apply(conn, object(), _raw(8400), {}, counters, what="league 667")  # type: ignore[arg-type]

    blocks = -(-8400 // fx.FIXTURE_BLOCK)
    assert seen == list(range(8400)), "every entry once, in payload order"
    assert order[:blocks] == [f"apply {fx.FIXTURE_BLOCK}"] * (blocks - 1) + [f"apply {8400 - fx.FIXTURE_BLOCK * (blocks - 1)}"]
    assert all(o.startswith("classify") for o in order[blocks:]) and len(order) - blocks == -(-8400 // fx.CLASSIFY_BLOCK)
    assert loads == [8400], "the rule's reference is loaded once for the payload"
    assert conn.commits == 1 + blocks + (len(order) - blocks), "the index row, then one commit per block"
    assert (out.ours, out.fixtures_updated, out.fixtures_unchanged, out.venue_verdicts_written) == (8400, 8400, 8400,
                                                                                                    len(order) - blocks)
    assert (counters.rows_normalized, counters.rows_updated) == (8400, 16800)


async def test_a_small_payload_is_one_block(monkeypatch: pytest.MonkeyPatch, no_pauses: None) -> None:
    sizes: list[int] = []

    def fake_apply(_conn: Any, _provider: Any, body: dict[str, Any], **_kw: Any) -> PayloadOutcome:
        sizes.append(len(body["response"]))
        return PayloadOutcome(seen=0, ours=0, fixtures_inserted=0, fixtures_updated=0, finished_seen=0,
                              results_written=0)

    monkeypatch.setattr(apply_mod, "apply_fixtures_payload", fake_apply)
    await fx._apply(FakeConn(), object(), _raw(20), {}, RunCounters(), what="date")  # type: ignore[arg-type]
    assert sizes == [20]


# ------------------------------------------------------------------ the pulse


class PulseConn:
    def __init__(self, log: list[Any]) -> None:
        self.log = log
        self.closed = False
        self.autocommit = False

    def cursor(self) -> PulseConn:
        return self

    def __enter__(self) -> PulseConn:
        return self

    def __exit__(self, *_a: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        if "UPDATE raw.worker_heartbeats" in sql:
            assert "stopped_at IS NULL" in sql, "a late pulse must never revive a worker that announced its stop"
            self.log.append(params)

    def close(self) -> None:
        self.closed = True


def _loop_in_thread() -> tuple[asyncio.AbstractEventLoop, threading.Thread]:
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    return loop, t


def test_the_pulse_beats_while_the_scheduler_loop_is_held() -> None:
    """The failure of 13-15 Nov: a job held the loop and the beat, written on it, stopped. The pulse does not."""
    beats: list[Any] = []
    loop, thread = _loop_in_thread()
    pulse = LivenessPulse(lambda: PulseConn(beats), worker_id="host:worker",  # type: ignore[arg-type, return-value]
                          loop=loop, every_s=0.05, stall_s=30)
    release = threading.Event()
    loop.call_soon_threadsafe(lambda: release.wait(5))  # blocking work on the loop, like a lock wait
    try:
        pulse.start()
        time.sleep(0.6)
        assert len(beats) >= 5, "it beat while the loop was held"
        assert pulse.loop_lag_s() >= 0.5
    finally:
        release.set()
        pulse.stop()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()
    assert all(p[1] == "host:worker" for p in beats)


def test_the_pulse_goes_quiet_when_the_loop_runs_nothing_for_too_long() -> None:
    """A stuck loop is still a dead worker: past the stall limit the pulse withholds its beat."""
    beats: list[Any] = []
    t = [0.0]
    loop = asyncio.new_event_loop()  # never run: nothing scheduled on it ever executes
    pulse = LivenessPulse(lambda: PulseConn(beats), worker_id="w", loop=loop,  # type: ignore[arg-type, return-value]
                          stall_s=600, clock=lambda: t[0])
    try:
        assert pulse.pulse_once()
        t[0] = 599
        assert pulse.pulse_once()
        t[0] = 601
        assert not pulse.pulse_once()
        assert len(beats) == 2
    finally:
        loop.close()
    assert not pulse.pulse_once(), "a closed loop vouches for nothing"


def test_the_pulse_beats_only_while_the_scheduler_runs() -> None:
    beats: list[Any] = []
    running = [True]
    pulse = LivenessPulse(lambda: PulseConn(beats), worker_id="w",  # type: ignore[arg-type, return-value]
                          healthy=lambda: running[0])
    assert pulse.pulse_once()
    running[0] = False
    assert not pulse.pulse_once()
    assert len(beats) == 1


def test_a_failed_write_reconnects_at_the_next_pulse() -> None:
    beats: list[Any] = []
    attempts = [0]

    def connect() -> PulseConn:
        attempts[0] += 1
        if attempts[0] == 1:
            raise psycopg.OperationalError("database restarting")
        return PulseConn(beats)

    pulse = LivenessPulse(connect, worker_id="w")  # type: ignore[arg-type]
    assert not pulse.pulse_once()
    assert pulse.pulse_once()
    assert attempts[0] == 2 and len(beats) == 1


def test_nothing_beats_after_stop() -> None:
    beats: list[Any] = []
    pulse = LivenessPulse(lambda: PulseConn(beats), worker_id="w", every_s=0.02)  # type: ignore[arg-type, return-value]
    pulse.start()
    time.sleep(0.15)
    pulse.stop()
    n = len(beats)
    time.sleep(0.1)
    assert n >= 1 and len(beats) == n


# ------------------------------------------------------------------ the scheduler


def test_the_in_play_follow_runs_on_a_loop_of_its_own() -> None:
    assert "live_match_capture" in scheduler.OWN_LOOP_JOBS
    assert "fixtures_sync" in scheduler.OWN_LOOP_JOBS
    assert "odds_capture" not in scheduler.OWN_LOOP_JOBS and "live_odds_capture" not in scheduler.OWN_LOOP_JOBS


def test_what_a_job_on_its_own_loop_starts_beside_itself_runs_on_the_scheduler_loop(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The settlement after the follow: started on the follow's own loop, it would end with that loop."""
    main, thread = _loop_in_thread()
    monkeypatch.setattr(scheduler, "_main_loop", main)
    ran_on: list[asyncio.AbstractEventLoop] = []
    done = threading.Event()

    def fn() -> None:
        ran_on.append(asyncio.get_running_loop())
        done.set()

    async def job_on_its_own_loop() -> None:
        scheduler._on_main_loop(fn)

    try:
        asyncio.run(job_on_its_own_loop())
        assert done.wait(5)
        assert ran_on == [main]
    finally:
        main.call_soon_threadsafe(main.stop)
        thread.join(5)
        main.close()
