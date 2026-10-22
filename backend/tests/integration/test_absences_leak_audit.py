"""The nightly proof that no packet listed an absence that was no longer the latest word by its moment (plan F3, ``leak-audit-v3``, rule
``absences_known``).

The rule reads the packets built on the day: every player they list as absent must have been named by an answer of the provider recorded
by the packet's moment, that answer must be the newest one the provider had given about him by then (a player a later answer cleared
is back, and a packet that still lists him read a row that was no longer true), and the kind of absence the packet gives is the one
the answer gave. The packets are written by hand where a faulty reader would have put something wrong in them: a stored packet cannot
be changed afterwards (the table is append-only)."""

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
from fbi.ai.packet import PacketBuilder, store_packet
from fbi.intel import leakage
from fbi.providers.api_football.details import AbsenceRef
from tests.integration.conftest import Seed
from tests.integration.test_availability_history import (
    DOUBT,
    KICKOFF,
    KNEE,
    T1,
    T2,
    T3,
    H,
    World,
    _answer,
    _ref,
    _world,
)

pytestmark = pytest.mark.integration

RULE = "absences_known"


def audited(db: psycopg.Connection[Any], at: datetime) -> dict[str, Any]:
    """The rule on the Bogotá day of ``at`` (one call per day in a test: the audit keeps every run under its ``checked_at``)."""
    out: dict[str, Any] = leakage.audit_day(db, day=local_day(at), at=at + H)[RULE]
    return out


def honest(db: psycopg.Connection[Any], w: World, at: datetime) -> tuple[int, dict[str, Any]]:
    """A packet as the builder makes it for ``at``, stored; returns its id and a copy of its content to tamper with."""
    built = PacketBuilder(db).build(w.fixture, at=at)
    assert built is not None
    return store_packet(db, built, built_at=at), copy.deepcopy(built.content)


def handmade(db: psycopg.Connection[Any], w: World, at: datetime, content: dict[str, Any], *, version: str = "packet-v5") -> int:
    """A stored packet whose content was written by hand: what a faulty reader would have put there."""
    row = db.execute(
        "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id", (w.fixture, version, at, at + H / 60, hashlib.sha256(repr((w.fixture, at, content)).encode()).hexdigest(),
                         Jsonb(content))).fetchone()
    assert row is not None
    return int(row[0])


def tampered(db: psycopg.Connection[Any], w: World, at: datetime, change: Callable[[dict[str, Any]], None]) -> int:
    """The packet of the builder for ``at`` (not stored) with something changed in its content, stored by hand; returns its id."""
    built = PacketBuilder(db).build(w.fixture, at=at)
    assert built is not None
    content = copy.deepcopy(built.content)
    change(content)
    return handmade(db, w, at, content)


def listing(player: int, kind: str = "Missing Fixture") -> dict[str, Any]:
    return {"player_id": player, "name": f"Player {player}", "type": kind, "reason": "Knee Injury", "key": False, "weight": 0.1}


def test_the_rule_is_in_the_audit_and_the_version_says_so() -> None:
    assert RULE in leakage.RULES and leakage.VERSION == "leak-audit-v3" and RULE in (leakage.__doc__ or "")


def test_a_packet_built_by_the_builder_lists_only_what_was_the_latest_word(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001), _ref(w, 9002, DOUBT), _ref(w, 9003, away=True)])
    _answer(db, seed, w, T2, [_ref(w, 9002, DOUBT), _ref(w, 9003, away=True)])      # 9001 has recovered
    honest(db, w, T2 + H)
    assert audited(db, T2 + H) == {"checked": 2, "violations": 0, "examples": []}, "9002 and 9003; the one who recovered is not listed"
    rows = db.execute("SELECT version, n_checked, n_violations FROM intel.audit_checks WHERE rule = %s", (RULE,)).fetchall()
    assert rows == [("leak-audit-v3", 2, 0)]


def test_what_a_later_answer_says_does_not_make_an_honest_packet_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The audit runs after the packet: the answers that came later are history, not a reason to doubt what it read."""
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001), _ref(w, 9003, away=True)])
    honest(db, w, T1 + H)
    _answer(db, seed, w, T3, [])                                                      # everybody recovered afterwards
    assert audited(db, T1 + H) == {"checked": 2, "violations": 0, "examples": []}


def test_a_player_a_later_answer_cleared_but_the_packet_still_lists_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001), _ref(w, 9002, DOUBT)])
    _answer(db, seed, w, T2, [_ref(w, 9002, DOUBT)])                                    # 9001 has recovered
    honest(db, w, T2 + H)

    def keeps_the_old_row(content: dict[str, Any]) -> None:
        content["absences"]["home"]["players"].append(listing(9001))

    bad = tampered(db, w, T2 + H, keeps_the_old_row)
    assert audited(db, T2 + H) == {"checked": 1 + 2, "violations": 1, "examples": [bad]}, "9002 alone; then 9002 and the one who recovered"


def test_a_player_named_only_after_the_moment_or_never_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001)])
    _answer(db, seed, w, T3, [_ref(w, 9001), _ref(w, 9007)])                            # 9007 is named only at T3
    honest(db, w, T1 + H)

    def from_the_future(content: dict[str, Any]) -> None:
        content["absences"]["home"]["players"].append(listing(9007))

    def invented(content: dict[str, Any]) -> None:
        content["absences"]["away"]["players"].append(listing(9100))

    first, second = tampered(db, w, T1 + H, from_the_future), tampered(db, w, T1 + H, invented)
    assert audited(db, T1 + H) == {"checked": 1 + 2 + 2, "violations": 2, "examples": [first, second]}


def test_an_answer_about_the_same_man_in_another_match_is_not_the_answer_of_this_one(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_short, "
               "status_group) VALUES (9893101, %s, %s, %s, %s, 'NS', 'scheduled')", (w.season, w.home_team, w.away_team, KICKOFF + timedelta(days=3)))
    elsewhere = AbsenceRef(9893101, 9050, w.home_provider, "Player 9050", KNEE[0], KNEE[1])
    _answer(db, seed, w, T1, [_ref(w, 9001), elsewhere])
    honest(db, w, T1 + H)                                                              # 9050 is out of the other match, not of this one

    def other_match(content: dict[str, Any]) -> None:
        content["absences"]["home"]["players"].append(listing(9050))

    bad = tampered(db, w, T1 + H, other_match)
    assert audited(db, T1 + H) == {"checked": 1 + 2, "violations": 1, "examples": [bad]}


def test_a_kind_of_absence_that_is_not_the_one_the_answer_gave_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9002, DOUBT)])
    honest(db, w, T1 + H)

    def firmer(content: dict[str, Any]) -> None:
        content["absences"]["home"]["players"][0]["type"] = KNEE[0]

    bad = tampered(db, w, T1 + H, firmer)
    assert audited(db, T1 + H) == {"checked": 2, "violations": 1, "examples": [bad]}


def test_an_answer_recorded_at_the_very_moment_is_known_at_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001)])
    honest(db, w, T1)                                       # named at T1: known at T1
    _answer(db, seed, w, T2, [])                            # and cleared at T2
    honest(db, w, T2)                                       # nobody listed: nothing to prove

    def keeps_him(content: dict[str, Any]) -> None:
        content["absences"]["home"]["players"].append(listing(9001))

    bad = tampered(db, w, T2, keeps_him)                    # the clearing was known at T2: listing him then is a violation
    assert audited(db, T2) == {"checked": 1 + 1, "violations": 1, "examples": [bad]}


def test_a_packet_with_nobody_listed_or_of_a_block_that_is_not_the_builders_does_not_break_the_audit(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001)])
    _answer(db, seed, w, T2, [])
    honest(db, w, T2 + H)                                                              # nobody listed: nothing to prove
    for odd in ({"absences": {"checked": True, "home": {"players": "not a list"}, "away": {"players": [1, "x", {"name": "no id"}]}}},
                {"absences": "none"}, {}):
        handmade(db, w, T2 + H, odd)
    assert audited(db, T2 + H) == {"checked": 0, "violations": 0, "examples": []}
