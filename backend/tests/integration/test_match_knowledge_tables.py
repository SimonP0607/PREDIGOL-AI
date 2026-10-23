"""The two tables of plan F7 on a real database (revisions 0089 and 0090): what each line of the events is, and Match Knowledge.

``core.fixture_event_kinds`` is DERIVED - the builder rewrites the rows of a match as a whole - so it is a plain table with the checks that keep
it honest. ``intel.match_knowledge`` is HISTORY - one row per build, never edited or deleted - so the database itself refuses a change, refuses
two builders adding the same row, and shows the newest build of each match through a view. The transaction is rolled back after every test."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg.errors import CheckViolation, NotNullViolation, UniqueViolation
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration

T0 = datetime(2034, 4, 1, 12, tzinfo=UTC)
A, B = 91_000_001, 91_000_002
HASH_1, HASH_2, HASH_3 = "1" * 64, "2" * 64, "3" * 64
CONTENT_X, CONTENT_Y = "a" * 64, "b" * 64


# ── core.fixture_event_kinds ─────────────────────────────────────────────────────────────────────────────────────────────


def put_kind(db: psycopg.Connection[Any], **change: Any) -> None:
    row: dict[str, Any] = {"fixture_id": A, "source": "api-football", "seq": 0, "rules_version": "events-v1", "kind": "goal", "period": "1H",
                           "side": "home", "player_side": None, "pair_seq": None, "flags": [], "event_fetched_at": T0} | change
    db.execute("INSERT INTO core.fixture_event_kinds (fixture_id, source, seq, rules_version, kind, period, side, player_side, pair_seq, flags, "
               "event_fetched_at) VALUES (%(fixture_id)s, %(source)s, %(seq)s, %(rules_version)s, %(kind)s, %(period)s, %(side)s, "
               "%(player_side)s, %(pair_seq)s, %(flags)s, %(event_fetched_at)s)", row)


def kinds_of(db: psycopg.Connection[Any], fixture_id: int) -> list[tuple[Any, ...]]:
    return db.execute("SELECT seq, kind, period, side, flags FROM core.fixture_event_kinds WHERE fixture_id = %s ORDER BY seq", (fixture_id,)).fetchall()


def test_a_line_is_read_once_per_match_source_and_position(db: psycopg.Connection[Any]) -> None:
    put_kind(db)
    put_kind(db, seq=1)
    put_kind(db, fixture_id=B)                    # the same position of another match is another line
    with pytest.raises(UniqueViolation):
        put_kind(db)


@pytest.mark.parametrize("change", [
    {"source": "other-provider"}, {"seq": -1}, {"kind": "Goal"}, {"kind": "own goal"}, {"kind": "x"}, {"kind": ""}, {"kind": "g" * 42},
    {"rules_version": "  "}, {"period": "3H"}, {"period": "FT"}, {"side": "neither"}, {"player_side": "both"}, {"pair_seq": -1},
])
def test_the_database_refuses_a_line_that_is_not_what_it_says(db: psycopg.Connection[Any], change: dict[str, Any]) -> None:
    with pytest.raises(CheckViolation):
        put_kind(db, **change)


def test_a_line_must_say_which_line_it_was_read_from(db: psycopg.Connection[Any]) -> None:
    with pytest.raises(NotNullViolation):
        put_kind(db, event_fetched_at=None)


def test_a_line_with_no_side_no_pair_and_no_flags_is_stored_as_it_is(db: psycopg.Connection[Any]) -> None:
    put_kind(db, side=None, kind="other", flags=["unknown_detail", "no_side"])
    put_kind(db, seq=1, kind="yellow", period="2H")
    assert kinds_of(db, A) == [(0, "other", "1H", None, ["unknown_detail", "no_side"]), (1, "yellow", "2H", "home", [])]
    row = db.execute("SELECT built_at IS NOT NULL, pair_seq, player_side FROM core.fixture_event_kinds WHERE seq = 1").fetchone()
    assert row == (True, None, None), "built_at is the moment it was read; a pair and the side of the man are left empty when there is none"


def test_the_rows_of_a_match_can_be_rewritten_as_a_whole_and_the_others_are_not_touched(db: psycopg.Connection[Any]) -> None:
    for seq, kind in enumerate(("goal", "yellow", "red")):
        put_kind(db, seq=seq, kind=kind)
    put_kind(db, fixture_id=B, kind="penalty_goal")
    db.execute("DELETE FROM core.fixture_event_kinds WHERE fixture_id = %s", (A,))
    put_kind(db, seq=0, kind="own_goal", rules_version="events-v2")
    db.execute("UPDATE core.fixture_event_kinds SET kind = 'goal' WHERE fixture_id = %s AND seq = 0", (A,))     # a derived table is not append-only
    assert [r[:2] for r in kinds_of(db, A)] == [(0, "goal")]
    assert [r[:2] for r in kinds_of(db, B)] == [(0, "penalty_goal")]


# ── intel.match_knowledge ────────────────────────────────────────────────────────────────────────────────────────────────


def put_build(db: psycopg.Connection[Any], *, skip_if_same: bool = False, **change: Any) -> int | None:
    row: dict[str, Any] = {"fixture_id": A, "version": "mk-v1", "known_at": T0, "inputs_hash": HASH_1, "content_hash": CONTENT_X,
                           "completeness": "complete", "layers": Jsonb({"c1": {"status": "ok"}}), "quality": Jsonb({})} | change
    got = db.execute("INSERT INTO intel.match_knowledge (fixture_id, version, known_at, inputs_hash, content_hash, completeness, layers, quality) "
                     "VALUES (%(fixture_id)s, %(version)s, %(known_at)s, %(inputs_hash)s, %(content_hash)s, %(completeness)s, %(layers)s, "
                     f"%(quality)s) {'ON CONFLICT DO NOTHING ' if skip_if_same else ''}RETURNING id", row).fetchone()
    return None if got is None else int(got[0])


def latest(db: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return db.execute("SELECT fixture_id, version, id, inputs_hash, content_hash FROM intel.match_knowledge_latest ORDER BY fixture_id, version").fetchall()


def test_a_build_is_stored_with_its_layers_and_the_view_shows_it(db: psycopg.Connection[Any]) -> None:
    layers = {"c1": {"status": "ok", "known_at": "2034-04-01T12:00:00Z", "sources": ["core.fixture_results"], "data": {"ft": [2, 1]}},
              "c7": {"status": "off"}}
    first = put_build(db, layers=Jsonb(layers), quality=Jsonb({"events_give_the_score": True}), completeness="partial")
    assert first is not None
    row = db.execute("SELECT layers, quality, completeness, known_at, built_at IS NOT NULL FROM intel.match_knowledge_latest WHERE fixture_id = %s",
                     (A,)).fetchone()
    assert row == (layers, {"events_give_the_score": True}, "partial", T0, True)


def test_building_again_with_the_same_inputs_and_content_adds_nothing(db: psycopg.Connection[Any]) -> None:
    assert put_build(db) is not None
    assert put_build(db, skip_if_same=True) is None, "what the builder does when two of them meet"
    assert db.execute("SELECT count(*) FROM intel.match_knowledge").fetchone() == (1,)
    with pytest.raises(UniqueViolation):
        put_build(db)


def test_a_match_can_go_a_then_b_then_a_again_and_the_third_row_is_a_fact(db: psycopg.Connection[Any]) -> None:
    # The provider changes its mind twice: the third build has the content of the first and the inputs of the third moment.
    first = put_build(db, inputs_hash=HASH_1, content_hash=CONTENT_X)
    second = put_build(db, inputs_hash=HASH_2, content_hash=CONTENT_Y)
    third = put_build(db, inputs_hash=HASH_3, content_hash=CONTENT_X)
    assert first is not None and second is not None and third is not None and first < second < third
    assert latest(db) == [(A, "mk-v1", third, HASH_3, CONTENT_X)], "what the match is today is the newest build"
    assert db.execute("SELECT count(*) FROM intel.match_knowledge WHERE fixture_id = %s", (A,)).fetchone() == (3,), "and the history is all there"


def test_the_view_shows_the_newest_build_of_each_match_and_each_version(db: psycopg.Connection[Any]) -> None:
    put_build(db, inputs_hash=HASH_1)
    newest_a = put_build(db, inputs_hash=HASH_2, content_hash=CONTENT_Y)
    other_version = put_build(db, version="mk-v2")
    other_match = put_build(db, fixture_id=B)
    assert latest(db) == [(A, "mk-v1", newest_a, HASH_2, CONTENT_Y), (A, "mk-v2", other_version, HASH_1, CONTENT_X),
                          (B, "mk-v1", other_match, HASH_1, CONTENT_X)]


@pytest.mark.parametrize("statement", [
    "UPDATE intel.match_knowledge SET completeness = 'minimal'",
    "UPDATE intel.match_knowledge SET layers = '{}'::jsonb",
    "DELETE FROM intel.match_knowledge",
])
def test_a_build_is_never_edited_or_deleted_afterwards(db: psycopg.Connection[Any], statement: str) -> None:
    put_build(db)
    with pytest.raises(CheckViolation, match="append-only"):
        db.execute(statement)


@pytest.mark.parametrize("change", [
    {"version": "  "}, {"inputs_hash": "1" * 63}, {"inputs_hash": "1" * 65}, {"content_hash": "a" * 63}, {"content_hash": ""},
    {"completeness": "full"}, {"completeness": ""}, {"layers": Jsonb([])}, {"layers": Jsonb("c1")}, {"quality": Jsonb([])}, {"quality": Jsonb(3)},
])
def test_the_database_refuses_a_build_that_is_not_what_it_says(db: psycopg.Connection[Any], change: dict[str, Any]) -> None:
    with pytest.raises(CheckViolation):
        put_build(db, **change)


@pytest.mark.parametrize("change", [{"known_at": None}, {"fixture_id": None}, {"layers": None}, {"inputs_hash": None}, {"content_hash": None}])
def test_a_build_must_say_when_it_was_known_and_what_it_was_built_from(db: psycopg.Connection[Any], change: dict[str, Any]) -> None:
    with pytest.raises(NotNullViolation):
        put_build(db, **change)


@pytest.mark.parametrize("completeness", ["complete", "partial", "minimal"])
def test_a_build_is_complete_partial_or_minimal(db: psycopg.Connection[Any], completeness: str) -> None:
    assert put_build(db, completeness=completeness) is not None
