"""The nightly proof that no packet knew a team's calendar before the world did (plan F4, ``leak-audit-v5``, rule ``calendar_known``).

A packet from ``packet-v7`` says, for each side, which reading of the team's list its figures come from (``schedule.calendar``) and
cites the matches behind them (``schedule.<side>.recent`` / ``upcoming``). The rule holds the packet to the tables: the reading
must exist, not be later than the packet and be the newest by then; a side that says it is whole must have been read lately; and every
match cited must be a row that existed by the packet's moment. The honest packets here are built by the real builder; the dishonest
ones are the same packets edited by hand, which is what a faulty reader would have stored. The transaction is rolled back afterwards."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from fbi.ai.packet import Packet, PacketBuilder, store_packet
from fbi.intel import leakage
from tests.integration.calendar_helpers import (
    AT,
    FRESH,
    KICKOFF,
    World,
    cup_tie,
    fixture,
    followed_season,
    own_followed,
    read,
    read_both,
    world,
)
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

pytestmark = pytest.mark.integration

RULE = "calendar_known"


def built(db: psycopg.Connection[Any], w: World, at: datetime = AT) -> Packet:
    packet = PacketBuilder(db).build(w.fixture_id, at=at)
    assert packet is not None
    return packet


def audited(db: psycopg.Connection[Any], at: datetime = AT, run: int = 0) -> dict[str, Any]:
    """The rule on the Bogotá day of ``at`` (the audit keeps every run under its ``checked_at``, so a second run in a test moves it)."""
    out: dict[str, Any] = leakage.audit_day(db, day=local_day(at), at=at + timedelta(hours=1, minutes=run))[RULE]
    return out


def handmade(db: psycopg.Connection[Any], fid: int, content: dict[str, Any], at: datetime = AT) -> int:
    """A stored packet whose content was written by hand: what a faulty reader would have put there."""
    row = db.execute(
        "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id", (fid, "packet-v7", at, at, hashlib.sha256(repr((fid, at, content)).encode()).hexdigest(),
                         Jsonb(content))).fetchone()
    assert row is not None
    return int(row[0])


def tampered(packet: Packet, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    content = copy.deepcopy(packet.content)
    change(content)
    return content


# ── the rule and the packets it reads ────────────────────────────────────────────────────────────────────────────────────


def test_the_rule_is_in_the_audit_and_the_version_says_so() -> None:
    assert RULE in leakage.RULES and leakage.VERSION == "leak-audit-v7" and RULE in (leakage.__doc__ or "")


def test_an_honest_packet_passes_one_check_per_side_and_per_match_cited(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    packet = built(db, w)
    schedule = packet.content["schedule"]
    assert [len(schedule[s]["recent"]) for s in ("home", "away")] == [2, 1] and len(schedule["home"]["upcoming"]) == 1
    store_packet(db, packet, built_at=AT)

    assert audited(db) == {"checked": 6, "violations": 0, "examples": []}, "2 sides, 3 matches played and 1 to come"
    rows = db.execute("SELECT version, n_checked, n_violations FROM intel.audit_checks WHERE rule = %s", (RULE,)).fetchall()
    assert rows == [("leak-audit-v7", 6, 0)], "the run is kept in the ledger of the audit with its version"


def test_a_side_never_read_is_honest_when_it_says_so(db: psycopg.Connection[Any]) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    packet = built(db, w)
    assert packet.content["schedule"]["calendar"]["home"]["fetched_at"] is None
    store_packet(db, packet, built_at=AT)
    assert audited(db) == {"checked": 4, "violations": 0, "examples": []}, "2 sides and the league match each one played"


def test_a_packet_that_does_not_carry_the_calendar_is_not_read(db: psycopg.Connection[Any]) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    packet = built(db, w)
    v6 = tampered(packet, lambda c: c["schedule"].update(
        calendar={"scope": "tracked_competitions", "complete": None, "note": "only the competitions PrediGol follows"}))
    for side in ("home", "away"):
        for key in ("recent", "upcoming"):
            v6["schedule"][side].pop(key)
    handmade(db, w.fixture_id, v6, AT)
    gone = tampered(packet, lambda c: c.update(schedule={"error": "UndefinedTable"}))
    handmade(db, w.fixture_id, gone, AT + timedelta(minutes=1))
    assert audited(db) == {"checked": 0, "violations": 0, "examples": []}


def test_a_list_rescheduled_between_two_packets_is_cited_as_each_one_read_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    tie = cup_tie(w, "home", days_after=3.0, name="Supercopa")
    read(db, seed, w.home, [own_followed(w, "home", 8.0), tie], FRESH)
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], FRESH)
    first = built(db, w)
    later = AT + timedelta(hours=3)
    moved = copy.deepcopy(tie)
    moved["fixture"]["date"] = (KICKOFF + timedelta(days=4)).isoformat()
    read(db, seed, w.home, [own_followed(w, "home", 8.0), moved], AT + timedelta(hours=2))
    second = built(db, w, at=later)

    assert first.content["schedule"]["home"]["upcoming"][0]["days_after"] == 3.0
    assert second.content["schedule"]["home"]["upcoming"][0]["days_after"] == 4.0
    store_packet(db, first, built_at=AT)
    store_packet(db, second, built_at=later)
    result = audited(db)
    assert result["violations"] == 0 and result["checked"] == 10, "each packet cites the list as it stood at its own moment"


# ── the reading a packet says it used ───────────────────────────────────────────────────────────────────────────────────


def test_a_reading_made_after_the_packet_is_found(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    packet = built(db, w)
    after = (AT + timedelta(minutes=5)).isoformat()
    pid = handmade(db, w.fixture_id, tampered(packet, lambda c: c["schedule"]["calendar"]["home"].update(fetched_at=after)))

    result = audited(db)
    assert result["checked"] == 6 and result["violations"] == 1 and result["examples"] == [pid]


def test_a_reading_that_never_happened_is_found(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    packet = built(db, w)
    never = (FRESH - timedelta(hours=3)).isoformat()  # no list of the team was read then
    pid = handmade(db, w.fixture_id, tampered(packet, lambda c: c["schedule"]["calendar"]["away"].update(fetched_at=never)))

    result = audited(db)
    assert result["violations"] == 1 and result["examples"] == [pid]


def test_a_packet_that_read_an_older_list_than_the_one_the_provider_had_given_is_found(db: psycopg.Connection[Any],
                                                                                    seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    packet = built(db, w)  # cites the reading of yesterday
    read(db, seed, w.home, [own_followed(w, "home", 8.0)], AT - timedelta(hours=2))  # a newer one existed by the moment
    pid = handmade(db, w.fixture_id, packet.content)

    result = audited(db)
    assert result["violations"] == 1 and result["examples"] == [pid], "the side that did not read the newest answer"


def test_a_reading_still_being_committed_when_the_packet_was_built_is_not_held_against_it(db: psycopg.Connection[Any],
                                                                                      seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    store_packet(db, built(db, w), built_at=AT)
    read(db, seed, w.home, [own_followed(w, "home", 8.0)], AT - timedelta(seconds=30))  # seconds before the moment

    assert audited(db)["violations"] == 0, "a minute of leeway for a reading that was not yet visible"


def test_a_side_that_says_it_was_never_read_when_it_had_been_is_found(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    packet = built(db, w)  # nobody had read the lists
    read(db, seed, w.home, [own_followed(w, "home", 8.0)], AT - timedelta(hours=3))  # but home's had been read three hours before
    pid = handmade(db, w.fixture_id, packet.content)

    result = audited(db)
    assert result["checked"] == 4 and result["violations"] == 1 and result["examples"] == [pid]


def test_a_side_that_says_it_is_whole_without_a_reading_is_found(db: psycopg.Connection[Any]) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    packet = built(db, w)
    pid = handmade(db, w.fixture_id, tampered(packet, lambda c: c["schedule"]["calendar"]["home"].update(complete=True)))

    result = audited(db)
    assert result["violations"] == 1 and result["examples"] == [pid]


def test_a_side_that_says_it_is_whole_from_a_list_read_too_long_ago_is_found(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read(db, seed, w.home, [own_followed(w, "home", 8.0)], AT - timedelta(days=5))
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], FRESH)
    packet = built(db, w)
    home = packet.content["schedule"]["calendar"]["home"]
    assert home["complete"] is False and home["reason"] == "stale" and home["age_hours"] == 120.0
    store_packet(db, packet, built_at=AT)
    assert audited(db)["violations"] == 0, "a list five days old that says it may be incomplete is honest"

    pid = handmade(db, w.fixture_id, tampered(packet, lambda c: c["schedule"]["calendar"]["home"].update(complete=True)),
                   AT + timedelta(minutes=1))
    result = audited(db, run=1)
    assert result["violations"] == 1 and result["examples"] == [pid]


def test_a_side_whose_team_is_not_ours_is_found(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    packet = built(db, w)
    pid = handmade(db, w.fixture_id, tampered(packet, lambda c: c["fixture"]["home"].update(id=0)))

    result = audited(db)
    assert result["violations"] == 1 and result["examples"] == [pid], "the reading cannot be found for a team that does not exist"


# ── the matches a packet cites ──────────────────────────────────────────────────────────────────────────────────────────


def test_a_match_that_does_not_exist_is_found_whether_the_platform_follows_it_or_not(db: psycopg.Connection[Any],
                                                                                  seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    packet = built(db, w)

    def invent(c: dict[str, Any]) -> None:
        recent = c["schedule"]["home"]["recent"]
        assert [m["followed"] for m in recent] == [False, True]
        recent[0]["provider_fixture_id"] = 987_654_321
        recent[1]["provider_fixture_id"] = 987_654_322

    pid = handmade(db, w.fixture_id, tampered(packet, invent))
    result = audited(db)
    assert result["violations"] == 2 and result["examples"] == [pid], "two bad checks, one packet"


def test_a_match_with_another_kickoff_than_the_one_the_list_gave_is_found(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    packet = built(db, w)
    moved = (KICKOFF - timedelta(days=2, hours=1)).isoformat()
    pid = handmade(db, w.fixture_id, tampered(packet, lambda c: c["schedule"]["home"]["recent"][0].update(kickoff_at=moved)))

    result = audited(db)
    assert result["violations"] == 1 and result["examples"] == [pid]


def test_a_malformed_match_is_a_violation_and_never_an_error(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    packet = built(db, w)
    pid = handmade(db, w.fixture_id, tampered(packet, lambda c: c["schedule"]["home"]["recent"][0].update(provider_fixture_id="x7")))

    result = audited(db)
    assert result["violations"] == 1 and result["examples"] == [pid], "the whole audit goes on"


def test_a_match_announced_after_the_moment_is_found_when_a_packet_cites_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    announced = cup_tie(w, "home", days_after=5.0, name="Supercopa")
    read(db, seed, w.home, [own_followed(w, "home", 8.0), announced], AT + timedelta(hours=1))  # the list changed after the packet
    packet = built(db, w)
    assert [m["competition"] for m in packet.content["schedule"]["home"]["upcoming"]] == ["Champions League"], "the builder did not know it"

    def cite(c: dict[str, Any]) -> None:
        c["schedule"]["home"]["upcoming"].append({
            "provider_fixture_id": announced["fixture"]["id"], "kickoff_at": announced["fixture"]["date"], "days_after": 5.0,
            "competition": "Supercopa", "type": None, "followed": False, "home": True})

    pid = handmade(db, w.fixture_id, tampered(packet, cite))
    result = audited(db)
    assert result["violations"] == 1 and result["examples"] == [pid]


def test_a_followed_match_recorded_after_the_moment_is_found_when_a_packet_cites_it(db: psycopg.Connection[Any],
                                                                                    seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    packet = built(db, w)
    season, _ = followed_season(db, name="Other League")
    home_id = int(scalar(db.execute("SELECT id FROM core.teams WHERE provider_team_id = %s", (w.home,))))
    other_id = int(scalar(db.execute("SELECT id FROM core.teams WHERE provider_team_id = %s", (w.other,))))
    late = KICKOFF + timedelta(days=4)
    _, provider = fixture(db, season, home_id, other_id, late, created=AT + timedelta(hours=2))  # the schedule came out after the packet

    def cite(c: dict[str, Any]) -> None:
        c["schedule"]["home"]["upcoming"].append({
            "provider_fixture_id": provider, "kickoff_at": late.isoformat(), "days_after": 4.0,
            "competition": "Other League", "type": "domestic_league", "followed": True, "home": True})

    pid = handmade(db, w.fixture_id, tampered(packet, cite))
    result = audited(db)
    assert result["violations"] == 1 and result["examples"] == [pid]


def test_a_match_to_come_cannot_be_cited_as_one_already_played(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    packet = built(db, w)

    def played(c: dict[str, Any]) -> None:
        coming = c["schedule"]["home"]["upcoming"].pop()
        c["schedule"]["home"]["recent"].insert(0, {
            **{k: v for k, v in coming.items() if k != "days_after"}, "days_before": 1.0})

    pid = handmade(db, w.fixture_id, tampered(packet, played))
    result = audited(db)
    assert result["violations"] == 1 and result["examples"] == [pid], "its kick-off is after the moment"
