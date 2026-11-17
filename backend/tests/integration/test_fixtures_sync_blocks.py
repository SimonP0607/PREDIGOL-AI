"""OPS-006 against a real database: a large season no longer holds its rows for the whole sync.

On the server (16 Nov 2026) the club friendlies' season - 8,400 fixtures, 7,682 of them finished - was applied as one
transaction of about 30 minutes, every row rewritten even when the payload was byte for byte the one of six hours
before, and the in-play follow of any of those matches waited for the end. Here:

* a payload that confirms what the rows hold issues no per-row upsert and leaves exactly the rows the upsert left
  (content equal, lineage moved);
* a season is applied in committed blocks, so a concurrent in-play write waits for one block, not the season;
* a block that waits past ``LOCK_TIMEOUT`` is retried, and given up as an error of the run when the lock never comes.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion import fixtures as fx
from fbi.ingestion import results as rs
from fbi.ingestion.apply import apply_fixtures_payload
from fbi.ingestion.fixtures import (
    FixtureRepository,
    HeldFixture,
    SyncStrategy,
    sync_fixtures,
    tracked_season_ids,
)
from fbi.ingestion.results import ResultRepository
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.ratelimit import DailyQuota, TokenBucket
from fbi.storage.payload_store import PayloadStore
from tests.integration.helpers import scalar

SECRET = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
LEAGUE, SEASON = 66_700, 2026
FID0 = 9_000_000
TEAM0, VENUE0 = 700_000, 770_000
T1 = datetime(2026, 11, 16, 3, 41, tzinfo=UTC)
SEASON_SIZE, FINISHED = 8_400, 7_680


def entry(i: int, *, status: str | None = None, kickoff: datetime | None = None, round_: str | None = None,
          goals: tuple[int, int] | None = None) -> dict[str, Any]:
    """Fixture ``FID0 + i``: the first FINISHED are played (kick-off before T1), the rest are to come."""
    played = i <= FINISHED
    ko = kickoff or (T1 - timedelta(days=60) + timedelta(minutes=10 * i) if played else T1 + timedelta(days=1, hours=i % 48))
    st = status or ("FT" if played else "NS")
    g = goals if goals is not None else ((i % 4, i % 3) if st == "FT" else None)
    return {
        "fixture": {"id": FID0 + i, "date": ko.isoformat(), "status": {"short": st},
                    "venue": {"id": VENUE0 + i % 100 + 1, "name": f"Ground {i % 100}", "city": f"Town {i % 100}"}},
        "league": {"id": LEAGUE, "season": SEASON, "round": round_ or f"Club Friendlies {1 + i % 30}"},
        "teams": {"home": {"id": TEAM0 + 1 + i % 400, "name": f"Club {i % 400}"},
                  "away": {"id": TEAM0 + 1 + (i + 7) % 400, "name": f"Club {(i + 7) % 400}"}},
        "goals": {"home": g[0] if g else None, "away": g[1] if g else None},
        "score": {"halftime": {"home": None, "away": None},
                  "fulltime": {"home": g[0] if g else None, "away": g[1] if g else None},
                  "extratime": {"home": None, "away": None}, "penalty": {"home": None, "away": None}},
    }


def body(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"get": "fixtures", "parameters": {"league": str(LEAGUE), "season": str(SEASON)}, "errors": [],
            "results": len(entries), "paging": {"current": 1, "total": 1}, "response": entries}


def provider_for(tmp_path: Path, answer: Callable[[], dict[str, Any]]) -> ApiFootballProvider:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=answer())

    async def _no_sleep(_s: float) -> None:
        return None

    return ApiFootballProvider(ApiFootballClient(
        ApiFootballSettings(key=SECRET, plan="pro", daily_budget=50, max_retries=0),
        PayloadStore(tmp_path), transport=httpx.MockTransport(handler),
        rate_limiter=TokenBucket(300, sleep=_no_sleep), quota=DailyQuota(budget=50),
    ))


@pytest.fixture()
def clock() -> Iterator[FrozenClock]:
    c = FrozenClock(T1)
    set_clock(c)
    yield c
    set_clock(SystemClock())


@pytest.fixture()
def friendlies(db: psycopg.Connection, migrated_database: str) -> Iterator[psycopg.Connection]:
    """A tracked, current season of club friendlies (a non-league competition: its venues are classified)."""
    with db.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = false")
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                    "is_tracked) VALUES (%s, 'Friendlies Clubs', 'friendly', 'club', 'international', true) "
                    "RETURNING id", (LEAGUE,))
        comp = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, %s, true)",
                    (comp, SEASON))
    db.commit()
    yield db
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN %s AND %s", (FID0, FID0 + 99_999))
        cur.execute("DELETE FROM core.teams WHERE provider_team_id BETWEEN %s AND %s", (TEAM0, TEAM0 + 9_999))
        cur.execute("DELETE FROM core.venues WHERE provider_venue_id BETWEEN %s AND %s", (VENUE0, VENUE0 + 9_999))
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE run_id IN "
                    "(SELECT id FROM raw.ingestion_runs WHERE job_type IN ('fixtures_sync', 'ops006_live'))")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type IN ('fixtures_sync', 'ops006_live')")
        cur.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s", (comp,))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (comp,))
    db.commit()


def index_payload(conn: psycopg.Connection, payload_hash: str, fetched_at: datetime) -> str:
    """A payload index row, as a real fetch leaves (the fixtures' lineage references it)."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) "
                    "VALUES ('t', 'ops006_live', 'completed', now()) RETURNING id")
        run_id = scalar(cur)
        cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, "
                    "bytes) VALUES (%s, %s, '/fixtures', %s, 200, 'x', 1) ON CONFLICT (hash) DO NOTHING",
                    (payload_hash, run_id, fetched_at))
    return payload_hash


def content(conn: psycopg.Connection) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute("SELECT f.provider_fixture_id, f.competition_season_id, f.home_team_id, f.away_team_id, "
                    "f.kickoff_at, f.status_short, f.status_group, f.round, f.venue_id, f.venue_name, f.venue_city, "
                    "r.goals_home, r.goals_away, r.ft_goals_home, r.ft_goals_away FROM core.fixtures f "
                    "LEFT JOIN core.fixture_results r ON r.fixture_id = f.id "
                    "WHERE f.provider_fixture_id BETWEEN %s AND %s ORDER BY 1", (FID0, FID0 + 99_999))
        return cur.fetchall()


def lineage_at(conn: psycopg.Connection) -> dict[datetime | None, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT source_fetched_at, count(*) FROM core.fixtures WHERE provider_fixture_id BETWEEN %s AND %s "
                    "GROUP BY 1", (FID0, FID0 + 99_999))
        return {a: int(b) for a, b in cur.fetchall()}


class Spy:
    """Counts the calls of a method while delegating to it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, owner: Any, name: str) -> None:
        self.calls = 0
        original = getattr(owner, name)

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, staticmethod(wrapper) if isinstance(owner.__dict__[name], staticmethod)
                            else wrapper)


async def test_a_season_of_8400_is_written_in_blocks_equal_rows_are_not_rewritten_and_a_live_write_does_not_wait(
        friendlies: psycopg.Connection, migrated_database: str, tmp_path: Path, clock: FrozenClock,
        monkeypatch: pytest.MonkeyPatch) -> None:
    season = [entry(i) for i in range(1, SEASON_SIZE + 1)]
    current: list[dict[str, Any]] = [body(season)]
    provider = provider_for(tmp_path, lambda: current[0])

    t0 = time.monotonic()
    first = await sync_fixtures(friendlies, provider, strategy=SyncStrategy.LEAGUE)
    first_s = time.monotonic() - t0
    assert first.status == "completed" and (first.rows_inserted, first.errors) == (SEASON_SIZE, [])
    before = content(friendlies)
    assert len(before) == SEASON_SIZE and sum(1 for r in before if r[11] is not None) == FINISHED

    # -- the same body six hours later (what the server did at 15:41 on 16 Nov): no per-row write at all
    upserts = Spy(monkeypatch, FixtureRepository, "_upsert_one")
    scores = Spy(monkeypatch, ResultRepository, "_upsert_result")
    clock.advance(hours=6)
    t0 = time.monotonic()
    second = await sync_fixtures(friendlies, provider, strategy=SyncStrategy.LEAGUE)
    second_s = time.monotonic() - t0
    assert (upserts.calls, scores.calls) == (0, 0), "a payload that changes nothing issues no per-row upsert"
    assert second.status == "completed" and second.errors == []
    assert (second.rows_inserted, second.rows_updated) == (0, SEASON_SIZE + FINISHED), "counted as before: confirmed"
    assert content(friendlies) == before, "nothing of the content moved"
    assert lineage_at(friendlies) == {T1 + timedelta(hours=6): SEASON_SIZE}, "the lineage moved, every row"
    with friendlies.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixture_result_revisions v JOIN core.fixtures f ON f.id = v.fixture_id "
                    "WHERE f.provider_fixture_id BETWEEN %s AND %s", (FID0, FID0 + 99_999))
        assert scalar(cur) == 0, "no revision: nothing was corrected"

    # -- three real changes, and the in-play follow writing 20 of the season's matches while the sync runs
    changed = list(season)
    changed[0] = entry(1, kickoff=T1 - timedelta(days=60, hours=-2))                      # moved
    changed[FINISHED] = entry(FINISHED + 1, status="FT", kickoff=T1 - timedelta(hours=3),  # played meanwhile
                              goals=(1, 1))
    changed[FINISHED + 1] = entry(FINISHED + 2, round_="Club Friendlies 99")              # renamed round
    current[0] = body(changed)
    clock.advance(hours=6)
    sync_at = T1 + timedelta(hours=12)
    live_ids = list(range(SEASON_SIZE - 19, SEASON_SIZE + 1))  # the season's last block: written last by the sync
    live_at = sync_at + timedelta(minutes=1)
    live_body = body([entry(i, status="1H", kickoff=live_at - timedelta(minutes=20)) for i in live_ids])
    timing: dict[str, float] = {}

    def live_follow() -> None:
        with psycopg.connect(migrated_database) as live:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:  # once the sync has committed its first block
                with live.cursor() as cur:
                    cur.execute("SELECT count(*) FROM core.fixtures WHERE source_fetched_at = %s", (sync_at,))
                    if (scalar(cur) or 0) > 0:
                        break
                live.rollback()
                time.sleep(0.02)
            live.rollback()
            index_payload(live, "live-ops006", live_at)
            live.commit()
            started = time.monotonic()
            apply_fixtures_payload(live, provider, live_body, payload_hash="live-ops006", fetched_at=live_at,
                                   season_ids=tracked_season_ids(live))
            live.commit()
            timing["live_s"] = time.monotonic() - started
            timing["live_done"] = time.monotonic()

    upserts.calls = scores.calls = 0
    follower = threading.Thread(target=live_follow)
    follower.start()
    third = await sync_fixtures(friendlies, provider, strategy=SyncStrategy.LEAGUE)
    sync_done = time.monotonic()
    follower.join(130)
    assert "live_s" in timing, "the in-play write finished"
    print(f"\nOPS-006 local: first sync {first_s:.1f} s, unchanged resync {second_s:.1f} s, "
          f"in-play write during the third {timing['live_s']:.2f} s")
    assert third.status == "completed" and third.errors == []
    assert timing["live_s"] < 30, "the in-play write waited for one block at most, not for the season"
    assert timing["live_done"] <= sync_done
    # the three changes; the follow's own 20 (a new status); and, when the follow wrote first, the sync's older reading
    # of those 20, which the upsert declines
    assert upserts.calls in (3 + len(live_ids), 3 + 2 * len(live_ids))
    assert scores.calls == 1, "one new score"
    after = {r[0]: r for r in content(friendlies)}
    assert after[FID0 + 1][4] == T1 - timedelta(days=60, hours=-2)
    assert after[FID0 + FINISHED + 1][5:7] == ("FT", "finished") and after[FID0 + FINISHED + 1][11:13] == (1, 1)
    assert after[FID0 + FINISHED + 2][7] == "Club Friendlies 99"
    with friendlies.cursor() as cur:
        cur.execute("SELECT count(*) FROM core.fixtures WHERE provider_fixture_id = ANY(%s) AND status_short = '1H' "
                    "AND source_fetched_at = %s", ([FID0 + i for i in live_ids], live_at))
        assert scalar(cur) == len(live_ids), "the follow's newer reading stands: the older sync did not undo it"
        cur.execute("SELECT count(*) FROM core.fixture_kickoff_changes k JOIN core.fixtures f ON f.id = k.fixture_id "
                    "WHERE f.provider_fixture_id = %s", (FID0 + 1,))
        assert scalar(cur) == 1, "the move is kept, as before"


def small(i: int, **kw: Any) -> dict[str, Any]:
    """A played match of last week: the season stays current (``active_seasons``)."""
    return entry(i, **{"kickoff": T1 - timedelta(days=7) + timedelta(hours=i), **kw})


def small_season(n: int, **kw: Any) -> list[dict[str, Any]]:
    return [small(i, **kw) for i in range(1, n + 1)]


def _hold_lock(dsn: str, provider_fixture_id: int, seconds: float, held: threading.Event) -> None:
    with psycopg.connect(dsn) as other:
        other.execute("SELECT 1 FROM core.fixtures WHERE provider_fixture_id = %s FOR UPDATE", (provider_fixture_id,))
        held.set()
        time.sleep(seconds)
        other.rollback()


async def test_a_block_that_meets_a_held_row_is_retried_and_applied(
        friendlies: psycopg.Connection, migrated_database: str, tmp_path: Path, clock: FrozenClock,
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx, "FIXTURE_BLOCK", 2)
    monkeypatch.setattr(fx, "LOCK_TIMEOUT", "200ms")
    monkeypatch.setattr(fx, "LOCK_RETRY_PAUSES_S", (0.3, 0.3, 0.3, 0.3))
    current = [body(small_season(6))]
    provider = provider_for(tmp_path, lambda: current[0])
    await sync_fixtures(friendlies, provider, strategy=SyncStrategy.LEAGUE)

    current[0] = body(small_season(6, round_="Moved round"))
    clock.advance(hours=6)
    held = threading.Event()
    holder = threading.Thread(target=_hold_lock, args=(migrated_database, FID0 + 4, 0.8, held))
    holder.start()
    assert held.wait(10)
    seen: list[dict[str, Any]] = []

    class _Recorder:
        """The module's own logger, recorded directly: ``capture_logs`` misses a logger cached before it (CI, 4 workers)."""

        def __getattr__(self, level: str) -> Any:
            def emit(event: str, **kw: Any) -> None:
                seen.append({"event": event, **kw})
            return emit

    monkeypatch.setattr(fx, "log", _Recorder())
    counters = await sync_fixtures(friendlies, provider, strategy=SyncStrategy.LEAGUE)
    holder.join(10)
    waits = [e for e in seen if e["event"] == "fixtures.block_lock_wait"]
    assert waits and {e["block"] for e in waits} == {f"league {LEAGUE} block 2/3"}, "the held block waited, and only it"
    assert counters.status == "completed" and counters.errors == []
    assert {r[7] for r in content(friendlies)} == {"Moved round"}, "every block, the waiting one too, was applied"


async def test_a_block_that_never_gets_its_lock_is_given_up_and_the_others_are_applied(
        friendlies: psycopg.Connection, migrated_database: str, tmp_path: Path, clock: FrozenClock,
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fx, "FIXTURE_BLOCK", 2)
    monkeypatch.setattr(fx, "LOCK_TIMEOUT", "100ms")
    monkeypatch.setattr(fx, "LOCK_RETRY_PAUSES_S", (0.05, 0.05))
    current = [body(small_season(6))]
    provider = provider_for(tmp_path, lambda: current[0])
    await sync_fixtures(friendlies, provider, strategy=SyncStrategy.LEAGUE)

    current[0] = body(small_season(6, round_="Moved round"))
    clock.advance(hours=6)
    held = threading.Event()
    holder = threading.Thread(target=_hold_lock, args=(migrated_database, FID0 + 4, 3.0, held))
    holder.start()
    assert held.wait(10)
    counters = await sync_fixtures(friendlies, provider, strategy=SyncStrategy.LEAGUE)
    holder.join(10)
    assert counters.status == "partial"
    assert len(counters.errors) == 1 and "block 2/3" in counters.errors[0] and "gave up" in counters.errors[0]
    rounds = {r[0] - FID0: r[7] for r in content(friendlies)}
    assert [k for k, v in rounds.items() if v != "Moved round"] == [3, 4], "only the held block waits for next time"


def _snapshot(conn: psycopg.Connection) -> tuple[Any, ...]:
    with conn.cursor() as cur:
        cur.execute("SELECT f.*, r.goals_home, r.goals_away, r.source_payload_hash, r.source_fetched_at "
                    "FROM core.fixtures f LEFT JOIN core.fixture_results r ON r.fixture_id = f.id "
                    "WHERE f.provider_fixture_id BETWEEN %s AND %s ORDER BY f.provider_fixture_id", (FID0, FID0 + 99_999))
        fixtures = cur.fetchall()
        cur.execute("SELECT count(*) FROM core.fixture_kickoff_changes k JOIN core.fixtures f ON f.id = k.fixture_id "
                    "WHERE f.provider_fixture_id BETWEEN %s AND %s", (FID0, FID0 + 99_999))
        moves = scalar(cur)
        cur.execute("SELECT count(*) FROM core.fixture_result_revisions v JOIN core.fixtures f ON f.id = v.fixture_id "
                    "WHERE f.provider_fixture_id BETWEEN %s AND %s", (FID0, FID0 + 99_999))
        revisions = scalar(cur)
    return tuple(fixtures), moves, revisions


async def test_the_rows_left_are_the_ones_the_full_upsert_leaves(
        friendlies: psycopg.Connection, tmp_path: Path, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Differential: the same payloads through the new path and through the per-row upsert alone give the same rows,
    lineage, trail and revisions."""
    provider = provider_for(tmp_path, lambda: {})
    seasons = tracked_season_ids(friendlies)
    for h, at in (("p0", T1 - timedelta(hours=6)), ("p1", T1), ("p2", T1 + timedelta(hours=6))):
        index_payload(friendlies, h, at)
    apply_fixtures_payload(friendlies, provider, body(small_season(12)), payload_hash="p1", fetched_at=T1,
                           season_ids=seasons)
    friendlies.commit()
    later = body([
        small(1), small(2, round_=None), small(3, kickoff=T1 - timedelta(days=2)),       # equal, equal (kept), moved
        small(4, goals=(3, 3)),                                                          # a corrected score
        small(5, status="AET"), small(11, status="PST"),                                 # a new status, postponed
        small(6), small(6, round_="Twice"),                                              # listed twice
        small(7), small(8), small(9), small(10), small(12),
    ])

    def run() -> tuple[Any, ...]:
        apply_fixtures_payload(friendlies, provider, later, payload_hash="p2", fetched_at=T1 + timedelta(hours=6),
                               season_ids=seasons)
        # an older payload than what the rows hold: changes nothing either way
        apply_fixtures_payload(friendlies, provider, body(small_season(12)), payload_hash="p0",
                               fetched_at=T1 - timedelta(hours=6), season_ids=seasons)
        return _snapshot(friendlies)

    friendlies.execute("SAVEPOINT before")
    new = run()
    friendlies.execute("ROLLBACK TO SAVEPOINT before")
    monkeypatch.setattr(HeldFixture, "same_as", lambda *_a, **_k: False)
    monkeypatch.setattr(rs, "_same_score", lambda *_a, **_k: False)
    old = run()
    assert new == old
    assert new[1] == 1, "the move is kept"
    assert new[2] >= 1, "the corrected score is a revision"


# ------------------------------------------------------------------ the pulse, on the real table


def test_the_pulse_keeps_a_worker_whose_loop_is_held_alive_and_never_revives_a_stopped_one(
        db: psycopg.Connection, migrated_database: str) -> None:
    """The tick has not beaten for 20 minutes (a held loop): without the pulse the worker reads as dead and is
    restarted; with it, alive - while its last tick still shows how old it is. After a clean stop no pulse counts."""
    from fbi.core.clock import now
    from fbi.ops.heartbeat import HeartbeatWriter, LivenessPulse, latest_heartbeat

    worker = "ops006-host:worker"
    try:
        w = HeartbeatWriter(db, worker_id=worker, tick_interval_s=300, code_version="ops006")
        w.started()
        w.beat(outcome="nothing_due", duration_ms=10, lag_ms=0)
        db.execute("UPDATE raw.worker_heartbeats SET last_beat_at = now() - interval '20 minutes', "
                   "last_tick_at = now() - interval '20 minutes' WHERE worker_id = %s", (worker,))
        db.commit()
        beat = latest_heartbeat(db)
        assert beat is not None and not beat.is_alive(), "a held loop reads as a dead worker"

        pulse = LivenessPulse(lambda: psycopg.connect(migrated_database), worker_id=worker)
        assert pulse.pulse_once()
        db.rollback()
        beat = latest_heartbeat(db)
        assert beat is not None and beat.is_alive()
        assert beat.last_tick_at is not None and now() - beat.last_tick_at > timedelta(minutes=19), (
            "the tick's own record is untouched")
        assert beat.ticks == 1

        w.stopped()
        stopped_at = latest_heartbeat(db).stopped_at  # type: ignore[union-attr]
        assert pulse.pulse_once(), "the write ran"
        db.rollback()
        beat = latest_heartbeat(db)
        assert beat is not None and not beat.is_alive() and beat.stopped_at == stopped_at
        pulse.stop()
    finally:
        db.rollback()
        db.execute("DELETE FROM raw.worker_heartbeats WHERE worker_id = %s", (worker,))
        db.commit()
