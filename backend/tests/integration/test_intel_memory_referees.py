"""Referees in the longitudinal memory (plan F3, ``memory-v3``): the entity is the person, the rows memory-v2 wrote under a
string are history that nothing continues or reconciles, and a merge re-books the days still inside the late window."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.api.services import intelligence as svc
from fbi.intel import memory
from fbi.people import referees as store

from .conftest import Seed
from .test_intel_memory_late import DAY, KICKOFF, World, _night, _rows

pytestmark = pytest.mark.integration


def referee_key(db: psycopg.Connection[Any], fixture_id: int) -> memory.EKey:
    row = db.execute("SELECT referee_id FROM core.fixture_referees WHERE fixture_id = %s", (fixture_id,)).fetchone()
    assert row is not None, "the match has not been placed"
    return ("referee", str(row[0]), "discipline")


def test_one_person_is_one_entity_whatever_the_spellings(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    db.execute("UPDATE core.competitions SET country = 'England' WHERE id = %s", (seed.competition_id,))  # a domestic league: the scope
    full = w.match(KICKOFF, result=(2, 1), referee="Michael Oliver")
    initial = w.match(KICKOFF + timedelta(hours=4), result=(0, 0), referee="M. Oliver")  # not within 2 h: one man is not in two places
    store.build(db, apply=True)
    key = referee_key(db, full)
    assert referee_key(db, initial) == key, "'M. Oliver' is Michael Oliver: the one full name it could be"

    memory.build_memory(db, day=DAY, at=_night(DAY))
    referees = _rows(db, DAY, entity_type="referee")
    assert list(referees) == [key]
    assert referees[key]["stats"]["matches"] == 2 and referees[key]["entity_name"] == "Michael Oliver"
    assert sorted(referees[key]["sources"]) == sorted([full, initial])
    assert referees[key]["version"] == memory.VERSION


def test_the_rows_written_under_a_string_are_history_nothing_continues_or_reconciles(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    old_day = DAY - timedelta(days=1)
    legacy = {"matches": 5, "cards": 20, "cards_home": 9, "cards_away": 11, "reds": 1, "fouls": 100, "fouls_matches": 5, "penalties": 2}
    db.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, entity_name, aspect, as_of_day, built_at, version, stats, delta, sources) "
               "VALUES ('referee', 'M. Oliver', 'M. Oliver', 'discipline', %s, %s, 'memory-v2', %s, %s, '[]')",
               (old_day, _night(old_day), Jsonb(legacy), Jsonb(legacy)))
    fid = w.match(KICKOFF - timedelta(days=1), result=(1, 0), referee="M. Oliver")  # on the legacy row's day
    store.build(db, apply=True)

    for day in (DAY, DAY + timedelta(days=1)):
        memory.build_memory(db, day=day, at=_night(day))
    rows = db.execute("SELECT as_of_day, version, stats, delta FROM intel.entity_memory WHERE entity_type = 'referee' "
                      "AND entity_id = 'M. Oliver' ORDER BY as_of_day").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(old_day, "memory-v2")], "no row for the string after memory-v2: nothing continues it"
    assert rows[0][2] == legacy and rows[0][3] == legacy, "and the old row is as it was written"

    new_key = referee_key(db, fid)
    new_rows = db.execute("SELECT as_of_day, stats FROM intel.entity_memory WHERE entity_type = 'referee' AND entity_id = %s ORDER BY as_of_day",
                          (new_key[1],)).fetchall()
    assert new_rows and new_rows[0][1]["matches"] == 1, "the person starts over on the first day memory-v3 runs, booking the late window"


def test_the_console_lists_the_people_and_still_reaches_the_old_rows(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    old_day = DAY - timedelta(days=1)
    db.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, entity_name, aspect, as_of_day, built_at, version, stats, delta, sources) "
               "VALUES ('referee', 'M. Oliver', 'M. Oliver', 'discipline', %s, %s, 'memory-v2', %s, '{}', '[]')",
               (old_day, _night(old_day), Jsonb({"matches": 5})))
    fid = w.match(KICKOFF, result=(1, 0), referee="Michael Oliver")
    store.build(db, apply=True)
    memory.build_memory(db, day=DAY, at=_night(DAY))

    listed = svc.memory(db, entity_type="referee", q=None, limit=50).data
    assert [r["entity_id"] for r in listed["items"]] == [referee_key(db, fid)[1]], "one entity per person"
    assert listed["total"] == 1
    found = svc.memory(db, entity_type=None, q="Oliver", limit=50).data
    assert {r["entity_id"] for r in found["items"] if r["entity_type"] == "referee"} == {referee_key(db, fid)[1]}
    history = svc.memory_history(db, "referee", "M. Oliver").data
    assert [h["as_of_day"] for h in history["history"]] == [old_day.isoformat()], "the history of the string is still there to read"


def test_the_console_hides_only_the_referees_under_a_string(db: psycopg.Connection[Any]) -> None:
    """A market is an entity too, and its id is a word (``1X2``): the filter that hides the old referee rows is about referees."""
    day = DAY - timedelta(days=1)
    for entity_type, entity_id, name in (("market", "1X2", "1X2"), ("team", "77", "Some FC"), ("referee", "Some Ref", "Some Ref"),
                                         ("referee", "123", "Some Ref")):
        db.execute("INSERT INTO intel.entity_memory (entity_type, entity_id, entity_name, aspect, as_of_day, built_at, version, stats, delta, sources) "
                   "VALUES (%s, %s, %s, 'x', %s, %s, 'memory-v2', %s, '{}', '[]')",
                   (entity_type, entity_id, name, day, _night(day), Jsonb({"matches": 1})))
    listed = svc.memory(db, entity_type=None, q=None, limit=50).data
    assert {(r["entity_type"], r["entity_id"]) for r in listed["items"]} == {("market", "1X2"), ("team", "77"), ("referee", "123")}


def test_a_match_placed_after_its_day_was_written_is_booked_by_the_late_news(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    nxt = DAY + timedelta(days=1)
    fid = w.match(KICKOFF, result=(2, 1), referee="Michael Oliver")
    memory.build_memory(db, day=DAY, at=_night(DAY))
    assert _rows(db, DAY, entity_type="referee") == {}, "the identity has not placed the match: no entity yet"

    store.build(db, apply=True)
    assert memory.build_memory(db, day=nxt, at=_night(nxt)) >= 1
    key = referee_key(db, fid)
    row = _rows(db, nxt, entity_type="referee")[key]
    assert row["delta"]["late"][DAY.isoformat()]["matches"] == 1 and row["stats"]["matches"] == 1
    assert fid in row["sources"]


def test_a_merge_rebooks_the_days_inside_the_late_window_to_the_right_person(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    nxt = DAY + timedelta(days=1)
    one = w.match(KICKOFF, result=(1, 0), referee="Michael Oliver")
    two = w.match(KICKOFF + timedelta(hours=5), result=(0, 1), referee="Mike Whistle")
    store.build(db, apply=True)
    keep, other = referee_key(db, one), referee_key(db, two)
    assert keep != other
    memory.build_memory(db, day=DAY, at=_night(DAY))
    assert _rows(db, DAY, entity_type="referee")[keep]["stats"]["matches"] == 1

    store.merge(db, int(keep[1]), int(other[1]), actor="admin:test", note="the same man")
    assert memory.build_memory(db, day=nxt, at=_night(nxt)) >= 2
    rows = _rows(db, nxt, entity_type="referee")
    assert rows[keep]["delta"]["late"][DAY.isoformat()]["matches"] == 1 and rows[keep]["stats"]["matches"] == 2
    assert rows[other]["delta"]["late"][DAY.isoformat()]["matches"] == -1 and rows[other]["stats"]["matches"] == 0
    assert sorted(rows[keep]["sources"]) == sorted([one, two]) or two in rows[keep]["sources"]
