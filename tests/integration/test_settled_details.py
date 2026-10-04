"""A finished match's detail is never replaced silently (migration 0061).

The event and line-up lists are written change-only: a re-read that says the same thing touches nothing. When
a newer payload does change a FINISHED match - a list, a statistic - the row as it was is kept in
``audit.settled_detail_changes`` with the payload it came from. In-play replacements are not kept there (RAW
has every payload): the restore test of 4 Oct 2026 found nine in-play event lists replaced in four minutes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ingestion.details import apply_fixture_details
from fbi.providers.api_football.details import (
    EventRef,
    FixtureDetail,
    LineupPlayerRef,
    LineupRef,
    TeamStatsRef,
)
from tests.integration.conftest import Seed

T0 = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)


def payload(db: psycopg.Connection, seed: Seed, h: str, at: datetime) -> str:
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, "
               "bytes) VALUES (%s, %s, '/fixtures', '{}', %s, 200, %s, 1) ON CONFLICT DO NOTHING",
               (h, seed.run_id, at, h))
    return h


def event(seq: int, minute: int, detail: str = "Normal Goal") -> EventRef:
    return EventRef(provider_fixture_id=1001, seq=seq, minute=minute, extra_minute=None, provider_team_id=33,
                    provider_player_id=909, player_name="A. Striker", provider_assist_id=None, assist_name=None,
                    event_type="Goal", detail=detail, comments=None)


def detail(events: list[EventRef], *, shots: int = 11) -> FixtureDetail:
    keeper = LineupPlayerRef(provider_player_id=7000, name="A. Keeper", number=1, position="G", grid="1:1",
                             is_starter=True)
    return FixtureDetail(
        provider_fixture_id=1001,
        stats=(TeamStatsRef(provider_fixture_id=1001, provider_team_id=33, values={"shots": shots}),),
        events=tuple(events),
        lineups=(LineupRef(provider_fixture_id=1001, provider_team_id=33, formation="4-3-3", provider_coach_id=55,
                           coach_name="A. Coach", players=(keeper,)),),
        players=(),
        blocks_present=frozenset({"events", "lineups", "statistics"}))


def apply(db: psycopg.Connection, seed: Seed, h: str, at: datetime, d: FixtureDetail) -> Any:
    return apply_fixture_details(db, [d], payload_hash=payload(db, seed, h, at), fetched_at=at)


def changes(db: psycopg.Connection, seed: Seed) -> list[tuple[Any, ...]]:
    return db.execute("SELECT table_name, op, old_row->>'payload_hash', old_row->>'minute', old_row->>'shots', "
                      "new_row->>'shots' FROM audit.settled_detail_changes WHERE fixture_id = %s ORDER BY id",
                      (seed.fixture_id,)).fetchall()


def test_a_finished_match_keeps_what_a_newer_payload_replaced(db: psycopg.Connection, seed: Seed) -> None:
    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
               (seed.fixture_id,))
    apply(db, seed, "sd-1", T0, detail([event(1, 10)]))
    again = apply(db, seed, "sd-2", T0 + timedelta(hours=1), detail([event(1, 10)]))
    assert again.events == 0 and again.lineup_players == 0, "the same lists: nothing rewritten"
    assert db.execute("SELECT payload_hash FROM core.fixture_events WHERE fixture_id = %s",
                      (seed.fixture_id,)).fetchall() == [("sd-1",)], "the payload the list came from"
    assert changes(db, seed) == [], "provenance moving on, or a coach link, is not a change"

    apply(db, seed, "sd-3", T0 + timedelta(hours=2), detail([event(1, 10), event(2, 80)], shots=12))
    assert db.execute("SELECT count(*), min(payload_hash) FROM core.fixture_events WHERE fixture_id = %s",
                      (seed.fixture_id,)).fetchone() == (2, "sd-3")
    assert changes(db, seed) == [
        ("core.fixture_team_stats", "UPDATE", "sd-2", None, "11", "12"),
        ("core.fixture_events", "DELETE", "sd-1", "10", None, None),
    ], "the statistic as the latest payload had it, the list as the payload that first said it"

    late = apply(db, seed, "sd-0", T0 - timedelta(hours=1), detail([event(1, 12)]))
    assert late.stale == 1, "an older payload never replaces a newer list, changed or not"
    assert db.execute("SELECT count(*) FROM core.fixture_events WHERE fixture_id = %s",
                      (seed.fixture_id,)).fetchone() == (2,)


def test_an_in_play_list_is_replaced_without_an_archive_row(db: psycopg.Connection, seed: Seed) -> None:
    db.execute("UPDATE core.fixtures SET status_short = '2H', status_group = 'live' WHERE id = %s",
               (seed.fixture_id,))
    apply(db, seed, "lv-1", T0, detail([event(1, 10), event(2, 55)]))
    apply(db, seed, "lv-2", T0 + timedelta(minutes=1), detail([event(1, 10)], shots=13))
    assert db.execute("SELECT count(*) FROM core.fixture_events WHERE fixture_id = %s",
                      (seed.fixture_id,)).fetchone() == (1,), "the provider withdrew the second goal (VAR)"
    assert changes(db, seed) == [], "in play: RAW keeps every payload"
