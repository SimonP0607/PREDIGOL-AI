"""The nightly proof that no packet knew the referee before the provider said so (plan F3, ``leak-audit-v3``, rule ``referee_known``).

The rule reads the packets built on the day that name a referee: the observation of the provider the name comes from must exist,
must not be later than the packet's moment, and must be the newest one the provider had given by then. It never asks who the
spelling is today - a merge is a decision about the person, not a new fact about the past. The packets are written by hand where
a faulty reader would have put something wrong in them: a stored packet cannot be changed afterwards (the table is append-only)."""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from fbi.ai.packet import PacketBuilder, store_packet
from fbi.intel import leakage
from fbi.people import referees as store
from tests.integration.test_referee_identity_store import World, world  # noqa: F401  (the fixture and the data)
from tests.integration.test_referee_in_the_packet import AT, played, upcoming

pytestmark = pytest.mark.integration

RULE = "referee_known"


def audited(w: World, at: datetime) -> dict[str, Any]:
    """The rule on the Bogotá day of ``at`` (one call per day in a test: the audit keeps every run under its ``checked_at``)."""
    out: dict[str, Any] = leakage.audit_day(w.db, day=local_day(at), at=at + timedelta(hours=1))[RULE]
    return out


def content_of(w: World, fixture_id: int, at: datetime = AT) -> dict[str, Any]:
    """The content of the packet as the builder makes it (not stored): a copy to tamper with."""
    built = PacketBuilder(w.db).build(fixture_id, at=at)
    assert built is not None
    return copy.deepcopy(built.content)


def honest_packet(w: World, fixture_id: int, at: datetime = AT) -> tuple[int, dict[str, Any]]:
    """A packet as the builder makes it, stored; returns its id and a copy of its content to tamper with."""
    built = PacketBuilder(w.db).build(fixture_id, at=at)
    assert built is not None
    return store_packet(w.db, built, built_at=at), copy.deepcopy(built.content)


def handmade(w: World, fixture_id: int, content: dict[str, Any], at: datetime = AT, *, built_at: datetime | None = None,
             version: str = "packet-v5") -> int:
    """A stored packet whose content was written by hand: what a faulty reader would have put there."""
    row = w.db.execute(
        "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id", (fixture_id, version, at, built_at or at, hashlib.sha256(repr((fixture_id, at, content)).encode()).hexdigest(),
                         Jsonb(content))).fetchone()
    assert row is not None
    return int(row[0])


def test_the_rule_is_in_the_audit_and_the_version_says_so() -> None:
    assert RULE in leakage.RULES and leakage.VERSION == "leak-audit-v8"


def test_a_packet_built_by_the_builder_names_a_referee_the_provider_had_given(world: World) -> None:  # noqa: F811
    played(world, "England", 1, "Michael Oliver", "England")
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    honest_packet(world, target)

    assert audited(world, AT) == {"checked": 1, "violations": 0, "examples": []}
    rows = world.db.execute("SELECT version, n_checked, n_violations FROM intel.audit_checks WHERE rule = %s", (RULE,)).fetchall()
    assert rows == [("leak-audit-v8", 1, 0)], "the run is kept in the ledger of the audit with its version"


def test_a_packet_that_kept_the_string_cites_the_observation_of_the_facts(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Anna Referee")  # the identity has not seen the match: the packet keeps the string
    pid, content = honest_packet(world, target)
    assert content["fixture"]["referee"] == "Anna Referee" and content["fixture"]["referee_id"] is None
    assert audited(world, AT) == {"checked": 1, "violations": 0, "examples": []}
    assert pid


def test_a_packet_that_names_nobody_has_nothing_to_prove(world: World) -> None:  # noqa: F811
    target = upcoming(world, None)
    honest_packet(world, target)
    assert audited(world, AT) == {"checked": 0, "violations": 0, "examples": []}


def test_a_packet_of_an_earlier_version_is_not_read(world: World) -> None:  # noqa: F811
    """packet-v4 carried the name and not the moment it was seen: there is nothing to check it against, and it is not a violation."""
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    _pid, content = honest_packet(world, target)
    del content["fixture"]["referee_seen_at"]
    handmade(world, target, content, AT + timedelta(minutes=5), version="packet-v4")
    assert audited(world, AT) == {"checked": 1, "violations": 0, "examples": []}, "only the honest packet; the old one is not counted"


def test_a_packet_that_read_an_observation_made_after_its_moment_is_a_violation(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Michael Oliver", "England")
    later = AT + timedelta(hours=2)
    world.say(target, "Craig Pawson", "England", at=later)  # said after the packet's moment
    store.build(world.db, apply=True)
    _pid, content = honest_packet(world, target)
    content["fixture"].update(referee="Craig Pawson", referee_seen_at=later.isoformat())  # a reader that looked at the newest
    bad = handmade(world, target, content, AT + timedelta(minutes=1), built_at=AT + timedelta(minutes=1))

    assert audited(world, AT) == {"checked": 2, "violations": 1, "examples": [bad]}


def test_an_observation_made_at_the_very_moment_of_the_packet_is_known(world: World) -> None:  # noqa: F811
    target = world.fixture("England", 100)
    world.say(target, "Michael Oliver", "England", at=AT)
    world.db.execute("UPDATE core.fixtures SET status_short = 'NS', status_group = 'scheduled' WHERE id = %s", (target,))
    store.build(world.db, apply=True)
    _pid, content = honest_packet(world, target)
    assert content["fixture"]["referee"] == "Michael Oliver" and content["fixture"]["referee_seen_at"] == AT.isoformat()
    assert audited(world, AT) == {"checked": 1, "violations": 0, "examples": []}


def test_a_packet_that_cites_an_observation_that_does_not_exist_is_a_violation(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    _pid, content = honest_packet(world, target)
    content["fixture"]["referee_seen_at"] = (AT - timedelta(hours=2)).isoformat()  # the provider said nothing then
    bad = handmade(world, target, content, AT + timedelta(minutes=1))
    assert audited(world, AT) == {"checked": 2, "violations": 1, "examples": [bad]}


def test_a_packet_that_cites_no_moment_for_the_name_it_gives_is_a_violation(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    _pid, content = honest_packet(world, target)
    content["fixture"]["referee_seen_at"] = None
    bad = handmade(world, target, content, AT + timedelta(minutes=1))
    assert audited(world, AT) == {"checked": 2, "violations": 1, "examples": [bad]}


def test_a_packet_that_read_an_older_answer_than_the_one_the_provider_had_given_is_a_violation(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Michael Oliver", "England")  # said at AT - 20 h
    store.build(world.db, apply=True)
    stale = content_of(world, target)
    world.say(target, "Craig Pawson", "England", at=AT - timedelta(hours=1))  # the provider changed its mind before the moment
    store.build(world.db, apply=True)
    _pid, fresh = honest_packet(world, target, AT + timedelta(minutes=2))
    assert fresh["fixture"]["referee"] == "Craig Pawson"
    old = handmade(world, target, stale, AT + timedelta(minutes=1), built_at=AT + timedelta(minutes=1))  # one that missed the change

    assert audited(world, AT) == {"checked": 2, "violations": 1, "examples": [old]}


def test_a_packet_of_a_string_that_cites_a_missing_observation_of_the_facts_is_a_violation(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Anna Referee")
    _pid, content = honest_packet(world, target)
    content["fixture"]["referee_seen_at"] = (AT - timedelta(hours=3)).isoformat()
    bad = handmade(world, target, content, AT + timedelta(minutes=1))
    assert audited(world, AT) == {"checked": 2, "violations": 1, "examples": [bad]}


def test_a_packet_that_cites_an_observation_that_did_not_name_the_referee_is_a_violation(world: World) -> None:  # noqa: F811
    """The text reading: the row the moment points at is the one that took him off, so it cannot be where the name came from."""
    target = upcoming(world, "Anna Referee")  # said at AT - 20 h
    taken_off = world.say(target, None, at=AT - timedelta(hours=1))
    content = content_of(world, target)
    assert content["fixture"]["referee"] is None, "the builder knows he was taken off"
    content["fixture"].update(referee="Anna Referee", referee_seen_at=taken_off.isoformat())
    bad = handmade(world, target, content, AT + timedelta(minutes=1))
    assert audited(world, AT) == {"checked": 1, "violations": 1, "examples": [bad]}


def test_a_packet_built_before_the_pass_caught_up_is_not_a_violation_once_it_does(world: World) -> None:  # noqa: F811
    """The pass runs hourly: for a while after the provider changes the referee the packet reads the string, and says so."""
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    changed = world.say(target, "Craig Pawson", "England", at=AT - timedelta(hours=1))
    _pid, content = honest_packet(world, target)
    assert content["fixture"]["referee"] == "Craig Pawson" and content["fixture"]["referee_id"] is None
    assert content["fixture"]["referee_seen_at"] == changed.isoformat()

    store.build(world.db, apply=True)  # the pass catches up with the change
    assert audited(world, AT) == {"checked": 1, "violations": 0, "examples": []}


def test_a_merge_or_a_split_after_the_packet_is_not_a_violation(world: World) -> None:  # noqa: F811
    one = played(world, "England", 1, "Michael Oliver", "England")
    two = played(world, "England", 5, "Mike Whistle", "England")
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    keep, other = world.referee_of(one), world.referee_of(two)
    assert keep is not None and other is not None and keep != other
    honest_packet(world, target)

    store.merge(world.db, keep, other, actor="admin:test", note="the same man")
    assert audited(world, AT) == {"checked": 1, "violations": 0, "examples": []}, "who the spelling is today is not what the provider said then"


def test_only_the_packets_built_on_the_day_are_audited(world: World) -> None:  # noqa: F811
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    _pid, content = honest_packet(world, target)
    content["fixture"]["referee_seen_at"] = (AT - timedelta(hours=2)).isoformat()  # a violation, but built three days earlier
    early = AT - timedelta(days=3)
    handmade(world, target, content, early, built_at=early)
    assert audited(world, AT) == {"checked": 1, "violations": 0, "examples": []}
    assert audited(world, early)["violations"] == 1


def test_the_audit_proves_when_the_name_was_known_not_that_the_packet_reads_the_row_right(world: World) -> None:  # noqa: F811
    """The audit proves WHEN the name was known, not that the packet reads the row correctly: the as-of reader has its own tests."""
    target = upcoming(world, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    _pid, content = honest_packet(world, target)
    content["fixture"]["referee"] = "Somebody Else"
    handmade(world, target, content, AT + timedelta(minutes=1))
    assert audited(world, AT) == {"checked": 2, "violations": 0, "examples": []}
