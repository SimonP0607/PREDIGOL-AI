"""Plan F0, defect 9: the newest payload wins, at every level, also when two writers meet on one fixture.

``apply_fixture_details`` skips a payload older than anything applied for the fixture. But the check and the writes that
follow it were not one unit: a writer that read "nothing newer" before another writer committed a newer payload then
wrote its OLDER line-up over it (the line-up upsert had no ``fetched_at`` guard, unlike the team and player statistics).
Rows are committed here, because the point is two connections; everything is removed afterwards.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import psycopg
import pytest

from fbi.ingestion.details import LOCK_PREFIX, apply_fixture_details
from fbi.providers.api_football.details import (
    EventRef,
    FixtureDetail,
    LineupPlayerRef,
    LineupRef,
    TeamStatsRef,
)

from .conftest import Seed
from .helpers import scalar

FPID = 83900
HOME_ID, AWAY_ID = 5101, 5102
T1 = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)
T2 = T1 + timedelta(minutes=30)
T3 = T1 + timedelta(minutes=60)
HASHES = ("nw-old", "nw-new", "nw-newest")


@dataclass(frozen=True)
class Ctx:
    dsn: str
    fixture_id: int
    other_fixture_id: int


def _squad(base: int) -> tuple[LineupPlayerRef, ...]:
    return tuple(LineupPlayerRef(provider_player_id=base + n, name=f"NW {base + n}", number=n + 1, position="M",
                                 grid="2:1", is_starter=True) for n in range(11))


def _detail(*, formation: str, squad: int, coach: int, fixture: int = FPID, events: tuple[EventRef, ...] = (),
            shots: int | None = None) -> FixtureDetail:
    blocks = {"lineups"} | ({"events"} if events else set()) | ({"statistics"} if shots is not None else set())
    return FixtureDetail(
        provider_fixture_id=fixture,
        stats=() if shots is None else (TeamStatsRef(provider_fixture_id=fixture, provider_team_id=HOME_ID,
                                                     values={"shots": shots}),),
        events=events,
        lineups=(LineupRef(provider_fixture_id=fixture, provider_team_id=HOME_ID, formation=formation,
                           provider_coach_id=coach, coach_name=f"NW Coach {coach}", players=_squad(squad)),),
        players=(), blocks_present=frozenset(blocks))


def _goal(seq: int, minute: int, fixture: int = FPID) -> EventRef:
    return EventRef(provider_fixture_id=fixture, seq=seq, minute=minute, extra_minute=None, provider_team_id=HOME_ID,
                    provider_player_id=8399, player_name="NW Striker", provider_assist_id=None, assist_name=None,
                    event_type="Goal", detail="Normal Goal", comments=None)


def _apply(conn: psycopg.Connection[Any], d: FixtureDetail, h: str, at: datetime) -> Any:
    return apply_fixture_details(conn, [d], payload_hash=h, fetched_at=at)


def _lineup(conn: psycopg.Connection[Any], fixture_id: int) -> tuple[Any, ...]:
    row = conn.execute("SELECT formation, payload_hash, fetched_at, (SELECT min(provider_player_id) FROM "
                       "core.fixture_lineup_players p WHERE p.fixture_id = l.fixture_id AND p.team_side = l.team_side) "
                       "FROM core.fixture_lineups l WHERE fixture_id = %s AND team_side = 'home'",
                       (fixture_id,)).fetchone()
    assert row is not None
    return tuple(row)


def _clean(dsn: str) -> None:
    with psycopg.connect(dsn) as c:
        c.execute("DELETE FROM audit.data_quality_issues")
        ids = [r[0] for r in c.execute("SELECT id FROM core.fixtures WHERE provider_fixture_id IN (%s, %s)",
                                       (FPID, FPID + 1)).fetchall()]
        for table in ("core.fixture_lineup_players", "core.fixture_lineups", "core.fixture_events",
                      "core.fixture_team_stats", "core.fixture_player_stats", "core.fixture_detail_coverage",
                      "core.fixture_player_extras", "audit.settled_detail_changes"):
            c.execute(f"DELETE FROM {table} WHERE fixture_id = ANY(%s)", (ids,))
        c.execute("DELETE FROM core.fixtures WHERE provider_fixture_id IN (%s, %s)", (FPID, FPID + 1))
        c.execute("DELETE FROM core.teams WHERE provider_team_id IN (%s, %s)", (HOME_ID, AWAY_ID))
        c.execute("DELETE FROM core.coaches WHERE provider_coach_id BETWEEN 7900 AND 7999")
        c.execute("DELETE FROM core.players WHERE provider_player_id BETWEEN 8300 AND 8499")
        c.execute("DELETE FROM raw.ingestion_payloads WHERE hash = ANY(%s)", (list(HASHES),))
        c.commit()


@pytest.fixture()
def ctx(migrated_database: str, seed: Seed) -> Iterator[Ctx]:
    _clean(migrated_database)
    with psycopg.connect(migrated_database) as c:
        teams = [scalar(c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                                  (pid, f"NW {pid}"))) for pid in (HOME_ID, AWAY_ID)]
        fixtures = [int(scalar(c.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
            "kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
            (FPID + n, seed.season_id, teams[0], teams[1], T1 - timedelta(hours=3))))) for n in (0, 1)]
        for h, at in zip(HASHES, (T1, T2, T3), strict=True):
            c.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
                      "file_path, bytes) VALUES (%s, %s, '/fixtures', '{}', %s, 200, %s, 1)",
                      (h, seed.run_id, at, h))
        c.commit()
    try:
        yield Ctx(migrated_database, fixtures[0], fixtures[1])
    finally:
        _clean(migrated_database)


OLD = {"formation": "4-4-2", "squad": 8300, "coach": 7901}
NEW = {"formation": "3-5-2", "squad": 8400, "coach": 7902}


def test_an_older_payload_replayed_after_a_newer_one_leaves_the_lineup_alone(ctx: Ctx) -> None:
    with psycopg.connect(ctx.dsn) as c:
        assert _apply(c, _detail(**NEW), "nw-new", T2).lineups == 1
        report = _apply(c, _detail(**OLD), "nw-old", T1)
        c.commit()
        assert report.stale == 1 and report.lineups == 0, "an older payload for the fixture is skipped whole"
        assert _lineup(c, ctx.fixture_id) == ("3-5-2", "nw-new", T2, 8400)


@pytest.mark.parametrize("everything", [False, True], ids=["lineups only", "with events and statistics"])
def test_a_slow_older_writer_cannot_overwrite_the_newer_lineup_the_other_one_committed(ctx: Ctx,
                                                                                       everything: bool) -> None:
    """Writer A applies the NEWER payload and has not committed yet. Writer B, with the OLDER payload, read 'nothing newer'
    (A's rows are not visible) and goes on to write: it must wait for A, find it stale, and write nothing. With only a
    line-up in the payloads the old code overwrote the newer line-up silently; with events it failed on the key."""
    a = psycopg.connect(ctx.dsn)
    b = psycopg.connect(ctx.dsn)
    failures: list[BaseException] = []
    result: list[Any] = []
    old_extra = {"events": (_goal(1, 30),)} if everything else {}
    new_extra = {"events": (_goal(1, 61),), "shots": 14} if everything else {}

    def older() -> None:
        try:
            result.append(_apply(b, _detail(**OLD, **old_extra), "nw-old", T1))
            b.commit()
        except BaseException as exc:   # reported by the test thread
            failures.append(exc)

    try:
        _apply(a, _detail(**NEW, **new_extra), "nw-new", T2)
        writer = threading.Thread(target=older)
        writer.start()
        deadline = time.monotonic() + 8
        blocked = 0
        while time.monotonic() < deadline and not blocked:
            time.sleep(0.05)
            with psycopg.connect(ctx.dsn, autocommit=True) as watcher:
                blocked = int(scalar(watcher.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()")))
        assert blocked, "the second writer is expected to wait for the first (a row lock or the fixture's lock)"
        a.commit()
        writer.join(timeout=15)
        assert not writer.is_alive() and not failures, failures
    finally:
        a.close()
        b.close()

    with psycopg.connect(ctx.dsn) as c:
        assert _lineup(c, ctx.fixture_id) == ("3-5-2", "nw-new", T2, 8400), "the newer line-up and its players stay"
        if everything:
            assert c.execute("SELECT minute, payload_hash FROM core.fixture_events WHERE fixture_id = %s",
                             (ctx.fixture_id,)).fetchall() == [(61, "nw-new")]
            assert c.execute("SELECT shots, payload_hash FROM core.fixture_team_stats WHERE fixture_id = %s",
                             (ctx.fixture_id,)).fetchall() == [(14, "nw-new")]
    assert result[0].stale == 1 and result[0].lineups == 0


def test_two_writers_on_different_fixtures_do_not_wait_for_each_other(ctx: Ctx) -> None:
    a = psycopg.connect(ctx.dsn)
    b = psycopg.connect(ctx.dsn)
    try:
        _apply(a, _detail(**NEW), "nw-new", T2)
        started = time.monotonic()
        _apply(b, _detail(**OLD, fixture=FPID + 1), "nw-old", T1)    # the other fixture: no lock in common
        b.commit()
        assert time.monotonic() - started < 5
        a.commit()
    finally:
        a.close()
        b.close()


class _Recorder(psycopg.Cursor[Any]):
    """A cursor that notes the arguments of every advisory-lock statement it runs."""

    taken: ClassVar[list[str]] = []

    def execute(self, query: Any, params: Any = None, **kwargs: Any) -> Any:    # type: ignore[override]
        if "pg_advisory_xact_lock" in str(query):
            _Recorder.taken.append(params[0])
        return super().execute(query, params, **kwargs)


def test_the_fixture_lock_is_transaction_scoped_and_taken_in_ascending_order(ctx: Ctx) -> None:
    both = [_detail(**NEW), _detail(**NEW, fixture=FPID + 1)]
    _Recorder.taken = []
    with psycopg.connect(ctx.dsn, cursor_factory=_Recorder) as c:
        apply_fixture_details(c, list(reversed(both)), payload_hash="nw-new", fetched_at=T2)
        held = c.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() "
                         "AND granted").fetchone()
        assert held == (2,), "one lock per fixture, held until the transaction ends"
        c.commit()
        assert c.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
                         ).fetchone() == (0,)
    low, high = sorted((ctx.fixture_id, ctx.other_fixture_id))
    assert _Recorder.taken == [f"{LOCK_PREFIX}{low}", f"{LOCK_PREFIX}{high}"], \
        "ascending, whatever the order of the batch: two writers with overlapping batches cannot wait on each other"


def test_a_replayed_payload_older_than_the_events_stored_leaves_the_events_alone(ctx: Ctx) -> None:
    with psycopg.connect(ctx.dsn) as c:
        _apply(c, _detail(**NEW, events=(_goal(1, 61),)), "nw-new", T2)
        c.commit()
        report = _apply(c, _detail(**OLD, events=(_goal(1, 30), _goal(2, 44))), "nw-old", T1)
        c.commit()
        assert report.stale == 1 and report.events == 0
        assert c.execute("SELECT minute FROM core.fixture_events WHERE fixture_id = %s ORDER BY seq",
                         (ctx.fixture_id,)).fetchall() == [(61,)]


def test_a_newer_payload_still_replaces_what_an_older_one_wrote(ctx: Ctx) -> None:
    """The guard is about order, not about immutability: the newest payload wins."""
    with psycopg.connect(ctx.dsn) as c:
        _apply(c, _detail(**OLD, events=(_goal(1, 30),)), "nw-old", T1)
        report = _apply(c, _detail(**NEW, events=(_goal(1, 61),)), "nw-new", T2)
        c.commit()
        assert report.stale == 0 and report.lineups == 1
        assert _lineup(c, ctx.fixture_id) == ("3-5-2", "nw-new", T2, 8400)
        assert c.execute("SELECT minute FROM core.fixture_events WHERE fixture_id = %s", (ctx.fixture_id,)
                         ).fetchall() == [(61,)]
