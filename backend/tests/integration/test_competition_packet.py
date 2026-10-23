"""The AI packet and the dossier on a built competition season (plan F2): the ``phase`` block of ``packet-v4`` (and so v5), the second leg
of ``dossier-v2`` (and so v3), and the rule they share - nothing that came out of the tie reaches a packet built before the match."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from fbi.ai.packet import PACKET_VERSION, PacketBuilder, store_packet
from fbi.competitions import builder
from fbi.intel import leakage
from fbi.intel.narrative import rules_narrative
from tests.integration.conftest import Seed
from tests.integration.test_competition_builder import D0, NOW, champions_league, make_world
from tests.integration.test_competition_context import POISON_STAGES, POISON_TIES, built, kickoff


def test_a_second_leg_packet_carries_the_first_leg_the_aggregate_and_what_the_match_does_to_it(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    _w, f = built(db, seed, 99920)
    at = kickoff(107) - timedelta(hours=3)

    packet = PacketBuilder(db).build(f["r2"], at=at)

    assert packet is not None and packet.version == PACKET_VERSION == "packet-v8"
    c = packet.content
    assert c["fixture"]["stage"] == "knockout", "the round, read by the one classifier of round labels"
    phase = c["phase"]
    assert (phase["version"], phase["stage"], phase["kind"], phase["round_key"]) == (
        "phase-v1", "Round of 16", "knockout", "round_of_16")
    assert phase["tie"]["aggregate_before"] == {"home_side": 0, "away_side": 1}
    assert phase["tie"]["outlook"]["home_side_ahead_if_home_margin_at_least"] == 2
    assert {"block": "phase", "tables": ["core.competition_stages", "core.ties", "core.fixtures", "core.fixture_results"],
            "as_of": at.isoformat(), "version": "phase-v1"} in packet.sources
    assert "phase" not in packet.missing
    context = c["dossier"]["context"]
    assert (context["knockout"], context["final"]) == (True, False)
    assert context["second_leg"] == {"first_leg_at": kickoff(100).isoformat(), "first_leg_score_home_side": 0,
                                     "first_leg_score_away_side": 1, "aggregate_need": "el local remonta"}
    assert c["dossier"]["version"] == "dossier-v4"
    story = rules_narrative(c, [])["que_esta_en_juego"]
    assert "Es una eliminatoria." in story and "Partido de vuelta: la ida terminó 0-1" in story
    assert "En el global, tras los 90 minutos Team 99920-4 va por delante si gana por 2 goles o más" in story
    assert "queda igualado si gana por 1 gol" in story and "deciden las reglas de la competición" in story


def test_the_packet_of_a_season_that_was_never_built_says_so_instead_of_guessing(db: psycopg.Connection[Any],
                                                                                 seed: Seed) -> None:
    w = make_world(db, seed, 99921)
    f = champions_league(w)

    packet = PacketBuilder(db).build(f["r2"], at=kickoff(107) - timedelta(hours=3))

    assert packet is not None
    assert packet.content["phase"] is None and "phase" in packet.missing
    assert packet.content["fixture"]["stage"] == "knockout", "the round alone still reads"
    assert "second_leg" not in packet.content["dossier"]["context"], "no earlier meeting is taken for a first leg"


def test_two_sides_that_met_in_the_group_stage_are_not_in_a_second_leg_when_they_meet_again(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    """The heuristic dossier-v1 had: the last meeting of the pair in the 60 days before, whatever it was. A group-stage match
    forty days earlier made the final a 'second leg'."""
    w = make_world(db, seed, 99922)
    w.fixture("Group Stage - 6", 1, 2, 0, (2, 2))
    w.fixture("Group Stage - 6", 3, 4, 0, (0, 1))
    final = w.fixture("Final", 2, 1, 40, None, "NS")
    builder.build_one(db, w.season, now=NOW)

    packet = PacketBuilder(db).build(final, at=D0 + timedelta(days=39))

    assert packet is not None
    context = packet.content["dossier"]["context"]
    assert context["final"] is True and "second_leg" not in context
    assert packet.content["phase"]["role"] == "final" and packet.content["phase"]["tie"]["outlook"] == {
        "kind": "single_match"}
    assert packet.content["phase"]["tie"]["previous"] == [], "the group-stage meeting is another stage, not a leg"


def test_a_qualifying_round_is_a_knockout_round_for_the_packet_and_the_dossier(db: psycopg.Connection[Any],
                                                                               seed: Seed) -> None:
    _w, f = built(db, seed, 99923)

    packet = PacketBuilder(db).build(f["q2"], at=kickoff(7) - timedelta(hours=3))

    assert packet is not None
    assert packet.content["fixture"]["stage"] == "knockout"
    assert packet.content["dossier"]["context"]["knockout"] is True
    assert packet.content["phase"]["kind"] == "qualifying" and packet.content["phase"]["tie"]["leg"] == 2


def test_nothing_that_came_out_of_the_tie_changes_a_packet_built_before_the_match(db: psycopg.Connection[Any],
                                                                                 seed: Seed) -> None:
    w, f = built(db, seed, 99924)
    at = kickoff(107) - timedelta(hours=3)
    before = PacketBuilder(db).build(f["r2"], at=at)
    first_leg = PacketBuilder(db).build(f["r1"], at=kickoff(100) - timedelta(hours=3))
    assert before is not None and first_leg is not None

    db.execute(POISON_TIES)
    db.execute(POISON_STAGES)
    w.set_goals(f["r2"], 8, 0)  # the second leg, as it ended
    db.execute("UPDATE core.fixture_results SET settled_at = %s WHERE fixture_id = %s",
               (kickoff(107) + timedelta(hours=2), f["r2"]))

    after = PacketBuilder(db).build(f["r2"], at=at)
    first_after = PacketBuilder(db).build(f["r1"], at=kickoff(100) - timedelta(hours=3))

    assert after is not None and first_after is not None
    assert after.content == before.content and after.hash == before.hash, "the whole packet, not only its phase block"
    assert first_after.content == first_leg.content and first_after.hash == first_leg.hash


# ── the nightly proof: leak-audit-v3 reads the packets of the day ───────────


def audited(db: psycopg.Connection[Any], at: Any) -> dict[str, Any]:
    out: dict[str, Any] = leakage.audit_day(db, day=local_day(at), at=at + timedelta(hours=1))["tie_legs_known"]
    return out


def insert_packet(db: psycopg.Connection[Any], fixture_id: int, at: Any, content: dict[str, Any]) -> int:
    """A stored packet whose content is written by hand: what a faulty reader would have put there."""
    row = db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) "
                     "VALUES (%s, 'packet-v4', %s, %s, %s, %s) RETURNING id",
                     (fixture_id, at, at, "0" * 64, Jsonb(content))).fetchone()
    assert row is not None
    return int(row[0])


def test_the_audit_counts_each_leg_a_stored_packet_cites_and_finds_them_recorded_in_time(db: psycopg.Connection[Any],
                                                                                         seed: Seed) -> None:
    _w, f = built(db, seed, 99925)
    at = kickoff(107) - timedelta(hours=3)
    packet = PacketBuilder(db).build(f["r2"], at=at)
    assert packet is not None
    store_packet(db, packet, built_at=at)

    assert "tie_legs_known" in leakage.RULES and leakage.VERSION == "leak-audit-v6"
    assert audited(db, at) == {"checked": 1, "violations": 0, "examples": []}


def test_a_packet_that_cites_a_leg_recorded_after_its_moment_is_a_violation(db: psycopg.Connection[Any],
                                                                            seed: Seed) -> None:
    _w, f = built(db, seed, 99926)
    at = kickoff(107) - timedelta(hours=3)
    packet = PacketBuilder(db).build(f["r2"], at=at)
    assert packet is not None
    packet_id = store_packet(db, packet, built_at=at)
    db.execute("UPDATE core.fixture_results SET settled_at = %s WHERE fixture_id = %s",
               (at + timedelta(minutes=1), f["r1"]))

    assert audited(db, at) == {"checked": 1, "violations": 1, "examples": [packet_id]}


@pytest.mark.parametrize("cited", ["the_leg_played_later", "the_match_itself", "a_fixture_that_does_not_exist"])
def test_a_packet_cannot_cite_a_leg_that_is_not_an_earlier_match(db: psycopg.Connection[Any], seed: Seed,
                                                                cited: str) -> None:
    """Every result is recorded long before the packet: the only thing wrong is WHICH match the packet names."""
    _w, f = built(db, seed, 99927 if cited == "the_leg_played_later" else 99928 if cited == "the_match_itself" else 99929)
    at = kickoff(100) - timedelta(hours=3)
    db.execute("UPDATE core.fixture_results SET settled_at = %s", (kickoff(-30),))
    leg = {"the_leg_played_later": f["r2"], "the_match_itself": f["r1"], "a_fixture_that_does_not_exist": 987654321}[cited]
    packet_id = insert_packet(db, f["r1"], at, {"phase": {"tie": {"previous": [{"fixture_id": leg}]}}})

    assert audited(db, at) == {"checked": 1, "violations": 1, "examples": [packet_id]}


@pytest.mark.parametrize("content", [{}, {"phase": None}, {"phase": {"tie": None}}, {"phase": {"tie": {"previous": []}}},
                                     {"phase": {"tie": {"previous": None}}}])
def test_a_packet_that_cites_no_leg_is_not_counted_and_never_breaks_the_audit(db: psycopg.Connection[Any], seed: Seed,
                                                                             content: dict[str, Any]) -> None:
    _w, f = built(db, seed, 99930)
    at = kickoff(100) - timedelta(hours=3)
    insert_packet(db, f["r1"], at, content)

    assert audited(db, at) == {"checked": 0, "violations": 0, "examples": []}
