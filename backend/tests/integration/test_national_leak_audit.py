"""The nightly proof that no packet knew the people of a national-team match before the world did (plan F3, ``leak-audit-v3``, rule
``national_known``).

The rule reads the packets built on the day that carry ``dossier.national``: every match the block cites must have kicked off before the
match of the packet and had its result recorded by the packet's moment, a sheet it says is the match's own must have been fetched by
then, and no day it gives for a club may be later than the day of the packet. The packets are written by hand where a faulty reader
would have put something wrong in them: a stored packet cannot be changed afterwards (the table is append-only)."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from fbi.ai.packet import PacketBuilder, store_packet
from fbi.intel import leakage
from tests.integration.test_national_block import AT, KICKOFF, Squad, played, settle, sheet
from tests.integration.test_player_history_store import World, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration

RULE = "national_known"
HONEST_CHECKS = 11
"""One check per cited fact in the block of Spain with its own sheet: the sheet (1), and for the three players the last squad (3), the
last cap (3), the last club match of the two who have a form (2) and the two club days of those with a known club (2)."""


def audited(w: World, at: datetime = AT) -> dict[str, Any]:
    """The rule on the Bogotá day of ``at`` (one call per day in a test: the audit keeps every run under its ``checked_at``)."""
    out: dict[str, Any] = leakage.audit_day(w.db, day=local_day(at), at=at + timedelta(hours=1))[RULE]
    return out


def honest(s: Squad) -> tuple[int, dict[str, Any]]:
    """A packet as the builder makes it, stored; returns its id and a copy of its content to tamper with."""
    built = PacketBuilder(s.w.db).build(s.target, at=AT)
    assert built is not None
    return store_packet(s.w.db, built, built_at=AT), copy.deepcopy(built.content)


def handmade(s: Squad, content: dict[str, Any], *, version: str = "packet-v5") -> int:
    """A stored packet whose content was written by hand: what a faulty reader would have put there."""
    row = s.w.db.execute(
        "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id", (s.target, version, AT, AT + timedelta(minutes=1), hashlib.sha256(repr((s.target, content)).encode()).hexdigest(),
                         Jsonb(content))).fetchone()
    assert row is not None
    return int(row[0])


def tampered(s: Squad, change: Callable[[dict[str, Any]], None], side: str = "home") -> int:
    """The packet of the builder (not stored) with something changed in the block of one side, stored by hand; returns its id."""
    built = PacketBuilder(s.w.db).build(s.target, at=AT)
    assert built is not None
    content = copy.deepcopy(built.content)
    change(content["dossier"]["national"][side])
    return handmade(s, content)


@pytest.fixture()
def squad(world: World) -> Squad:  # noqa: F811
    s = Squad(world)
    s.build()
    return s


def test_the_rule_is_in_the_audit_and_the_version_says_so() -> None:
    assert RULE in leakage.RULES and leakage.VERSION == "leak-audit-v5" and "national_known" in (leakage.__doc__ or "")


def test_a_packet_built_by_the_builder_cites_only_what_was_known(squad: Squad) -> None:
    honest(squad)
    assert audited(squad.w) == {"checked": HONEST_CHECKS, "violations": 0, "examples": []}
    rows = squad.w.db.execute("SELECT version, n_checked, n_violations FROM intel.audit_checks WHERE rule = %s", (RULE,)).fetchall()
    assert rows == [("leak-audit-v5", HONEST_CHECKS, 0)]


def test_the_previous_match_that_stands_in_for_the_call_up_is_checked_too(squad: Squad) -> None:
    squad.w.db.execute("UPDATE core.fixture_lineups SET fetched_at = %s WHERE fixture_id = %s", (AT + timedelta(minutes=1), squad.target))
    _pid, content = honest(squad)
    assert content["dossier"]["national"]["home"]["squad"] == "last_match"
    # the sheet of the previous match (1) and, of the two men who started it, the last squad (2), the last cap (2), the form (2), the club (2)
    assert audited(squad.w) == {"checked": 9, "violations": 0, "examples": []}


def test_a_packet_of_a_club_match_or_of_an_earlier_version_has_nothing_to_prove(squad: Squad) -> None:
    club_match = squad.w.fixture(squad.alpha, squad.rival, 44, status="scheduled")
    built = PacketBuilder(squad.w.db).build(club_match, at=AT)
    assert built is not None
    store_packet(squad.w.db, built, built_at=AT)
    _pid, content = honest(squad)
    del content["dossier"]["national"]
    handmade(squad, content, version="packet-v4")
    assert audited(squad.w) == {"checked": HONEST_CHECKS, "violations": 0, "examples": []}, "only the honest one of the national match"


def test_a_match_cited_whose_result_was_recorded_after_the_moment_is_a_violation(squad: Squad) -> None:
    late = squad.w.fixture(squad.alpha, squad.rival, 30)
    sheet(squad.w, late, "home", {squad.p1: "Pedro Uno"})
    played(squad.w, late, "home", squad.p1, 90)
    settle(squad.w, late, AT + timedelta(minutes=10))
    honest(squad)

    def cite(block: dict[str, Any]) -> None:
        block["players"][0]["form"]["last_fixture"] = late

    bad = tampered(squad, cite)
    assert audited(squad.w) == {"checked": 2 * HONEST_CHECKS, "violations": 1, "examples": [bad]}


def test_a_match_cited_that_is_the_match_itself_or_a_later_one_is_a_violation(squad: Squad) -> None:
    after = squad.w.fixture(squad.spain, squad.rival, 40, national=True)
    settle(squad.w, after, AT - timedelta(hours=1))        # (even with a result recorded: it began after the match)

    def itself(block: dict[str, Any]) -> None:
        block["players"][0]["caps"]["last_cap_fixture"] = squad.target

    def later(block: dict[str, Any]) -> None:
        block["players"][1]["caps"]["last_squad_fixture"] = after

    first, second = tampered(squad, itself), tampered(squad, later)
    assert audited(squad.w) == {"checked": 2 * HONEST_CHECKS, "violations": 2, "examples": [first, second]}


def test_a_match_cited_that_does_not_exist_is_a_violation(squad: Squad) -> None:
    def ghost(block: dict[str, Any]) -> None:
        block["players"][2]["caps"]["last_cap_fixture"] = 999_999_999

    bad = tampered(squad, ghost)
    assert audited(squad.w) == {"checked": HONEST_CHECKS, "violations": 1, "examples": [bad]}


def test_a_stand_in_sheet_of_a_match_whose_result_was_recorded_after_the_moment_is_a_violation(squad: Squad) -> None:
    squad.w.db.execute("UPDATE core.fixture_lineups SET fetched_at = %s WHERE fixture_id = %s", (AT + timedelta(minutes=1), squad.target))
    pid, _content = honest(squad)
    assert audited(squad.w) == {"checked": 9, "violations": 0, "examples": []}
    # the packet cited the previous match as settled; the result in the database says it was recorded after the moment
    squad.w.db.execute("UPDATE core.fixture_results SET settled_at = %s WHERE fixture_id = %s", (AT + timedelta(minutes=5), squad.m2))
    found = audited(squad.w, AT + timedelta(minutes=1))
    assert found == {"checked": 9, "violations": 5, "examples": [pid]}, "the sheet's match, and the last squad and cap of the two men who started it"


def test_a_sheet_said_to_be_the_matchs_own_but_fetched_after_the_moment_is_a_violation(squad: Squad) -> None:
    pid, _content = honest(squad)
    squad.w.db.execute("UPDATE core.fixture_lineups SET fetched_at = %s WHERE fixture_id = %s", (AT + timedelta(minutes=1), squad.target))
    assert audited(squad.w) == {"checked": HONEST_CHECKS, "violations": 1, "examples": [pid]}


def test_a_day_of_a_club_later_than_the_day_of_the_packet_is_a_violation(squad: Squad) -> None:
    def since(block: dict[str, Any]) -> None:
        block["players"][0]["club"]["since"] = (AT + timedelta(days=1)).date().isoformat()

    def seen(block: dict[str, Any]) -> None:
        block["players"][1]["club"]["last_seen"] = (AT + timedelta(days=3)).date().isoformat()

    first, second = tampered(squad, since), tampered(squad, seen)
    assert audited(squad.w) == {"checked": 2 * HONEST_CHECKS, "violations": 2, "examples": [first, second]}


def test_what_is_known_at_the_very_moment_is_known(squad: Squad) -> None:
    """A result recorded, a sheet fetched and a day given at exactly the moment (or the day) of the packet are not later than it."""
    squad.w.db.execute("UPDATE core.fixture_results SET settled_at = %s WHERE fixture_id = %s", (AT, squad.m2))
    squad.w.db.execute("UPDATE core.fixture_lineups SET fetched_at = %s WHERE fixture_id = %s", (AT, squad.target))
    honest(squad)

    def today(block: dict[str, Any]) -> None:
        block["players"][0]["club"]["since"] = AT.date().isoformat()
        block["players"][1]["club"]["last_seen"] = AT.date().isoformat()

    tampered(squad, today)
    assert audited(squad.w) == {"checked": 2 * HONEST_CHECKS, "violations": 0, "examples": []}


def test_a_match_with_no_result_a_twin_of_the_match_or_a_sheet_of_the_other_side_is_a_violation(squad: Squad) -> None:
    unplayed = squad.w.fixture(squad.alpha, squad.rival, 29, status="scheduled")                     # (never settled)
    twin = squad.w.fixture(squad.spain, squad.rival, 0, national=True, at=KICKOFF)                   # (the very same kick-off)
    settle(squad.w, twin, AT - timedelta(hours=1))

    def cite(fixture: int) -> Callable[[dict[str, Any]], None]:
        def change(block: dict[str, Any]) -> None:
            block["players"][0]["form"]["last_fixture"] = fixture
        return change

    def other_side(block: dict[str, Any]) -> None:
        block.update(squad="lineup", players=[])         # claims the sheet of the away side, which nobody fetched

    first, second = tampered(squad, cite(unplayed)), tampered(squad, cite(twin))
    third = tampered(squad, other_side, side="away")
    assert audited(squad.w) == {"checked": 3 * HONEST_CHECKS + 1, "violations": 3, "examples": [first, second, third]}


def test_a_block_that_is_not_the_one_the_builder_makes_does_not_break_the_audit(squad: Squad) -> None:
    def broken(block: dict[str, Any]) -> None:
        block["players"] = "not a list"

    tampered(squad, broken)
    assert audited(squad.w) == {"checked": 0, "violations": 0, "examples": []}
